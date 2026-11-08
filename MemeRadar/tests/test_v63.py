"""Regression cases for empty candidate UI, broadened pool discovery, social priority."""
import tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
from radar.engine import Radar
from radar.source_scanner import gecko_discovery, WSOL, SourceError
from radar.store import Store
from radar.social import J7Feed
from test_memeradar import MINT, pair, safe
from test_social import event, MINT as SOCIAL_MINT

class Regression63(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db=str(Path(self.tmp.name)/'r.db')
    def test_gecko_new_page_2_and_reverse_pair(self):
        seen=[]
        mint='Q'*32
        def get(url):
            seen.append(url)
            if 'new_pools' in url and 'page=2' in url:
                return {'data':[{'relationships':{'base_token':{'data':{'id':'solana_'+WSOL}},'quote_token':{'data':{'id':'solana_'+mint}}}}]}
            return {'data':[]}
        found,errors=gecko_discovery(get)
        self.assertIn(mint,found)
        self.assertIn('gecko_new_pools',found[mint])
        self.assertEqual(len(seen),3)
        self.assertFalse(errors)
    def test_failed_gecko_page_does_not_destroy_others(self):
        def get(url):
            if 'page=2' in url: raise SourceError('429')
            return {'data':[{'relationships':{'base_token':{'data':{'id':'solana_'+MINT}}}}]}
        found,warnings=gecko_discovery(get)
        self.assertIn(MINT,found)
        self.assertTrue(any('429' in w for w in warnings))
    def test_many_fresh_tokens_not_starved_by_known(self):
        radar=Radar(self.db,'/missing',limit=14)
        now=time.time()
        for i in range(19):
            mint=('B'*31)+chr(65+i)
            radar.store.save_coin({'mint':mint,'symbol':'OLD','name':'Old','score':30,'status':'incomplet','price_usd':1},now-100-i)
        discovered={('C'*31)+chr(65+i):{'gecko_new_pools'} for i in range(15)}
        captured=[]
        def batch(ids): captured.extend(ids); return {}
        with patch('radar.engine.providers.discoveries',return_value=(discovered,[])),\
            patch.object(radar.wallet_monitor,'scan',return_value=(set(),[])),\
            patch('radar.engine.providers.dex_pairs_batch',side_effect=batch),\
            patch('radar.engine.providers.quote_same_pools',return_value=({},[])):
            self.assertTrue(radar.run_once())
        self.assertEqual(len(captured),14)
        self.assertGreaterEqual(sum(x.startswith('C'*31) for x in captured),10)
        self.assertEqual(radar.status['new_candidates'],15)
        self.assertEqual(radar.status['pairs_found'],0)
        self.assertEqual(radar.store.count_coins(),19)
    def test_social_influencers_distinct_and_no_replies(self):
        store=Store(self.db)
        feed=J7Feed(store,token='fake')
        a=event(follower=80000)
        feed.ingest(a)
        feed.ingest({**event(id='1990123412341234568',follower=160000), 'author':{'handle':'otherTrader','id':'123456789','followersCount':160000}})
        feed.ingest({**event(id='1990123412341234569',follower=900000), 'author':{'handle':'replyTrader','id':'987654321','followersCount':900000},'isReply':True})
        ctx=store.social_context(SOCIAL_MINT)
        self.assertEqual(ctx['influential_authors_10m'],2)
        self.assertEqual(ctx['authors_5m'],2)
    def test_untrusted_social_does_not_override_market_risk(self):
        radar=Radar(self.db,'/missing')
        feed=J7Feed(radar.store,token='fake')
        feed.ingest(event(follower=900000))
        mint=SOCIAL_MINT
        p=pair(liquidity=1000)
        p['baseToken']['address']=mint
        with patch('radar.engine.providers.discoveries',return_value=({mint:{'gecko_new_pools'}},[])),\
             patch.object(radar.wallet_monitor,'scan',return_value=(set(),[])),\
             patch('radar.engine.providers.dex_pairs_batch',return_value={mint:p}),\
             patch('radar.engine.providers.quote_same_pools',return_value=({},[])),\
             patch('radar.engine.providers.rug_report',return_value=safe()):
            self.assertTrue(radar.run_once())
        coin=radar.store.get(mint)
        self.assertEqual(coin['status'],'risque')
        self.assertEqual(coin['attention_score'],0)  # J7 followers without official X verification must not boost
        self.assertEqual(radar.view()['stats']['stored'],1)

if __name__=='__main__':unittest.main()
