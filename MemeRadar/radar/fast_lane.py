"""Independent fast *observation* lane for explicitly discovered mints.

Never marks a token 'à étudier', computes sellability, or touches orders.
Scanner remains the authority for final full-market and safety assessments.
"""
from __future__ import annotations
import queue,threading,time
from .social import is_solana_address
from .source_scanner import number
from .narrative_intelligence import watch_evidence

class FastLane:
    def __init__(self,store,stop_event):
        self.store=store
        self.stop_event=stop_event
        self.events=queue.Queue(maxsize=1000)
        self.quote_events=queue.Queue(maxsize=800)
        self.lock=threading.Lock()
        self.last_seen={}
        self.quote_retry={}  # mint -> (due monotonic time, attempts); one worker owns it
        self.status={'received':0,'quoted':0,'unquoted':0,'dropped':0,
                     'last_result':None,'error':None,'running':False}

    def submit(self,mint):
        if not is_solana_address(mint):return False
        now=time.monotonic()
        with self.lock:
            self.last_seen={m:ts for m,ts in self.last_seen.items() if now-ts<120}
            if mint in self.last_seen:return False
            self.last_seen[mint]=now
            try:self.events.put_nowait(mint)
            except queue.Full:
                self.status['dropped']+=1
                self.last_seen.pop(mint,None)
                return False
            self.status['received']+=1
        return True

    def snapshot(self):
        with self.lock:return dict(self.status,queued=self.events.qsize())

    def observe(self,mints,get_pairs=None):
        from .providers import dex_pairs_batch
        get_pairs=get_pairs or dex_pairs_batch
        if not mints:return 0
        pairs=get_pairs(mints)
        now=time.time()
        narratives=self.store.recent_narrative_events(150,now)
        origins=self.store.first_highlights(mints)
        launches={e['mint']:e for e in self.store.launch_recent(150)}
        observed=0
        for mint in mints:
            # Don't overwrite already-verified analyses, including known risks!
            if self.store.get(mint) is not None:continue
            pair=pairs.get(mint) or {}
            launch=launches.get(mint) or {}
            origin=origins.get(mint) or {}
            # A valid Solana CA received from J7 is still a candidate before
            # public price feeds index it. All market/risk fields stay unknown.
            base=pair.get('baseToken') or {}
            name=str(base.get('name') or launch.get('name') or origin.get('name') or '?')[:80]
            symbol=str(base.get('symbol') or launch.get('symbol') or origin.get('symbol') or '?')[:25]
            buys=(pair.get('txns') or {}).get('m5') or {}
            provisional={'mint':mint,'name':name,'symbol':symbol,
                'status':'incomplet','score':0,'coverage':0,'eligible':False,
                'risk_assessment':'not_yet_available',
                'sources':['fast_event_observation']+[launch['source']] if launch else ['fast_event_observation','j7_direct_contract'],
                'price_usd':number(pair.get('priceUsd')),
                'liquidity_usd':number((pair.get('liquidity') or {}).get('usd')),
                'volume_m5_usd':number((pair.get('volume') or {}).get('m5')),
                'market_cap_usd':number(pair.get('marketCap')),
                'pressure_buys_m5':number(buys.get('buys')),
                'pressure_sells_m5':number(buys.get('sells')),
                'change_m5_pct':number((pair.get('priceChange') or {}).get('m5')),
                'first_seen':launch.get('event_at') or now,
                'pair_address':pair.get('pairAddress'),
                'pair_dex':str(pair.get('dexId') or '')[:40],
                'narrative_signals':watch_evidence(name,symbol,narratives,now),
                'j7_origin':origin or None,
                'unknown':['Veille rapide : contrôles RugCheck non effectués',
                           'Risques dev, insiders et possibilité de revente non vérifiés'],
                'positives':[],'risks':[],'patterns':[],
                'market_quote_at':now if pair else None,
                'decision_at':now,'score_method':'provisional_event'}
            # Recheck inside store transaction to avoid clobbering scanner.
            if self.store.save_coin_if_absent(provisional,now):observed+=1
        with self.lock:
            self.status['quoted']+=observed
            self.status['unquoted']+=len(mints)-observed
            self.status['last_result']=now
        return observed

    def observe_immediate(self,mints):
        """No HTTP calls: J7 contract appears in the UI even with no DEX price."""
        now=time.time()
        origins=self.store.first_highlights(mints)
        launches={x['mint']:x for x in self.store.launch_recent(200)}
        created=0
        for mint in mints:
            origin=origins.get(mint) or {}
            launch=launches.get(mint) or {}
            item={'mint':mint,'name':launch.get('name') or origin.get('name') or '?',
                  'symbol':launch.get('symbol') or origin.get('symbol') or '?',
                  'status':'incomplet','score':None,'coverage':0,'eligible':False,
                  'risk_assessment':'not_yet_available','score_method':'provisional_event',
                  'price_usd':None,'liquidity_usd':None,'market_cap_usd':None,
                  'sources':['j7_or_launch_event'], 'j7_origin':origin or None,
                  'risks':[],'positives':[],'patterns':[],
                  'unknown':['Prix DEX et disponibilité de la vente encore inconnus',
                             'Risque du développeur et des premiers snipers non vérifiés']}
            if self.store.save_coin_if_absent(item,now):created+=1
            try:self.quote_events.put_nowait(mint)
            except queue.Full:
                with self.lock:self.status['dropped']+=1
        with self.lock:
            self.status['received']+=0
            self.status['unquoted']+=created
            self.status['last_result']=now
        return created

    def quote_once(self,get_pairs=None,now=None):
        from .providers import dex_pairs_batch
        now=time.monotonic() if now is None else now
        # Drain a bounded queue. Pending retries are bounded as well.
        for _ in range(800):
            try:mint=self.quote_events.get_nowait()
            except queue.Empty:break
            if mint not in self.quote_retry:
                if len(self.quote_retry)>=800:
                    with self.lock:self.status['dropped']+=1
                else:self.quote_retry[mint]=(now,0)
        batch=[m for m,(due,n) in sorted(self.quote_retry.items(),key=lambda x:x[1][0]) if due<=now][:30]
        if not batch:return 0
        try:
            pairs=(get_pairs or dex_pairs_batch)(batch)
            with self.lock:self.status['error']=None
        except Exception as exc:
            pairs={}
            with self.lock:self.status['error']=type(exc).__name__
        for mint in batch:
            attempts=self.quote_retry[mint][1]+1
            pair=pairs.get(mint)
            if pair:
                changed=self.store.update_provisional_quote(mint,pair)
                with self.lock:self.status['quoted']+=int(changed)
                self.quote_retry.pop(mint,None)
            elif attempts>=12:
                self.quote_retry.pop(mint,None)
            else:
                self.quote_retry[mint]=(now+min(60,5*2**min(attempts-1,4)),attempts)
        with self.lock:self.status['quote_pending']=len(self.quote_retry)
        return len(batch)

    def run_quotes(self):
        while not self.stop_event.is_set():
            try:self.quote_once()
            except Exception as exc:
                with self.lock:self.status['error']=type(exc).__name__
            self.stop_event.wait(2)

    def run(self):
        with self.lock:self.status['running']=True
        try:
            while not self.stop_event.is_set():
                try:first=self.events.get(timeout=1)
                except queue.Empty:continue
                batch=[first]
                while len(batch)<60:
                    try:batch.append(self.events.get_nowait())
                    except queue.Empty:break
                try:self.observe_immediate(list(dict.fromkeys(batch)))
                except Exception as exc:
                    with self.lock:self.status['error']=type(exc).__name__
                # No 3-second wait and no network dependency in the fast lane.
        finally:
            with self.lock:self.status['running']=False
