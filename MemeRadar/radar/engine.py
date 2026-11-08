"""Orchestrates price discovery, independent pool verification and safety research."""
from __future__ import annotations
import time, threading, uuid
from concurrent.futures import ThreadPoolExecutor
from . import providers
from .source_scanner import SourceError, number, candidate, gecko_pause_seconds
from .scoring import score_token
from .patterns import detect_patterns
from .prebreakout import prebreakout
from .curve import assess_curve
from .early_watch import observe_early
from .narratives import contextual_matches
from .narrative_intelligence import watch_evidence
from .fast_lane import FastLane
from .realtime import LaunchQuoteWorker,compare_cohorts
from .selection import discovery_priority,early_rank,select_candidates
from .onchain_risk import SolanaRiskObserver
from .store import Store
from .strategies import enforce_gate

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
                     'new_candidates':0,'pairs_found':0,'queued_social':0,'engine_version':'v2.0','known_total':0,'scan_stages_s':{}}
        self.stop_event=threading.Event()
        self.refresh_event=threading.Event()
        self._last_social_wake=0
        self._last_prune=0
        # Wallet RPC runs independently: an overloaded public RPC must NEVER
        # delay discovery or token scoring by 9-45 seconds.
        self.fast_lane=FastLane(self.store,self.stop_event)
        self.launch_quotes=LaunchQuoteWorker(self.store,self.stop_event)
        self.risk_observer=SolanaRiskObserver(self.store,self.stop_event,rpc_url or 'https://api.mainnet-beta.solana.com')
        self._wallet_lock=threading.Lock()
        self._wallet_running=False
        self._wallet_pending=set()
        self._wallet_errors=[]
        self._wallet_started=float('-inf')  # a fresh machine (low uptime) must still start the first scan

    def social_wakeup(self, mint):
        """Read-only scan trigger, rate-limited; do not duplicate scan workers."""
        now=time.time()
        self.store.enqueue(mint)
        self.fast_lane.submit(mint)
        if (not self.stop_event.is_set() and not self.status['running']
              and now-self._last_social_wake>=30 and now-(self.status['last_scan'] or 0)>=15):
            self._last_social_wake=now
            self.refresh_event.set()

    def _scan_wallet_background(self):
        mints=set(); warnings=[]
        try:
            mints,warnings=self.wallet_monitor.scan()
        except Exception as exc:
            warnings=['Wallet RPC: '+type(exc).__name__]
        with self._wallet_lock:
            self._wallet_pending.update(mints)
            self._wallet_errors.extend(warnings[:8])
            self._wallet_running=False
        # Wake next cycle, but not until the current one is done.
        for mint in mints:
            self.store.enqueue(mint,'wallet_public')
        if mints and not self.stop_event.is_set():
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
        safety_pool=None
        warnings=[]
        success=False
        stages={}
        stage_started=time.monotonic()
        fresh_selected=0
        selected_count=0
        self.status.update(discovered=0,new_candidates=0,scanned=0,pairs_found=0)
        try:
            t=time.time()
            try:
                discovered,w=providers.discoveries()
                warnings.extend(w)
            except Exception as exc:
                discovered={};warnings.append(f'Découverte: {type(exc).__name__}: {str(exc)[:150]}')
            stages['discovery']=round(time.monotonic()-stage_started,2)
            stage_started=time.monotonic()
            self.status['phase']='Surveillance asynchrone des wallets publics'
            with self._wallet_lock:
                wallet_mints=set(self._wallet_pending)
                self._wallet_pending.clear()
                warnings.extend(self._wallet_errors)
                self._wallet_errors=[]
                # Limit RPC requests even after a very fast scan.
                if not self._wallet_running and time.monotonic()-self._wallet_started>=30:
                    self._wallet_running=True
                    self._wallet_started=time.monotonic()
                    threading.Thread(target=self._scan_wallet_background,daemon=True,
                                     name='public-wallet-monitor').start()
                self.status['wallet_scan_running']=self._wallet_running
            stages['wallets']=round(time.monotonic()-stage_started,2)
            stage_started=time.monotonic()
            for mint in wallet_mints:
                discovered.setdefault(mint,set()).add('wallet_public')
            # J7 mentions can discover a CA before DEX indexation. They never
            # increase a token's numerical score; no CA means no market match.
            # Monitor old candidates as well, with a strict budget and a share for new discoveries.
            # `previous` remains bounded for the recheck budget, but its limit
            # must NEVER define the known-token set. A full identity-only query
            # is cheap and avoids recycling archived coins as fresh discoveries.
            previous=self.store.list_coins(1000)
            known=self.store.known_mints()
            self.status['known_total']=len(known)
            recent_posts=self.store.recent_social(200)
            recent_trends=self.store.recent_trends(now=t)
            narrative_events=self.store.recent_narrative_events(150,now=t)
            fresh=[m for m,_ in sorted(discovered.items(),key=discovery_priority,reverse=True) if m not in known]
            # During bursts, first quote more *new* mints cheaply in DexScreener
            # (batched endpoint) and spend scarce RugCheck calls on candidates
            # with current market activity, rather than arbitrary discovery order.
            prefetched = {}
            if len(fresh) > max(40, self.limit * 2):
                try:
                    prefetched = providers.dex_pairs_batch(fresh[:60])
                    fresh.sort(key=lambda mint:early_rank(mint,prefetched,t,recent_posts,recent_trends), reverse=True)
                except Exception as exc:
                    warnings.append('Pré-sélection DEX indisponible: '+type(exc).__name__)
                    prefetched = {}
            urgent=self.store.queue_due(max(1,self.limit//2))
            for q in urgent:
                discovered.setdefault(q['mint'],set()).add(q['source'])
            have_prewatch=any((p.get('prewatch') or p.get('early_watch')) and t-p.get('last_seen',0)<FOLLOW_ACTIVE_S
                              for p in previous)
            plan=select_candidates(discovered,known,previous,urgent,self.limit,t,have_prewatch,fresh_order=fresh)
            chosen=plan['chosen']; fresh=plan['fresh']; fresh_selected=plan['fresh_selected']
            selected_count=len(chosen)
            fresh_selected=sum(m in set(fresh) for m in chosen)
            stages['candidate_selection']=round(time.monotonic()-stage_started,2)
            stage_started=time.monotonic()
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
            try:
                pairs = {mint:prefetched[mint] for mint in chosen if mint in prefetched}
                remaining = [mint for mint in chosen if mint not in pairs]
                pairs.update(providers.dex_pairs_batch(remaining) if remaining else {})
            except Exception as exc:
                warnings.append(f'DexScreener: {type(exc).__name__}: {str(exc)[:150]}')
                self.status.update(scanned=0,cycle=self.status['cycle']+1,errors=warnings[:16]);return False
            stages['dex_quotes']=round(time.monotonic()-stage_started,2)
            stage_started=time.monotonic()
            self.store.heartbeat_v3()
            self.status['pairs_found']=len(pairs)
            self.status['pairs_prefetched']=len(prefetched)
            # Snapshot timestamp is when the batch quotes arrived, not the
            # beginning of potentially long discovery / API-limited scans.
            pair_observed_at=time.time()
            # FAST FIRST PASS: show genuine new-market activity now, BEFORE
            # slow Gecko/RugCheck calls. This is an UNVERIFIED observation,
            # never a buy signal or a proof that the token is sellable.
            for mint in chosen:
                pair=pairs.get(mint) or {}
                prior=self.store.get(mint) or {}
                if not pair or prior.get('status') in ('risque','a_etudier','surveillance'):
                    continue
                origin=set(prior.get('sources') or []) | discovered.get(mint,set())
                provisional_report=score_token(pair,{},None,origin,[],pair_observed_at)
                early=observe_early(pair,{},provisional_report,pair_observed_at)
                if not early:
                    continue
                base=pair.get('baseToken') or {}
                price=number(pair.get('priceUsd'))
                provisional={**provisional_report,'mint':mint,
                    'symbol':str(base.get('symbol') or prior.get('symbol') or '?')[:25],
                    'name':str(base.get('name') or prior.get('name') or '?')[:80],
                    'sources':sorted(origin),'status':'surveillance',
                    'score_method':'curve_experimentale' if assess_curve(pair,{},provisional_report,pair_observed_at) else 'amm',
                    'early_watch':True,'early_watch_evidence':early,'eligible':False,
                    'risks':[], 'wallets':[], 'safety_summary':{},
                    'unknown':provisional_report['unknown']+[
                        'Vérification provisoire : RugCheck et Gecko en attente, sécurité inconnue'],
                    'price_usd':price,'first_price_usd':price,
                    'pair_address':pair.get('pairAddress'),
                    'pair_dex':str(pair.get('dexId') or '')[:50],
                    'market_cap_usd':number(pair.get('marketCap')),
                    'liquidity_usd':number((pair.get('liquidity') or {}).get('usd')),
                    'volume_h1_usd':number((pair.get('volume') or {}).get('h1')),
                    'volume_m5_usd':early['volume_m5'],
                    'pressure_buys_m5':early['buys_m5'],
                    'pressure_sells_m5':early['sells_m5'],
                    'change_m5_pct':early['change_m5'],
                    'patterns':[{'key':'early_observation','label':'Début d’activité · non vérifié',
                        'why':'Données de marché disponibles avant les contrôles externes. Risque de rug non exclu.'}],
                    'market_quote_at':pair_observed_at,
                    'decision_at':time.time(),
                    'quote_lag_s':round(time.time()-pair_observed_at,2),
                    'narrative_matches':contextual_matches(base.get('name') or prior.get('name'),recent_posts,recent_trends,t)}
                self.store.save_coin(provisional,time.time())
                self.store.record_v3(provisional,prior,provisional['decision_at'])
            # At most three concurrent risk requests; the shared provider pacer still applies.
            safety_pool=ThreadPoolExecutor(max_workers=3,thread_name_prefix='risk-check')
            safety_cached={m:self.store.cached_safety(m) for m in chosen if pairs.get(m)}
            safety_jobs={m:safety_pool.submit(providers.rug_report,m) for m,v in safety_cached.items() if v is None}
            self.status['phase']='Vérification des cotations indépendantes'
            gecko,w=providers.quote_same_pools(pairs)
            warnings.extend(w)
            stages['gecko_quotes']=round(time.monotonic()-stage_started,2)
            stage_started=time.monotonic()
            self.status['phase']='Analyse des tokens et des risques'
            new_count=0
            for index,mint in enumerate(chosen):
                pair=pairs.get(mint) or {}
                if not pair:
                    # Launch event proves creation, NOT price, safety or liquidity.
                    # Keep the candidate identifiable while awaiting DEX indexing.
                    prior=self.store.get(mint) or {}
                    launches=[e for e in self.store.launch_recent(150) if e['mint']==mint]
                    if launches and not prior:
                        launch=launches[0]
                        self.store.save_coin({'mint':mint,'name':launch['name'] or '?',
                            'symbol':launch['symbol'] or '?','status':'incomplet',
                            'score':0,'coverage':0,'eligible':False,
                            'sources':[launch['source']],'risk_assessment':'not_yet_available',
                            'price_usd':None,'liquidity_usd':None,'unknown':[
                                'Nouveau lancement : marché non coté, achat/vente non vérifiés',
                                'Risques dev, insiders et sécurité inconnus'],
                            'risks':[], 'positives':[], 'patterns':[],
                            'narrative_signals':watch_evidence(launch['name'],launch['symbol'],narrative_events,t),
                            'first_seen':launch['event_at'],'pair_address':None},time.time())
                    self.status['progress_done']=index+1
                    self.store.queue_done(mint,False)
                    continue
                prior=self.store.get(mint) or {}
                if not prior and pair: new_count+=1
                sources=set(prior.get('sources') or []) | discovered.get(mint,set())
                safety=safety_cached.get(mint)
                if safety is None:
                    try:
                        safety=safety_jobs[mint].result()
                        self.store.save_safety(mint,safety)
                        safety['_checked_at']=time.time()
                    except Exception as exc:
                        warnings.append(f'RugCheck {mint[:6]}…: {type(exc).__name__}')
                        safety={}
                wallets=self.store.wallet_hits(mint)
                history=self.store.history(mint,90)
                live_price=number(pair.get('priceUsd'))
                if live_price is not None and live_price>0:
                    history=history+[{'ts':pair_observed_at,'price':live_price}]
                patterns=detect_patterns(pair,history, wallets, pair_observed_at)
                social=self.store.social_context(mint)
                report=score_token(pair,safety,gecko.get(mint),sources,wallets,pair_observed_at)
                pressure=prebreakout(pair,self.store.market_snapshots(mint,12),report,safety,pair_observed_at)
                curve=assess_curve(pair,safety,report,pair_observed_at)
                if curve is not None:
                    # The AMM liquidity gate is meaningless for a curve.
                    # This parallel score never turns missing reserves into verified liquidity.
                    report['score']=curve['score']
                    report['coverage']=curve['coverage']
                    report['pieces']=curve['pieces']
                    report['unknown']+=curve['unknown']
                    report['age_min']=round(curve['age_min'],1) if curve['age_min'] is not None else None
                    report['status']=('risque' if report['risks'] else 'a_etudier' if curve['early_candidate']
                                      else 'surveillance' if curve['preliminary'] and curve['coverage']>=70
                                      else 'incomplet')
                    report['market_score']=sum(curve['pieces'][k] for k in ('cap marché (courbe)',
                        'volume 5 min (courbe)','transactions 5 min (courbe)',
                        'pression acheteuse (courbe)','prix sans euphorie'))
                if curve and curve['preliminary']:
                    patterns.append({'key':'curve_early' if curve['early_candidate'] else 'curve_watch',
                        'label':'Courbe : pression avant hausse' if curve['early_candidate'] else 'Courbe : activité à confirmer',
                        'why':'Marché sur courbe probable : achat dominant et volume présents avec variation de prix encore limitée. Réserves et acheteurs uniques non vérifiés.'})
                if pressure['prewatch']:
                    patterns.append({'key':'pre_impulse' if pressure['confirmed'] else 'prewatch',
                      'label':'Pression acheteuse avant mouvement' if pressure['confirmed'] else 'Pression acheteuse à confirmer',
                      'why':('Deux fenêtres de 5 min non recouvrantes, même paire : '
                             'prix stable, ≥65 % des transactions 5 min à l’achat, '
                             'volume 5 min ≥1 500 $, liquidité ≥12 000 $. '
                             'Acheteurs uniques et volume organique non vérifiés.'
                             if pressure['confirmed'] else
                             'Premier relevé : prix relativement stable avec activité acheteuse. '
                             'Fenêtre de 5 min provisoire : les transactions ne sont pas des acheteurs uniques.')})
                # A strong early setup can be review-worthy BEFORE price momentum.
                # Keep the original numeric score, risk gates and proof coverage.
                if (curve is None and pressure['prewatch'] and report['status']=='surveillance'
                      and report['score']>=45 and report['coverage']>=70
                      and safety.get('mint_active') is False and safety.get('freeze_active') is False):
                    report['status']='a_etudier' 
                # Observe early market activity without fabricating a safety certificate.
                early=observe_early(pair,safety,report,pair_observed_at)
                if early and report['status']=='incomplet':
                    report['status']='surveillance'
                if early:
                    patterns.append({'key':'early_observation','label':'Début d’activité · non vérifié',
                        'why':'Achats et volume sur 5 min, sans preuve d’acheteurs indépendants ni de revente possible. Sécurité inconnue tant que non vérifiée.'})
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
                    'early_watch':bool(early),
                    'early_watch_evidence':early,
                    'narrative_matches':contextual_matches(base.get('name') or prior.get('name'),recent_posts,recent_trends,t),
                    'narrative_signals':watch_evidence(base.get('name') or prior.get('name'),base.get('symbol') or prior.get('symbol'),narrative_events,t),
                    'prewatch':pressure['prewatch'] or bool(curve and curve['preliminary']),
                    'curve_candidate':bool(curve and curve['early_candidate']),
                    'curve_preliminary':bool(curve and curve['preliminary']),
                    'score_method':'curve_experimentale' if curve else 'amm',
                    'pre_impulse':pressure['confirmed'],
                    'pressure_buys_m5':pressure['snapshot']['buys_m5'],
                    'pressure_sells_m5':pressure['snapshot']['sells_m5'],
                    'volume_m5_usd':pressure['snapshot']['volume_m5'],
                    'pressure_buy_share':pressure.get('buy_share'),
                    'safety_checked_at':safety.get('_checked_at'),
                    'safety_summary':{'mint_active':safety.get('mint_active'),
                        'freeze_active':safety.get('freeze_active'),'top10_pct':safety.get('top10_pct'),
                        'rugcheck_score':safety.get('rugcheck_risk_score'),
                        'rugged':safety.get('rugged'),
                        'top10_method':safety.get('top10_method'),
                        'rugcheck_risks_at_quote':list(safety.get('risk_details') or [])[:12],
                        'lp_locked_pct':(safety.get('lp_locked_by_pool') or {}).get(pair.get('pairAddress')) if pair else None},
                    **report}
                result['market_quote_at']=pair_observed_at
                result['decision_at']=time.time()
                result['quote_lag_s']=round(result['decision_at']-pair_observed_at,2)
                # A quote observed before a slow RugCheck batch can be stale by
                # the time a human receives the alert. Do not backdate the signal.
                if result['quote_lag_s']>60:
                    result['unknown'].append('Cotation potentiellement obsolète à l’alerte (>60 s)')
                    if result['status']=='a_etudier': result['status']='incomplet'
                    if result['early_watch']:
                        result['early_watch']=False
                        result['status']='incomplet'
                        result['unknown'].append('Veille précoce expirée : nouvelle cotation nécessaire')
                result['social_context']=social
                if result['pre_impulse']:
                    result['pre_impulse_first_at']=(prior.get('pre_impulse_first_at') or pair_observed_at)
                    result['pre_impulse_first_price']=(prior.get('pre_impulse_first_price') or live_price)
                else:
                    result['pre_impulse_first_at']=prior.get('pre_impulse_first_at')
                    result['pre_impulse_first_price']=prior.get('pre_impulse_first_price')
                age=result.get('age_min')
                result['regime']='courbe probable' if curve else ('lancement' if age is not None and age<=180 else 'token établi')
                official=social.get('verified_influential_authors_10m',0)
                upstream=social.get('j7_unconfirmed_authors_10m',0)
                influencers=official+upstream
                if influencers>=2 and social['acceleration']>0:
                    result['patterns'].append({'key':'social_attention','label':'Mentions J7 multi-comptes',
                        'why':f"Contrat Solana exact, {influencers} auteurs distincts (≥50 k abonnés), badge signalé par J7 ou confirmé X ; part des abonnés humains inconnue."})
                # X official verification gets higher weight than J7's upstream flags.
                # It changes analysis PRIORITY only, never the safety/status or market score.
                result['attention_score']=min(30,6*official+3*upstream+(6 if influencers>=2 else 0))
                result['priority_score']=round(min(100,report['market_score']/(82 if curve else 50)*70+result['attention_score']),1)
                result['analysis_version']='v2.0'
                # Require core evidence; a 100% coverage number alone does not prove safety.
                result['eligible']=(curve is None and not result['risks'] and result['coverage']>=90
                    and liquidity is not None and liquidity>=5000
                    and safety.get('mint_active') is False and safety.get('freeze_active') is False
                    and safety.get('rugcheck_risk_score') is not None)
                result['onchain_risk']=self.store.observed_risks([mint]).get(mint)
                enforce_gate(result, result['decision_at'])
                self.store.save_strategy_sample(result, pair_observed_at)
                result['pair_changed'] = bool(prior.get('pair_address') and prior.get('pair_address')!=result['pair_address'])
                self.store.save_market_snapshot(mint,pressure['snapshot'])
                self.store.save_coin(result,time.time())
                # Start measurement from the first alert itself, never backdate it to
                # token discovery. Reference and quote timestamps are persisted.
                self.store.record_research_event(result,prior,result['decision_at'])
                self.store.observation_v2(mint,result['pair_address'],live_price,liquidity,pair_observed_at)
                self.store.record_v3(result,prior,result['decision_at'])
                self.store.observation_v3(mint,result['pair_address'],live_price,pair_observed_at)
                self.store.queue_done(mint,True)
                self.status['progress_done']=index+1
            stages['token_analysis']=round(time.monotonic()-stage_started,2)
            self.status.update(scanned=len(chosen),cycle=self.status['cycle']+1,errors=warnings[:16],new_tokens=new_count)
            success=True
            return True
        except Exception as exc:
            self.status['errors']=(warnings+[f'Erreur cycle: {type(exc).__name__}: {str(exc)[:150]}'])[:16]
            return False
        finally:
            if safety_pool is not None:safety_pool.shutdown(wait=True,cancel_futures=True)
            finished=time.time()
            self.store.heartbeat_v3(finished)
            pause=gecko_pause_seconds()
            self.status['gecko_resume_at']=finished+pause if pause else None
            if pause:
                self.status['errors']=[e for e in self.status.get('errors',[]) if not ('gecko' in e.lower() and '429' in e)]
            self.status.update(running=False,last_scan=finished,finished_at=finished,
                               duration_seconds=round(finished-started,2),last_outcome='ok' if success else 'error',
                               phase='Scan terminé' if success else 'Scan interrompu',
                               scan_stages_s=stages, fresh_scanned=fresh_selected)
            try:
                self.store.save_cycle_metrics(dict(
                    finished_at=finished,success=success,duration_s=round(finished-started,2),
                    discovered=self.status.get('discovered',0),
                    new_candidates=self.status.get('new_candidates',0),
                    selected=selected_count,pairs_found=self.status.get('pairs_found',0),
                    fresh_scanned=fresh_selected,stages=stages,warnings=warnings[:12]))
            except Exception as exc:
                self.status['errors']=(self.status.get('errors',[])+
                    [f'Journal cycle: {type(exc).__name__}'])[-16:]
            self.lock.release()

    def run_loop(self):
        while not self.stop_event.is_set():
            self.store.heartbeat_v3()
            self.run_once()
            self.evaluate_due()
            self.store.heartbeat_v3()
            if time.time()-self._last_prune>3600:
                self.store.prune_old()
                self.store.live_prune()
                self._last_prune=time.time()
            if self.stop_event.is_set(): break
            due=time.time()+self.interval
            self.status['next_scan']=due
            # A manual refresh wakes this wait but cannot overlap a running scan.
            self.refresh_event.wait(self.interval)
            self.refresh_event.clear()
            self.status['next_scan']=None

    def evaluate_due(self):
        """Independent follow-up budget, including risky and hidden candidates."""
        due=list(dict.fromkeys(self.store.due_v3(limit=12)+self.store.evaluation_due_v2(limit=12)))[:20]
        if not due:return
        try:
            pairs=providers.dex_pairs_batch(due)
            for mint in due:
                pair=pairs.get(mint) or {}
                self.store.observation_v2(mint,pair.get('pairAddress'),number(pair.get('priceUsd')),number((pair.get('liquidity') or {}).get('usd')))
                self.store.observation_v3(mint,pair.get('pairAddress'),number(pair.get('priceUsd')))
            # No per-cycle report computation; reports are generated on demand.
        except Exception as exc:
            self.status['errors']=(self.status['errors']+[f'Suivi des résultats: {type(exc).__name__}'])[-16:]

    def view(self):
        coins=self.store.list_coins()
        now=time.time()
        origins=self.store.first_highlights([c['mint'] for c in coins])
        observed_risks=self.store.observed_risks([c['mint'] for c in coins])
        for c in coins:
            c['j7']=origins.get(c['mint'])
            c['onchain_risk']=observed_risks.get(c['mint'])
            original_status=c.get('status')
            enforce_gate(c,now)
            elapsed=max(0,now-(c.get('market_quote_at') or c.get('last_seen',0)))
            c['data_age_seconds']=int(elapsed)
            c['fresh']=elapsed<=LIVE_MAX_AGE_S
            # Important: override UNIQUEMENT sur les données renvoyées à l'interface,
            # jamais dans la base d'historique. Un vieux « À étudier » n'est pas live.
            if not c['fresh']:
                c['previous_status']=original_status
                c['status']='expire'
            if (c.get('first_price_usd') or 0)>0 and (c.get('price_usd') or 0)>0:
                c['observed_change_pct']=round((c['price_usd']/c['first_price_usd']-1)*100,2)
            else: c['observed_change_pct']=None
        coins.sort(key=lambda c:(c['fresh'],
            {'a_etudier':3,'surveillance':2,'incomplet':1,'risque':0}.get(c.get('status'),0),
            bool(c.get('narrative_signals')),
            bool(c.get('early_watch')),
            len(c.get('patterns') or []), c.get('score') or 0),reverse=True)
        live=[c for c in coins if c['fresh']]
        return {'live_launches':self.store.live_recent(20),'live_health':self.store.live_health(),
                'fast_lane':self.fast_lane.snapshot(),
                'narratives':self.store.narrative_summary(16),
                'launches':self.store.launch_recent(16),
                'coins':coins, 'stats':{'total':len(coins),'stored':self.store.count_coins(),
                'live':len(live),'expired':len(coins)-len(live),
                'interesting':sum(c['status']=='a_etudier' for c in live),
                'incomplete':sum(c['status']=='incomplet' for c in live),
                'early_watch':sum(bool(c.get('early_watch')) for c in live),
                'risky':sum(c['status']=='risque' for c in live)},
                'status':dict(self.status)}
