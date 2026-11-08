"""Orchestrates price discovery, independent pool verification and safety research."""
from __future__ import annotations
import time, threading, uuid
from . import providers
from .source_scanner import SourceError, number, candidate, gecko_pause_seconds
from .scoring import score_token
from .patterns import detect_patterns
from .prebreakout import prebreakout
from .store import Store

# Une cotation vieille de plusieurs minutes ne doit pas être présentée comme un signal actuel.
LIVE_MAX_AGE_S = 300
# Réévaluation ciblée des actifs récents, sans sacrifier la découverte de nouveaux coins.
FOLLOW_ACTIVE_S = 1800
RECHECK_AFTER_S = 65

class Radar:
    def __init__(self, path, wallets_path, interval=20, limit=14, rpc_url=None):
        self.store=Store(path)
        self.interval=max(20,int(interval))
        self.limit=max(1,min(25,int(limit)))
        self.wallet_monitor=providers.PublicWalletMonitor(self.store,wallets_path,rpc_url or 'https://api.mainnet-beta.solana.com')
        self.lock=threading.Lock()
        self.status={'instance_id':uuid.uuid4().hex,'running':False,'last_scan':None,'errors':[],'cycle':0,'scanned':0,'discovered':0,'mode':'live',
                     'interval_seconds':self.interval,'next_scan':None,'started_at':None,'finished_at':None,
                     'duration_seconds':None,'phase':'En attente du premier scan',
                     'progress_done':0,'progress_total':0,'last_outcome':None,'new_tokens':0,
                     'new_candidates':0,'pairs_found':0,'queued_social':0}
        self.stop_event=threading.Event()
        self.refresh_event=threading.Event()
        self._last_social_wake=0

    def social_wakeup(self, mint):
        """Read-only scan trigger, rate-limited; do not duplicate scan workers."""
        now=time.time()
        self.store.enqueue(mint)
        if (not self.stop_event.is_set() and not self.status['running']
              and now-self._last_social_wake>=30 and now-(self.status['last_scan'] or 0)>=15):
            self._last_social_wake=now
            self.refresh_event.set()

    def request_scan(self):
        """Queue one early scan in the existing worker; never start a competing worker."""
        if self.stop_event.is_set() or self.status['running'] or self.refresh_event.is_set():
            return False
        self.refresh_event.set()
        self.status['next_scan']=time.time()
        return True

    def run_once(self):
        if not self.lock.acquire(blocking=False): return False
        started=time.time()
        self.status.update(running=True,started_at=started,phase='Recherche de nouveaux pools',
                           progress_done=0,progress_total=0,next_scan=None,new_tokens=0)
        warnings=[]
        success=False
        try:
            t=time.time()
            try:
                discovered,w=providers.discoveries()
                warnings.extend(w)
            except Exception as exc:
                discovered={};warnings.append(f'Découverte: {type(exc).__name__}: {str(exc)[:150]}')
            self.status['phase']='Surveillance des wallets publics'
            try:
                wallet_mints,w=self.wallet_monitor.scan()
                warnings.extend(w)
            except Exception as exc:
                wallet_mints=set();warnings.append(f'Wallet: {type(exc).__name__}: {str(exc)[:150]}')
            for mint in wallet_mints:
                discovered.setdefault(mint,set()).add('wallet_public')
            # J7 mentions can discover a CA before DEX indexation. They never
            # increase a token's numerical score; no CA means no market match.
            # Monitor old candidates as well, with a strict budget and a share for new discoveries.
            previous=self.store.list_coins(1000)
            known={p['mint'] for p in previous}
            def priority(x):
                mint,src=x
                return (4 if 'j7_direct_contract' in src else 0,
                        3 if 'wallet_public' in src else 0,
                        2 if 'gecko_new_pools' in src else 0,
                        1 if 'gecko_trending_pools' in src else 0,
                        len(src))
            fresh=[m for m,_ in sorted(discovered.items(),key=priority,reverse=True) if m not in known]
            # Le problème v6.5 : ne reprenait que les archives les plus anciennes,
            # laissant les bons candidats récents vieillir pendant des heures.
            # Réserver environ la moitié des vérifications aux monnaies en cours
            # d'observation, en maintenant un quota non nul pour les nouveaux pools.
            # A coin with a preliminary pre-impulse pattern must receive a second
            # observation promptly, before it potentially starts to move.
            have_prewatch=any(p.get('prewatch') and t-p.get('last_seen',0)<FOLLOW_ACTIVE_S
                              for p in previous)
            old_budget = max(1, self.limit // 2 if have_prewatch else self.limit // 3)
            urgent = self.store.queue_due(min(max(1, self.limit // 4), old_budget))
            for q in urgent:
                discovered.setdefault(q['mint'], set()).add(q['source'])
            urgent_mints = [q['mint'] for q in urgent]
            excluded = set(urgent_mints) | set(fresh)
            # Les pièces encore pertinentes approchant de l'expiration sont vérifiées
            # AVANT les archives ; priorité aux alertes et au classement courant.
            recent = [p for p in previous if p['mint'] not in excluded
                      and t-p.get('last_seen', 0) >= RECHECK_AFTER_S
                      and t-p.get('last_seen', 0) <= FOLLOW_ACTIVE_S]
            recent.sort(key=lambda p:(
                bool(p.get('prewatch') and not p.get('pre_impulse')),
                p.get('status') == 'a_etudier',
                p.get('status') == 'surveillance',
                bool(p.get('patterns')),
                p.get('score', 0),
                min(t-p.get('last_seen', 0), LIVE_MAX_AGE_S * 2)), reverse=True)
            # Un budget limité pour les anciennes observations (historique / résultats).
            archive = [p for p in previous if p['mint'] not in excluded
                       and t-p.get('last_seen',0) > FOLLOW_ACTIVE_S]
            archive.sort(key=lambda p:p.get('last_seen', 0))
            available_old = max(0, old_budget-len(urgent_mints))
            selected_old = [p['mint'] for p in recent[:max(0, available_old-1)]]
            if archive and len(selected_old)<available_old:
                selected_old.append(archive[0]['mint'])
            selected_old.extend(p['mint'] for p in recent[len(selected_old):available_old])
            fresh_budget = max(1, self.limit-len(urgent_mints)-len(selected_old))
            chosen = list(dict.fromkeys(
                urgent_mints+fresh[:fresh_budget]+selected_old+fresh[fresh_budget:]))[:self.limit]
            # These numbers expose whether the bottleneck is the source, pair matching,
            # safety analysis or browser filters (they are otherwise easy to confuse).
            self.status.update(discovered=len(discovered),new_candidates=len(fresh),
                               queued_social=len(urgent))
            self.status.update(progress_total=len(chosen),progress_done=0,
                               phase='Récupération des prix et volumes' if chosen else 'Aucun nouveau candidat à examiner')
            if not chosen:
                self.status.update(scanned=0,pairs_found=0,cycle=self.status['cycle']+1,errors=warnings[:16]);
                success=True
                return True
            try: pairs=providers.dex_pairs_batch(chosen)
            except Exception as exc:
                warnings.append(f'DexScreener: {type(exc).__name__}: {str(exc)[:150]}')
                self.status.update(scanned=0,cycle=self.status['cycle']+1,errors=warnings[:16]);return False
            self.status['pairs_found']=len(pairs)
            # Snapshot timestamp is when the batch quotes arrived, not the
            # beginning of potentially long discovery / API-limited scans.
            pair_observed_at=time.time()
            self.status['phase']='Vérification des cotations indépendantes'
            gecko,w=providers.quote_same_pools(pairs)
            warnings.extend(w)
            self.status['phase']='Analyse des tokens et des risques'
            new_count=0
            for index,mint in enumerate(chosen):
                pair=pairs.get(mint) or {}
                if not pair:
                    self.status['progress_done']=index+1
                    self.store.queue_done(mint,False)
                    continue  # No unverified market in the coin list.
                prior=self.store.get(mint) or {}
                if not prior and pair: new_count+=1
                sources=set(prior.get('sources') or []) | discovered.get(mint,set())
                safety=self.store.cached_safety(mint)
                if safety is None:
                    try:
                        safety=providers.rug_report(mint)
                        self.store.save_safety(mint,safety)
                    except Exception as exc:
                        warnings.append(f'RugCheck {mint[:6]}…: {type(exc).__name__}')
                        safety={}
                wallets=self.store.wallet_hits(mint)
                history=self.store.history(mint,90)
                live_price=number(pair.get('priceUsd'))
                if live_price is not None and live_price>0:
                    history=history+[{'ts':t,'price':live_price}]
                patterns=detect_patterns(pair,history, wallets, t)
                social=self.store.social_context(mint)
                report=score_token(pair,safety,gecko.get(mint),sources,wallets,t)
                pressure=prebreakout(pair,self.store.market_snapshots(mint,12),report,safety,pair_observed_at)
                if pressure['prewatch']:
                    patterns.append({'key':'pre_impulse' if pressure['confirmed'] else 'prewatch',
                      'label':'Pression acheteuse avant mouvement' if pressure['confirmed'] else 'Pression acheteuse à confirmer',
                      'why':('Deux relevés réels espacés de 45 s à 8 min sur la même paire : '
                             'prix stable, ≥65 % des transactions 5 min à l’achat, '
                             'volume 5 min ≥1 500 $, liquidité ≥12 000 $. '
                             'Acheteurs uniques et volume organique non vérifiés.'
                             if pressure['confirmed'] else
                             'Premier relevé : prix relativement stable avec activité acheteuse. '
                             'Attend un second contrôle (les transactions ne sont pas des acheteurs uniques).')})
                # A strong early setup can be review-worthy BEFORE price momentum.
                # Keep the original numeric score, risk gates and proof coverage.
                if (pressure['confirmed'] and report['status']=='surveillance'
                      and report['score']>=50):
                    report['status']='a_etudier' 
                base=pair.get('baseToken') or {}
                liquidity=number((pair.get('liquidity') or {}).get('usd'))
                txns=(pair.get('txns') or {}).get('h1') or {}
                result={
                    'mint':mint,'symbol':str(base.get('symbol') or prior.get('symbol') or '?')[:25],
                    'name':str(base.get('name') or prior.get('name') or '?')[:80],
                    'price_usd':number(pair.get('priceUsd')),'liquidity_usd':liquidity,
                    'volume_h1_usd':number((pair.get('volume') or {}).get('h1')),
                    'market_cap_usd':number(pair.get('marketCap')),'fdv_usd':number(pair.get('fdv')),
                    'buys_h1':number(txns.get('buys')),'sells_h1':number(txns.get('sells')),
                    'change_m5_pct':number((pair.get('priceChange') or {}).get('m5')),
                    'change_h1_pct':number((pair.get('priceChange') or {}).get('h1')),
                    'pair_address':pair.get('pairAddress') if pair else None,
                    'pair_dex':str(pair.get('dexId') or '')[:50],
                    'pair_url':str(pair.get('url') or '')[:300],
                    'sources':sorted(sources),'wallets':wallets[:10],
                    'patterns':patterns,
                    'prewatch':pressure['prewatch'],
                    'pre_impulse':pressure['confirmed'],
                    'pressure_buys_m5':pressure['snapshot']['buys_m5'],
                    'pressure_sells_m5':pressure['snapshot']['sells_m5'],
                    'volume_m5_usd':pressure['snapshot']['volume_m5'],
                    'pressure_buy_share':pressure.get('buy_share'),
                    'safety_summary':{'mint_active':safety.get('mint_active'),
                        'freeze_active':safety.get('freeze_active'),'top10_pct':safety.get('top10_pct'),
                        'rugcheck_score':safety.get('rugcheck_risk_score'),
                        'lp_locked_pct':(safety.get('lp_locked_by_pool') or {}).get(pair.get('pairAddress')) if pair else None},
                    **report}
                result['social_context']=social
                if result['pre_impulse']:
                    result['pre_impulse_first_at']=(prior.get('pre_impulse_first_at') or pair_observed_at)
                    result['pre_impulse_first_price']=(prior.get('pre_impulse_first_price') or live_price)
                else:
                    result['pre_impulse_first_at']=prior.get('pre_impulse_first_at')
                    result['pre_impulse_first_price']=prior.get('pre_impulse_first_price')
                age=result.get('age_min')
                result['regime']='lancement' if age is not None and age<=180 else 'token établi'
                official=social.get('verified_influential_authors_10m',0)
                upstream=social.get('j7_unconfirmed_authors_10m',0)
                influencers=official+upstream
                if influencers>=2 and social['acceleration']>0:
                    result['patterns'].append({'key':'social_attention','label':'Mentions J7 multi-comptes',
                        'why':f"Contrat Solana exact, {influencers} auteurs distincts (≥50 k abonnés), badge signalé par J7 ou confirmé X ; part des abonnés humains inconnue."})
                # X official verification gets higher weight than J7's upstream flags.
                # It changes analysis PRIORITY only, never the safety/status or market score.
                result['attention_score']=min(30,6*official+3*upstream+(6 if influencers>=2 else 0))
                result['priority_score']=round(min(100,report['market_score']/50*70+result['attention_score']),1)
                result['analysis_version']='v6.7'
                # Require core evidence; a 100% coverage number alone does not prove safety.
                result['eligible']=(not result['risks'] and result['coverage']>=90
                    and liquidity is not None and liquidity>=5000
                    and safety.get('mint_active') is False and safety.get('freeze_active') is False
                    and safety.get('top10_pct') is not None and safety.get('rugcheck_risk_score') is not None)
                result['pair_changed'] = bool(prior.get('pair_address') and prior.get('pair_address')!=result['pair_address'])
                self.store.save_market_snapshot(mint,pressure['snapshot'])
                self.store.save_coin(result,time.time())
                self.store.record_signal(result)
                self.store.observe(mint,live_price)
                self.store.queue_done(mint,True)
                self.status['progress_done']=index+1
            self.status.update(scanned=len(chosen),cycle=self.status['cycle']+1,errors=warnings[:16],new_tokens=new_count)
            success=True
            return True
        except Exception as exc:
            self.status['errors']=(warnings+[f'Erreur cycle: {type(exc).__name__}: {str(exc)[:150]}'])[:16]
            return False
        finally:
            finished=time.time()
            pause=gecko_pause_seconds()
            self.status['gecko_resume_at']=finished+pause if pause else None
            if pause:
                self.status['errors']=[e for e in self.status.get('errors',[]) if not ('gecko' in e.lower() and '429' in e)]
            self.status.update(running=False,last_scan=finished,finished_at=finished,
                               duration_seconds=round(finished-started,2),last_outcome='ok' if success else 'error',
                               phase='Scan terminé' if success else 'Scan interrompu')
            self.lock.release()

    def run_loop(self):
        while not self.stop_event.is_set():
            self.run_once()
            self.evaluate_due()
            if self.stop_event.is_set(): break
            due=time.time()+self.interval
            self.status['next_scan']=due
            # A manual refresh wakes this wait but cannot overlap a running scan.
            self.refresh_event.wait(self.interval)
            self.refresh_event.clear()
            self.status['next_scan']=None

    def evaluate_due(self):
        """Independent follow-up budget, including risky and hidden candidates."""
        due=self.store.evaluation_due()
        if not due:return
        try:
            pairs=providers.dex_pairs_batch(due)
            for mint in due:
                self.store.observe(mint,number((pairs.get(mint) or {}).get('priceUsd')))
            self.store.research_report()
        except Exception as exc:
            self.status['errors']=(self.status['errors']+[f'Suivi des résultats: {type(exc).__name__}'])[-16:]

    def view(self):
        coins=self.store.list_coins()
        now=time.time()
        for c in coins:
            hist=self.store.history(c['mint'],60)
            c['history']=[{'ts':p['ts'],'price':p['price']} for p in hist]
            c['social_mentions']=self.store.social_for_mint(c['mint'],5)
            c['research']=self.store.research_for(c['mint'])
            elapsed=max(0,now-c.get('last_seen',0))
            c['data_age_seconds']=int(elapsed)
            c['fresh']=elapsed<=LIVE_MAX_AGE_S
            # Important: override UNIQUEMENT sur les données renvoyées à l'interface,
            # jamais dans la base d'historique. Un vieux « À étudier » n'est pas live.
            if not c['fresh']:
                c['previous_status']=c.get('status')
                c['status']='expire'
            if (c.get('first_price_usd') or 0)>0 and (c.get('price_usd') or 0)>0:
                c['observed_change_pct']=round((c['price_usd']/c['first_price_usd']-1)*100,2)
            else: c['observed_change_pct']=None
        coins.sort(key=lambda c:(c['fresh'],
            {'a_etudier':3,'surveillance':2,'incomplet':1,'risque':0}.get(c.get('status'),0),
            len(c.get('patterns') or []), c['score']),reverse=True)
        live=[c for c in coins if c['fresh']]
        return {'coins':coins, 'stats':{'total':len(coins),'stored':self.store.count_coins(),
                'live':len(live),'expired':len(coins)-len(live),
                'interesting':sum(c['status']=='a_etudier' for c in live),
                'incomplete':sum(c['status']=='incomplet' for c in live),
                'risky':sum(c['status']=='risque' for c in live)},
                'status':dict(self.status)}
