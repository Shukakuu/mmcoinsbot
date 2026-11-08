"""Regressions: archived coins, no phantom fresh scores, safe restart endpoint."""
import json, tempfile, threading, time, unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from radar.engine import Radar, LIVE_MAX_AGE_S
from main import make_handler
from test_memeradar import pair, safe

MINT='A'*32

class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.radar=Radar(str(Path(self.temp.name)/'test.db'),'/missing')
    def old(self, seconds=60000, score=89):
        now=time.time()-seconds
        self.radar.store.save_coin({'mint':MINT,'symbol':'OLD','name':'Historic',
            'score':score,'status':'a_etudier','coverage':100,'sources':['gecko_new_pools'],
            'patterns':[{'key':'early','label':'Départ précoce'}],'price_usd':.02,
            'pair_address':'B'*32},now)
    def test_ancient_high_score_is_archived_not_live(self):
        self.old()
        view=self.radar.view()
        coin=view['coins'][0]
        self.assertFalse(coin['fresh'])
        self.assertEqual(coin['previous_status'],'a_etudier')
        self.assertEqual(coin['status'],'expire')
        self.assertEqual(view['stats']['interesting'],0)
        self.assertEqual(view['stats']['expired'],1)
        self.assertEqual(self.radar.store.get(MINT)['status'],'a_etudier')
    def test_recent_without_safety_is_unverified_v2(self):
        self.old(25)
        coin=self.radar.view()['coins'][0]
        self.assertTrue(coin['fresh'])
        self.assertEqual(coin['status'],'incomplet')
        self.assertEqual(coin['security_gate']['state'],'unverified')
        self.assertLess(coin['data_age_seconds'],LIVE_MAX_AGE_S)
    def test_missing_live_pair_does_not_fake_update(self):
        self.old()
        with patch('radar.engine.providers.discoveries',return_value=({},[])),\
             patch.object(self.radar.wallet_monitor,'scan',return_value=(set(),[])),\
             patch('radar.engine.providers.dex_pairs_batch',return_value={}),\
             patch('radar.engine.providers.quote_same_pools',return_value=({},[])):
            self.assertTrue(self.radar.run_once())
        self.assertEqual(self.radar.view()['coins'][0]['status'],'expire')
    def test_revalidated_token_reenters_live(self):
        self.old()
        p=pair(liquidity=19000)
        p['baseToken']['address']=MINT
        with patch('radar.engine.providers.discoveries',return_value=({},[])),\
             patch.object(self.radar.wallet_monitor,'scan',return_value=(set(),[])),\
             patch('radar.engine.providers.dex_pairs_batch',return_value={MINT:p}),\
             patch('radar.engine.providers.quote_same_pools',return_value=({},[])),\
             patch('radar.engine.providers.rug_report',return_value=safe()):
            self.assertTrue(self.radar.run_once())
        coin=self.radar.view()['coins'][0]
        self.assertTrue(coin['fresh'])
        self.assertNotEqual(coin['status'],'expire')
        self.assertEqual(coin['liquidity_usd'],19000)

class RestartApiTests(unittest.TestCase):
    def setUp(self):
        self.flag=[]
        def restart():
            if self.flag:return False
            self.flag.append('called');return True
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(None,demo=False,j7=None,verifier=None,restart_callback=restart))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(lambda:(self.server.shutdown(),self.thread.join(timeout=3)))
        self.url=f'http://127.0.0.1:{self.server.server_port}/api/restart'
    def test_restart_requires_local_header(self):
        with self.assertRaises(HTTPError) as e: urlopen(Request(self.url,method='POST'),timeout=3)
        self.assertEqual(e.exception.code,403)
        self.assertFalse(self.flag)
    def test_restart_queues_only_once(self):
        request=lambda:Request(self.url,method='POST',headers={'X-MemeRadar-Local-Action':'restart'})
        with urlopen(request(),timeout=3) as response:
            self.assertEqual(response.status,202)
            self.assertTrue(json.load(response)['restarting'])
        with self.assertRaises(HTTPError) as e:urlopen(request(),timeout=3)
        self.assertEqual(e.exception.code,409)
        self.assertEqual(self.flag,['called'])
    def test_rejects_cross_origin(self):
        req=Request(self.url,method='POST',headers={'X-MemeRadar-Local-Action':'restart','Origin':'https://evil.example'})
        with self.assertRaises(HTTPError) as e:urlopen(req,timeout=3)
        self.assertEqual(e.exception.code,403)
        self.assertFalse(self.flag)

if __name__=='__main__':unittest.main()
