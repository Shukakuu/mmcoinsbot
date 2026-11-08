#!/usr/bin/env python3
"""MemeRadar: LOCAL-ONLY read-only Solana discovery dashboard.

Usage: py main.py [--port 8765] [--interval 20] [--demo] [--once]
Never accepts private keys or places trades.
"""
from __future__ import annotations
import argparse, csv, io, json, os, sys, threading, time, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from radar.engine import Radar
from radar.store import Store
from radar.social import J7Feed
from radar.narratives import TrendsMonitor
from radar.live_launches import LaunchFeed
from radar.realtime import compare_cohorts
from radar.x_verification import XVerifier
from radar.j7_hub import HighlightTracker
from radar.world_watch import WorldMonitor, build_report, social_events
from radar.strategies import enforce_gate

ROOT=Path(__file__).resolve().parent
WEB=ROOT/'web'
RESTART_EXIT_CODE=75  # Le lanceur attend la sortie complète puis relance Python/J7


def demo_payload():
    now=time.time()
    coins=[]
    specimens=[('NOVA','Nova Pup',78,'a_etudier',82,41200,79000,6,17.5,1.2),
               ('ORBIT','Orbit Cat',71,'a_etudier',90,93500,182000,47,5.1,3.7),
               ('PIXEL','Pixel Frog',62,'surveillance',70,20900,18000,12,-2.7,8.4),
               ('MIMI','Mimi',46,'incomplet',40,9400,12300,3,27.1,9.2),
               ('FOMO','Fomo King',83,'risque',90,3200,220000,8,110,-50.0),
               ('HUSH','Hush Duck',38,'incomplet',35,None,None,None,None,None)]
    for i,(symbol,name,score,status,cover,liq,vol,age,m5,h1) in enumerate(specimens):
        mint=('A'*(32+i))+'BCDE' # fictitious base58 strings, no real address
        prices=[0.000014*(1+i*0.2)*(1+0.012*x+0.08*__import__('math').sin(x*0.8+i)) for x in range(15)]
        risks=['Liquidité < 5 000 $','Pump > 70 % en 5 minutes'] if status=='risque' else []
        unknown=['Score RugCheck indisponible','Prix du même pool non confirmé'] if status=='incomplet' else []
        coins.append({'mint':mint,'symbol':symbol,'name':name,'score':score,'status':status,'coverage':cover,
          'liquidity_usd':liq,'volume_h1_usd':vol,'age_min':age,'change_m5_pct':m5,'change_h1_pct':h1,
          'buys_h1':105-i*10,'sells_h1':45+i*7,'price_usd':prices[-1],'first_price_usd':prices[0],
          'market_cap_usd':(liq*2.5 if liq else None),'fdv_usd':(liq*2.8 if liq else None),
          'pair_address':None,'gecko_gap_pct':1.4 if cover>=80 else None,
          'first_seen':now-2000,'last_seen':now-60,'sources':['gecko_new_pools','dex_profiles'] if i%2 else ['gecko_trending_pools'],
          'wallets':[],'wallet_hit_count':0,'patterns':([{'key':'early','label':'Départ précoce','why':'Exemple fictif de momentum initial.'}] if i==0 else [{'key':'momentum','label':'Impulsion acheteuse','why':'Exemple fictif de pression acheteuse.'}] if i==1 else []),'positives':['Momentum modéré','Volume en progression'] if score>60 else [],
          'risks':risks,'unknown':unknown,'safety_summary':{'mint_active':False if cover>70 else None,
          'freeze_active':False if cover>70 else None,'top10_pct':19.4 if cover>70 else None,
          'rugcheck_score':12 if cover>70 else None,'lp_locked_pct':None},
          'history':[{'ts':now-900+60*x,'price':p} for x,p in enumerate(prices)],
          'observed_change_pct':round((prices[-1]/prices[0]-1)*100,2),
          'pieces':{'liquidité':12,'volume/liquidité':9,'pression acheteuse':8,'sécurité autorités':10}})
    for coin in coins:
        enforce_gate(coin,now)
    return {'coins':coins,'stats':{'total':len(coins),'interesting':0,'incomplete':4,'risky':1},
      'status':{'mode':'demo','running':False,'last_scan':now,'cycle':1,'scanned':6,'discovered':6,
      'interval_seconds':20,'next_scan':None,'started_at':None,'finished_at':now,'duration_seconds':0,
      'phase':'Simulation figée','progress_done':0,'progress_total':0,'last_outcome':'ok','new_tokens':0,
      'engine_version':'v2.0','errors':['Exemple fictif : aucune connexion aux marchés ; aucun de ces tokens n’est une recommandation.']}}


