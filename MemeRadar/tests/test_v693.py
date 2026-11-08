"""Regression for version 6.9.3: RPC v1, cycle metrics and social-author coverage."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from radar.engine import Radar
from radar.providers import PublicWalletMonitor
from radar.store import Store
from radar.social import J7Feed

W='69d6eAnot869mAuaDZqyF8qqDmXKQZqfhmDCyfQDapFp'
M='3w2TvVmTrtq4kSkoFVrTFQgz6MX7ThzDVrx9r5c3pump'

class Tests693(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.store=Store(self.root/'test.db')

    def test_rpc_transaction_version_one_and_wallet_observed(self):
        wl=self.root/'wallets.txt'; wl.write_text(W+'\n',encoding='utf-8')
        mon=PublicWalletMonitor(self.store,str(wl))
        seen=[]
        def rpc(method, params):
            if method=='getSignaturesForAddress':return [{'signature':'some_sig','blockTime':time.time(),'err':None}]
            seen.append(params)
            return {'meta':{'preTokenBalances':[], 'postTokenBalances':[
                {'owner':W,'mint':M,'uiTokenAmount':{'amount':'100','decimals':6}}]}}
        mon.rpc=rpc
        mints,warnings=mon.scan()
        self.assertEqual(warnings,[])
        self.assertEqual(mints,{M})
        self.assertEqual(seen[0][1]['maxSupportedTransactionVersion'],1)

    def test_empty_cycle_persists_observability(self):
        r=Radar(self.root/'test.db',str(self.root/'missing.txt'))
        with patch('radar.engine.providers.discoveries',return_value=({},[])),\
             patch.object(r.wallet_monitor,'scan',return_value=(set(),[])):
            self.assertTrue(r.run_once())
        cycles=self.store.cycle_metrics()
        self.assertEqual(len(cycles),1)
        self.assertTrue(cycles[0]['success'])
        self.assertEqual(cycles[0]['selected'],0)
        stages=json.loads(cycles[0]['stages_json'])
        self.assertIn('discovery',stages)
        self.assertIn('wallets',stages)

    def test_alert_snapshot_keeps_safety_and_market_evidence(self):
        item={'mint':M,'pair_address':'7'*32,'price_usd':0.002,
              'status':'a_etudier','coverage':90,'score':70,'score_method':'amm',
              'prewatch':False,'pre_impulse':False,'risks':[], 'sources':['gecko_new_pools'],
              'safety_summary':{'mint_active':False,'freeze_active':False,
                                'rugcheck_score':42,'rugcheck_risks_at_quote':[
                                    {'name':'High holder correlation','level':'warn'}]},
              'liquidity_usd':15200,'volume_m5_usd':2500,
              'pressure_buys_m5':40,'pressure_sells_m5':12,
              'market_quote_at':time.time()}
        self.store.record_v3(item,{},time.time())
        with self.store.db() as db:
            row=db.execute('SELECT payload_json FROM research_v3_events WHERE mint=? AND kind=?',
                           (M,'a_etudier')).fetchone()
        payload=json.loads(row[0])
        self.assertEqual(payload['safety_summary']['rugcheck_score'],42)
        self.assertEqual(payload['liquidity_usd'],15200)
        self.assertEqual(payload['pressure_buys_m5'],40)

    def test_external_j7_shapes_do_not_store_raw_text_or_guess_contracts(self):
        feed=J7Feed(self.store,token='')
        payload={'isWebhook':True,'secret':'must_not_be_saved',
                 'webhook':{'embeds':[{'address':M,'description':'private example'}]}}
        self.assertTrue(feed.record_external_shape(payload))
        with self.store.db() as db:
            row=db.execute('SELECT data,kind FROM j7_events WHERE kind=?',('external_shape',)).fetchone()
        self.assertIsNotNone(row)
        self.assertNotIn('must_not_be_saved',row['data'])
        self.assertNotIn(M,row['data'])
        self.assertEqual(json.loads(row['data'])['embeds'],1)
        self.assertFalse(feed.record_external_shape(payload))

    def test_authored_posts_not_replies_or_mentions_by_other_author(self):
        now=time.time()
        posts=[{'author':'elonmusk'}, {'author':'different','text':'@elonmusk sent a tweet'}]
        with self.store.db() as db:
            for i,post in enumerate(posts):
                db.execute('INSERT INTO social_posts VALUES(?,?,?,?,?)',
                           (str(i),now,now,json.dumps(post),0))
        r=self.store.watched_social_authors(now)
        self.assertEqual(r['elonmusk'],1)
        self.assertEqual(r['rockstargames'],0)
        self.assertEqual(self.store.social_diagnostics()['watched_authors_received_2h']['elonmusk'],1)

if __name__=='__main__':unittest.main()
