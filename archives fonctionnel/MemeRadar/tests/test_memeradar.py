"""Self-contained tests. No live APIs or trading actions."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radar.scoring import score_token
from radar.patterns import detect_patterns
from radar.store import Store
from radar.providers import PublicWalletMonitor, dex_pairs_batch
from radar.source_scanner import dex_discovery, gecko_discovery, rugcheck, WSOL, NON_MEMES
from radar.engine import Radar
from main import demo_payload, make_handler
from http.server import ThreadingHTTPServer
import threading
from urllib.request import urlopen, Request
from urllib.error import HTTPError

MINT='B'*32
PAIR='D'*32
WALLET1='E'*32
WALLET2='F'*32
NOW=1_800_000_000

def pair(price=0.001, age=8, liquidity=24000, buys=90, sells=30, change=7):
    return {'chainId':'solana','pairAddress':PAIR,'baseToken':{'address':MINT,'symbol':'TEST','name':'Test coin'},
            'quoteToken':{'address':WSOL},'priceUsd':str(price),
            'liquidity':{'usd':liquidity},'volume':{'h1':31000},
            'txns':{'h1':{'buys':buys,'sells':sells}},'priceChange':{'m5':change,'h1':20},
            'pairCreatedAt':int((NOW-age*60)*1000),'marketCap':45000,'fdv':48000}

def safe():
    return {'mint_active':False,'freeze_active':False,'rugged':False,'top10_pct':20,
            'rugcheck_risk_score':12,'risk_levels':[]}

class ScoringTests(unittest.TestCase):
    def test_missing_evidence_must_not_raise_score(self):
        base=score_token(pair(),safe(),{'pair_address':PAIR,'price':0.001,'buyers_h1':25},{'gecko_new_pools'},[],NOW)
        incomplete=score_token(pair(),{},None,{'gecko_new_pools'},[],NOW)
        self.assertLess(incomplete['score'],base['score'])
        self.assertLess(incomplete['coverage'],base['coverage'])
        self.assertEqual(incomplete['status'],'incomplet')

    def test_flag_real_risk_despite_good_momentum(self):
        result=score_token(pair(liquidity=1200,buys=200,sells=5),safe(),{},set(),[],NOW)
        self.assertEqual(result['status'],'risque')
        self.assertTrue(any('5 000' in x for x in result['risks']))

    def test_high_score_is_not_probability(self):
        score=score_token(pair(),safe(),{'pair_address':PAIR,'price':0.001},{'gecko_new_pools'},[],NOW)
        self.assertGreater(score['score'],0)
        self.assertLessEqual(score['score'],100)
        self.assertEqual(score['gecko_gap_pct'],0)

    def test_wrong_pool_not_cross_verified(self):
        s=score_token(pair(),safe(),{'pair_address':'Z'*32,'price':0.001},set(),[],NOW)
        self.assertEqual(s['pieces']['correspondance Gecko'],0)
        self.assertTrue(any('non confirmé' in x for x in s['unknown']))

class PatternTests(unittest.TestCase):
    def test_young_buyers_are_early(self):
        p=detect_patterns(pair(),[],[],NOW)
        self.assertIn('early',[x['key'] for x in p])
        self.assertIn('momentum',[x['key'] for x in p])

    def test_early_rejects_pumped_180_pct(self):
        p=detect_patterns(pair(change=180),[],[],NOW)
        self.assertNotIn('early',[x['key'] for x in p])
        self.assertNotIn('momentum',[x['key'] for x in p])

    def test_rebound_measured_only_from_real_samples(self):
        history=[{'ts':NOW-950,'price':1.0},{'ts':NOW-700,'price':1.2},
                 {'ts':NOW-480,'price':0.95},{'ts':NOW-200,'price':0.9},
                 {'ts':NOW,'price':1.03}]
        p=detect_patterns(pair(age=100,change=4),history,[],NOW)
        self.assertIn('rebound',[x['key'] for x in p])
        self.assertNotIn('rebound',[x['key'] for x in detect_patterns(pair(),[],[],NOW)])

    def test_wallet_convergence_is_observation_only(self):
        p=detect_patterns({},[],[WALLET1,WALLET2],NOW)
        self.assertEqual(p[0]['key'],'wallets')
        self.assertIn('pas des achats certifiés',p[0]['why'])

class SourceTests(unittest.TestCase):
    def test_skip_major_nonmemes(self):
        fake=lambda url:[{'chainId':'solana','tokenAddress':WSOL},{'chainId':'solana','tokenAddress':MINT}]
        out, warnings=dex_discovery(fake)
        self.assertIn(MINT,out)
        self.assertNotIn(WSOL,out)
        self.assertFalse(warnings)

    def test_gecko_uses_included_real_mint(self):
        sample={'data':[{'relationships':{'base_token':{'data':{'id':'solana_'+MINT}}}}],
                'included':[{'id':'solana_'+MINT,'attributes':{'address':MINT}}]}
        out,errors=gecko_discovery(lambda url:sample)
        self.assertIn(MINT,out)
        self.assertEqual(len(out[MINT]),2)
        self.assertFalse(errors)

    def test_rpc_balance_increase_not_confused_with_owner(self):
        tx={'meta':{'preTokenBalances':[{'owner':WALLET1,'mint':MINT,'uiTokenAmount':{'amount':'12000','decimals':6}}],
                    'postTokenBalances':[{'owner':WALLET1,'mint':MINT,'uiTokenAmount':{'amount':'90000','decimals':6}},
                                         {'owner':WALLET2,'mint':'G'*32,'uiTokenAmount':{'amount':'900','decimals':0}}]}}
        self.assertEqual(PublicWalletMonitor.gained_mints(tx,WALLET1),[MINT])

    def test_select_valid_pair_and_ignore_quote_inversion(self):
        with patch('radar.providers.fetch',return_value=[pair(),{
                'chainId':'solana','pairAddress':'H'*32,'baseToken':{'address':WSOL},
                'quoteToken':{'address':MINT},'priceUsd':'0.1','liquidity':{'usd':9999999}}]):
            out=dex_pairs_batch([MINT])
        self.assertEqual(out[MINT]['pairAddress'],PAIR)

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'samples.db')
    def tearDown(self): self.tmp.cleanup()

    def test_wallet_hits_expire(self):
        self.store.save_wallet_event(MINT,WALLET1,'old',time.time()-3600)
        self.store.save_wallet_event(MINT,WALLET2,'new',time.time()-60)
        self.assertEqual(self.store.wallet_hits(MINT),[WALLET2])
        self.assertEqual(set(self.store.wallet_hits(MINT,7200)),{WALLET1,WALLET2})

    def test_persist_first_seen_and_snapshots(self):
        record={'mint':MINT,'symbol':'TEST','name':'Test','status':'surveillance','score':44}
        t=time.time()-150
        self.store.save_coin(record.copy(),t)
        self.store.save_coin({**record,'price_usd':0.4},t+150)
        self.assertEqual(self.store.get(MINT)['first_seen'],t)
        self.assertEqual(len(self.store.history(MINT)),1)

    def test_full_radar_cycle_mock_only(self):
        radar=Radar(Path(self.tmp.name)/'radar.db',Path(self.tmp.name)/'wallets.txt',limit=3)
        with (patch('radar.providers.discoveries',return_value=({MINT:{'gecko_new_pools'}},[])),
              patch.object(radar.wallet_monitor,'scan',return_value=(set(),[])),
              patch('radar.providers.dex_pairs_batch',return_value={MINT:pair(age=6)}),
              patch('radar.providers.quote_same_pools',return_value=({MINT:{'pair_address':PAIR,'price':0.001,'buyers_h1':30}},[])),
              patch('radar.providers.rug_report',return_value=safe())):
            self.assertTrue(radar.run_once())
        view=radar.view()
        self.assertEqual(view['stats']['total'],1)
        self.assertEqual(view['coins'][0]['mint'],MINT)
        self.assertIn('early',[x['key'] for x in view['coins'][0]['patterns']])
        self.assertFalse(view['status']['errors'])

    def test_demo_api_local_only(self):
        fake=type('RadarFake',(),{'view':staticmethod(demo_payload),'status':{'running':False}})()
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(fake,True))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port)
            with urlopen(url+'/api/data',timeout=3) as response:
                output=json.loads(response.read())
            self.assertEqual(output['status']['mode'],'demo')
            self.assertEqual(len(output['coins']),6)
            with urlopen(url+'/api/export',timeout=3) as response:
                self.assertIn('signaux_observes',response.read().decode())
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)

if __name__=='__main__': unittest.main()


class FastScanConfigTests(unittest.TestCase):
    def test_default_and_minimum_scan_interval(self):
        from radar.engine import Radar
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'scan.db'
            wallets=Path(tmp)/'wallets.txt'
            self.assertEqual(Radar(db,wallets).interval,20)
            self.assertEqual(Radar(db,wallets,interval=1).interval,20)
            self.assertEqual(Radar(db,wallets,interval=45).interval,45)

    def test_api_budgets_below_published_limits(self):
        from radar.source_scanner import _bucket,DEX,GECKO
        self.assertGreaterEqual(_bucket(DEX+'/token-profiles/latest/v1')[1],1.0)
        self.assertGreaterEqual(_bucket(DEX+'/tokens/v1/solana/mint')[1],0.2)
        self.assertGreaterEqual(_bucket(GECKO+'/networks/solana/new_pools')[1],2.0)


class LiveRefreshTests(unittest.TestCase):
    def test_scan_lifecycle_and_exclusive_manual_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            radar=Radar(Path(tmp)/'radar.db',Path(tmp)/'wallets.txt')
            started=threading.Event(); release=threading.Event()
            def slow_discovery():
                started.set()
                self.assertTrue(release.wait(3))
                return {},[]
            with (patch('radar.providers.discoveries',side_effect=slow_discovery),
                  patch.object(radar.wallet_monitor,'scan',return_value=(set(),[]))):
                worker=threading.Thread(target=radar.run_once,daemon=True);worker.start()
                self.assertTrue(started.wait(2))
                self.assertTrue(radar.status['running'])
                self.assertEqual(radar.status['phase'],'Recherche de nouveaux pools')
                self.assertFalse(radar.request_scan(), 'No overlapping scan must be queued')
                release.set();worker.join(3)
            st=radar.view()['status']
            self.assertFalse(st['running'])
            self.assertEqual(st['last_outcome'],'ok')
            self.assertEqual(st['cycle'],1)
            self.assertGreater(st['last_scan'],0)
            self.assertIsNotNone(st['duration_seconds'])
            self.assertTrue(radar.request_scan())
            self.assertFalse(radar.request_scan(), 'Do not queue the same request twice')

    def test_refresh_endpoint_does_not_start_duplicate_threads(self):
        with tempfile.TemporaryDirectory() as tmp:
            radar=Radar(Path(tmp)/'radar.db',Path(tmp)/'wallets.txt')
            server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(radar))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                url='http://127.0.0.1:'+str(server.server_port)+'/api/refresh'
                with urlopen(Request(url,method='POST'),timeout=3) as response:
                    self.assertEqual(response.status,202)
                    self.assertTrue(json.loads(response.read())['queued'])
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(Request(url,method='POST'),timeout=3)
                self.assertEqual(ctx.exception.code,409)
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2)

    def test_worker_rearms_automatic_countdown_after_manual_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            radar=Radar(Path(tmp)/'radar.db',Path(tmp)/'wallets.txt')
            with (patch('radar.providers.discoveries',return_value=({},[])),
                  patch.object(radar.wallet_monitor,'scan',return_value=(set(),[]))):
                worker=threading.Thread(target=radar.run_loop,daemon=True);worker.start()
                deadline=time.time()+3
                while time.time()<deadline and (radar.status['cycle']<1 or not radar.status['next_scan']):time.sleep(.01)
                self.assertEqual(radar.status['cycle'],1)
                self.assertGreater(radar.status['next_scan'],time.time())
                self.assertTrue(radar.request_scan())
                while time.time()<deadline and radar.status['cycle']<2:time.sleep(.01)
                self.assertEqual(radar.status['cycle'],2)
                radar.stop_event.set();radar.refresh_event.set();worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