def make_handler(radar, demo=False, j7=None, verifier=None, restart_callback=None, launches=None, tracker=None, world=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt,*args):
            if not self.path.startswith('/api/data'): super().log_message(fmt,*args)

        def respond(self,body,content_type='application/json; charset=utf-8',code=200):
            if isinstance(body,str): raw=body.encode('utf-8')
            else: raw=json.dumps(body,ensure_ascii=False,allow_nan=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(raw)

        def do_GET(self):
            path=urlparse(self.path).path
            if path=='/api/data': return self.respond(demo_payload() if demo else radar.view())
            if path=='/api/v2':
                now=time.time()
                coins=demo_payload()['coins'] if demo else radar.view()['coins']
                events=[] if demo else radar.store.world_events(now)+social_events(radar.store.recent_social(500),now)
                if not demo:
                    histories=radar.store.strategy_histories([c['mint'] for c in coins],now)
                    for coin in coins:coin['strategy_history']=histories.get(coin['mint'],[])
                data=build_report(coins,events,now)
                data['demo']=demo
                data['news_status']=world.status if world else {'state':'demo' if demo else 'not_started'}
                return self.respond(data)
            if path=='/api/research':
                return self.respond({'version':3,'total_events':0,'groups':[],'note':'Démo : aucune mesure réelle'} if demo else radar.store.report_v3())
            if path=='/api/j7':
                if demo:return self.respond({'demo':True,'recent':[],'authors':[],'vias':[],'totals':{},'schemas':[],'status':{'state':'demo'},
                                              'note':'Démo : aucune donnée J7 réelle.'})
                data=radar.store.j7_report()
                data['status']=j7.report()
                data['tracker']=dict(tracker.status) if tracker else {}
                data['fast_lane']=radar.fast_lane.snapshot()
                return self.respond(data)
            if path=='/api/social-status':
                status={'state':'demo','connected':False} if demo else j7.report()
                if not demo:status['x_verification']=dict(verifier.status) if verifier else {'enabled':False}
                return self.respond(status)
            if path=='/api/intelligence':
                from radar.intelligence import report
                return self.respond({'authors':[],'clones':[],'wallets':{}} if demo else report(radar.store,radar.wallet_monitor.wallets_path))
            if path=='/api/evaluation':
                try:horizon=int(parse_qs(urlparse(self.path).query).get('horizon',['300'])[0])
                except ValueError:return self.respond({'error':'Horizon invalide'},code=400)
                if horizon not in (300,600,1200,3600,10800,21600):return self.respond({'error':'Horizon invalide'},code=400)
                return self.respond({'demo':True,'note':'Mode démo'} if demo else compare_cohorts(radar.store,horizon))
            if path=='/api/live':
                return self.respond({'demo':True,'launches':[],'health':{}} if demo else
                    {'launches':radar.store.live_recent(35),'health':radar.store.live_health(),
                     'provider':launches.snapshot(),'quote_worker':dict(radar.launch_quotes.status),
                     'risk_observer':dict(radar.risk_observer.status)})
            if path=='/api/launch-status':
                return self.respond({'state':'demo','enabled':False} if demo else launches.snapshot())
            if path=='/api/social':
                return self.respond({'narratives':[] if demo else radar.store.narrative_summary(20),
                                     'status':{'state':'demo','connected':False,'enabled':False,'last_event':None,'received':0,'new_mints':0,'error':None} if demo else j7.report(),
                                     'diagnostics':{'stored_posts':0,'linked_posts':0,'mint_mentions':0,'last_500_with_tickers':0,'sample_size':0} if demo else radar.store.social_diagnostics(),
                                     'posts':[] if demo else radar.store.recent_social(100),
                                     'x_verification':{'enabled':False} if (demo or verifier is None) else dict(verifier.status)})
            if path=='/api/export':
                coins=(demo_payload() if demo else radar.view())['coins']
                s=io.StringIO();writer=csv.writer(s)
                writer.writerow(['mint','symbol','score_non_calibre','statut','couverture_pct','prix_usd',
                   'liquidite_usd','volume_h1_usd','variation_5m_pct','age_paire_min','sources','signaux_observes','risques','inconnus'])
                for r in coins:
                    writer.writerow([r.get('mint'),r.get('symbol'),r.get('score'),r.get('status'),r.get('coverage'),
                         r.get('price_usd'),r.get('liquidity_usd'),r.get('volume_h1_usd'),r.get('change_m5_pct'),
                         r.get('age_min'),';'.join(r.get('sources',[])),';'.join(p.get('label','') for p in r.get('patterns',[])),';'.join(r.get('risks',[])),';'.join(r.get('unknown',[]))])
                return self.respond(s.getvalue(),'text/csv; charset=utf-8')
            if path in ('/','/index.html','/v8.css','/v8.js','/v2.js'):
                file=WEB/('index.html' if path=='/' else path.lstrip('/'))
                ctype='text/html; charset=utf-8' if file.suffix=='.html' else ('text/css; charset=utf-8' if file.suffix=='.css' else 'application/javascript; charset=utf-8')
                return self.respond(file.read_text(encoding='utf-8'),ctype)
            self.respond({'error':'not found'},code=404)

        def do_POST(self):
            # Restrict DNS rebinding on local mutating endpoints.
            host=self.headers.get('Host','').split(':',1)[0].lower()
            if host not in ('127.0.0.1','localhost'):
                return self.respond({'error':'Host local requis'},code=403)
            path=urlparse(self.path).path
            if path not in ('/api/refresh','/api/restart'):
                return self.respond({'error':'not found'},code=404)
            # Protection CSRF : header non simple, navigateur d'origine différente
            # soumis au preflight CORS (non autorisé ici) ; serveur lié à 127.0.0.1.
            if path=='/api/restart' and self.headers.get('X-MemeRadar-Local-Action')!='restart':
                return self.respond({'error':'Action locale non autorisée'},code=403)
            origin=self.headers.get('Origin')
            host=self.headers.get('Host','')
            if origin and origin.rstrip('/')!='http://'+host:
                return self.respond({'error':'Origine non autorisée'},code=403)
            if demo:return self.respond({'error':'Mode démo : aucun service à relancer'},code=400)
            if path=='/api/restart':
                if restart_callback is None or not restart_callback():
                    return self.respond({'error':'Redémarrage déjà demandé'},code=409)
                return self.respond({'ok':True,'restarting':True,
                    'message':'Arrêt complet en cours. Le lanceur Windows va relancer tous les services.'},code=202)
            if not radar.request_scan():
                return self.respond({'ok':False,'running':radar.status['running'],
                                     'error':'Scan déjà en cours ou déjà demandé'},code=409)
            self.respond({'ok':True,'queued':True},code=202)
    return Handler


def main():
    parser=argparse.ArgumentParser(description='MemeRadar (lecture seule, interface localhost)')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--interval',type=int,default=20,help='Secondes après chaque cycle (minimum 20)')
    parser.add_argument('--limit',type=int,default=14,help='Tokens analysés par cycle (1-25)')
    parser.add_argument('--db',default=str(ROOT/'radar.db'))
    parser.add_argument('--wallets',default=str(ROOT/'wallets.txt'))
    parser.add_argument('--rpc',default='https://api.mainnet-beta.solana.com',help='RPC Solana public ou personnel')
    parser.add_argument('--demo',action='store_true',help='Affiche des tokens FICTIFS sans requête externe')
    parser.add_argument('--once',action='store_true',help='Exécute un cycle et s’arrête sans interface')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--no-launch-feed',action='store_true',help='Désactiver le flux gratuit de créations')
    args=parser.parse_args()
    if args.once and args.demo:
        parser.error('--once et --demo ne peuvent pas être combinés')
    radar=None if args.demo else Radar(args.db,args.wallets,args.interval,args.limit,args.rpc)
    verifier=None if args.demo or args.once else XVerifier(radar.store,radar.social_wakeup)
    trends=None if args.demo or args.once else TrendsMonitor(radar.store,radar.stop_event)
    world=None if args.demo or args.once else WorldMonitor(radar.store,radar.stop_event)
    j7=None if args.demo or args.once else J7Feed(radar.store,radar.social_wakeup,verifier=verifier)
    launches=None if args.demo or args.once else LaunchFeed(radar.store,radar.stop_event,radar.social_wakeup)
    if launches and args.no_launch_feed:
        launches.status.update(enabled=False,state='disabled_by_user')
    tracker=None if args.demo or args.once else HighlightTracker(radar.store,radar.stop_event)
    if args.once:
        print('Lancement d’un cycle de détection en lecture seule...')
        done=radar.run_once();print(json.dumps({'success':done,'status':radar.status,'stats':radar.view()['stats']},ensure_ascii=False,indent=2));return
    url=f'http://127.0.0.1:{args.port}'
    restart_state={'requested':False}
    restart_lock=threading.Lock()
    server=None
    def request_restart():
        with restart_lock:
            if restart_state['requested']: return False
            restart_state['requested']=True
        # shutdown() doit être appelé hors du thread HTTP, après avoir émis le 202.
        def delayed_shutdown():
            time.sleep(.3)
            if server is not None: server.shutdown()
        threading.Thread(target=delayed_shutdown,name='restart-shutdown',daemon=True).start()
        return True
    try:
        server=ThreadingHTTPServer(('127.0.0.1',args.port),
            make_handler(radar,args.demo,j7,verifier,request_restart,launches,tracker,world))
    except OSError:
        print(f"Port {args.port} indisponible : fermez l'autre instance de MemeRadar puis relancez.")
        return
    if not args.demo:
        threading.Thread(target=radar.run_loop,name='radar-scanner',daemon=True).start()
        threading.Thread(target=radar.fast_lane.run,name='fast-event-lane',daemon=True).start()
        threading.Thread(target=radar.launch_quotes.run,name='launch-quote-followup',daemon=True).start()
        threading.Thread(target=radar.fast_lane.run_quotes,name='j7-quote-followup',daemon=True).start()
        threading.Thread(target=radar.risk_observer.run,name='onchain-risk-observer',daemon=True).start()
        threading.Thread(target=j7.run,name='j7-social-listener',daemon=True).start()
        threading.Thread(target=tracker.run,name='j7-highlight-tracker',daemon=True).start()
        threading.Thread(target=trends.run,name='public-trends-listener',daemon=True).start()
        threading.Thread(target=world.run,name='world-news-listener',daemon=True).start()
        if not args.no_launch_feed:
            threading.Thread(target=launches.run,name='free-launch-feed',daemon=True).start()
        if verifier.token:
            threading.Thread(target=verifier.run,name='x-account-verification',daemon=True).start()
    print('MemeRadar', 'DÉMO FICTIVE' if args.demo else 'LIVE SCAN', '|', url)
    print('Lecture seule. Aucune clé privée, transaction, position ou ordre. Ctrl+C pour stopper.')
    print('J7 social:', 'session configurée (connexion en cours)' if j7 and j7.token else 'désactivé — configurer J7_FEED_TOKEN')
    if not args.no_browser: threading.Timer(0.8,lambda:webbrowser.open(url)).start()
    try: server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt: print('\nArrêt de MemeRadar.')
    finally:
        if radar is not None:
            if j7 is not None:j7.stop()
            if verifier is not None:verifier.stop()
            radar.stop_event.set()
            radar.refresh_event.set()
        server.server_close()
    if restart_state['requested']:
        print('Redémarrage demandé : tous les services se sont arrêtés. Relance par START_J7.ps1 ou START_MEMERADAR.bat.')
        raise SystemExit(RESTART_EXIT_CODE)

if __name__=='__main__':main()
