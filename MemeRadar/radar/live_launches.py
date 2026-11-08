"""Optional FREE-only PumpPortal feed. No paid trade subscriptions, no order API.

Attempts the free creation/migration feed; optional user-provided API key.
Never subscribes to metered token/account trade streams.
"""
from __future__ import annotations
import json, os, threading, time
from .social import is_solana_address
from .realtime import normalize_launch, LaunchQuoteWorker


class LaunchFeed:
    def __init__(self,store,stop_event,wakeup=None,key=None):
        self.store=store
        self.stop_event=stop_event
        self.wakeup=wakeup
        self.key=(key if key is not None else os.getenv('PUMPPORTAL_API_KEY','')).strip()
        self.lock=threading.RLock()
        self._narratives_cache=[]
        self._narratives_at=0
        self.status={'enabled':True,'connected':False,'creations':0,'migrations':0,
                     'last_event':None,'state':'starting','error':None}

    def snapshot(self):
        with self.lock:return dict(self.status)

    def ingest(self,obj):
        """Receive native token metadata instantly; no DEX request in this path."""
        data=normalize_launch(obj)
        if not data:return False
        mint=data['mint']
        kind='migration' if ('migrat' in str(obj.get('txType') or obj.get('type') or obj.get('event') or '').lower()) else 'creation'
        now=time.time()
        if kind=='creation':
            # Cached social terms avoid locking SQLite for every raw launch.
            if now-self._narratives_at>=5:
                self._narratives_cache=self.store.recent_narrative_events(300,now)
                self._narratives_at=now
            from .narrative_intelligence import watch_evidence
            evidence=watch_evidence(data['name'],data['symbol'],self._narratives_cache,now)
            observation=self.store.live_launch(data,evidence,at=now)
            if not observation['new']:
                return False
            if observation['matched'] and observation['new']:
                # Launch entry appears with the real name BEFORE DEX indexing.
                self.store.save_coin_if_absent({
                    'mint':mint,'name':data['name'],'symbol':data['symbol'],
                    'status':'incomplet','score':None,'coverage':0,'eligible':False,
                    'risk_assessment':'not_yet_available','score_method':'launch_unverified',
                    'price_usd':None,'market_cap_usd':None,'liquidity_usd':None,
                    'market_cap_sol_initial':data['market_cap_sol'],
                    'virtual_sol':data['virtual_sol'],'virtual_token':data['virtual_token'],
                    'creator_initial_buy_sol':data['initial_buy_sol'],
                    'creator_wallet_unverified':data['creator'],
                    'narrative_signals':evidence,'sources':['pumpportal_creation','j7_narrative'],
                    'unknown':['Prix USD et vente non vérifiés','Concentration, dev, snipers et insiders inconnus'],
                    'risks':[],'positives':[],'patterns':[],
                    'decision_at':now,'market_quote_at':None},now)
                self.store.launch_event(mint,'creation',data['name'],data['symbol'],'pumpportal',now)
                self.store.enqueue(mint,'launch_narrative')
                if self.wakeup:self.wakeup(mint)
        else:
            # A migration without initial creation metadata is still discoverable.
            self.store.launch_event(mint,'migration',data['name'],data['symbol'],'pumpportal',now)
            self.store.enqueue(mint,'launch_migration')
            if self.wakeup:self.wakeup(mint)
        with self.lock:
            self.status['creations' if kind=='creation' else 'migrations']+=1
            self.status['last_event']=now
        return True

    def run(self):
        try:
            import websocket
        except ImportError:
            with self.lock:self.status.update(state='missing_websocket_client',error='Installer websocket-client')
            return
        # One socket, two confirmed free subscriptions. NEVER subscribe to
        # account/token trades (metered). Do not log websocket URLs / API keys.
        while not self.stop_event.is_set():
            ws=None
            try:
                # Free launch subscriptions; optional API key from env. Never
                # subscribe to metered trades or accounts, even if key exists.
                from urllib.parse import quote
                url='wss://pumpportal.fun/api/data'
                if self.key:url+='?api-key='+quote(self.key,safe='')
                ws=websocket.create_connection(url,timeout=12)
                ws.settimeout(8)
                ws.send(json.dumps({'method':'subscribeNewToken'}))
                ws.send(json.dumps({'method':'subscribeMigration'}))
                with self.lock:self.status.update(state='connected',connected=True,error=None)
                while not self.stop_event.is_set():
                    try:raw=ws.recv()
                    except websocket.WebSocketTimeoutException:continue
                    if not raw:break
                    if len(raw)>100_000:continue
                    obj=json.loads(raw)
                    if isinstance(obj,dict) and obj.get('message') and not obj.get('mint'):
                        continue
                    self.ingest(obj)
            except Exception as exc:
                with self.lock:self.status.update(state='error',connected=False,error=type(exc).__name__)
            finally:
                if ws:
                    try:ws.close()
                    except Exception:pass
                with self.lock:self.status['connected']=False
            self.stop_event.wait(15)
