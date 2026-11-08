import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from radar.store import Store
from radar.social import J7Feed
from radar.patterns import detect_patterns
from radar.engine import Radar
from test_memeradar import pair,safe,NOW,PAIR
from test_social import event,MINT

class V6Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(str(Path(self.tmp.name)/'test.db'))
    def test_initial_snapshot_immutable_and_missing_horizon(self):
        a={'mint':MINT,'score':55,'status':'risque','price_usd':1,'sources':['j7_direct_contract']}
        self.store.record_signal(a,1000)
        self.store.record_signal({**a,'score':90,'price_usd':3},1500)
        self.store.observe(MINT,1.5,1610)
        report=self.store.research_report(2400)
        result=self.store.research_for(MINT)
        self.assertEqual(result['initial_score'],55)
        self.assertEqual(result['outcomes'][0]['return_pct'],50)
        self.assertEqual(result['outcomes'][1]['state'],'missing')
        self.assertEqual(report['total'],1)
    def test_no_future_substitution_for_missing(self):
        self.store.record_signal({'mint':MINT,'score':50,'price_usd':1},1000)
        self.store.observe(MINT,4,2000)
        self.store.research_report(2000)
        self.assertEqual(self.store.research_for(MINT)['outcomes'][0]['state'],'missing')
    def test_queue_retry_and_restart(self):
        self.store.enqueue(MINT,'j7_follow_scan',1000)
        self.store.queue_done(MINT,False,1000)
        self.assertEqual(self.store.queue_due(now=1001),[])
        new=Store(self.store.path)
        self.assertEqual(new.queue_due(now=1100)[0]['mint'],MINT)
        new.enqueue(MINT,now=1100)
        self.assertEqual(new.queue_due(now=1100)[0]['source'],'j7_follow_scan')
    def test_late_followers_wake(self):
        hits=[];feed=J7Feed(self.store,hits.append,token='fake')
        feed.ingest(event(follower=None))
        feed.ingest(event(follower=120000))
        feed.ingest(event(follower=120000))
        self.assertEqual(hits,[MINT])
    def test_event_address_only_and_deleted_follow(self):
        feed=J7Feed(self.store,token='fake')
        feed.ingest_event('token_meta',{'id':'t1','mint':MINT,'tokenMeta':{'chain':'solana'}})
        self.assertEqual(self.store.queue_due()[0]['mint'],MINT)
        with self.store.db() as db:db.execute('DELETE FROM candidate_queue')
        feed.ingest_event('follow_scan',{'id':'f1','scan':{'contracts':{'ok':True,'rows':[{'ca':MINT,'chain':'solana','isDeleted':True}]}}})
        self.assertEqual(self.store.queue_due(),[])
        feed.ingest_event('profile_update',{'user':{'description':'$COIN very exciting'}})
        self.assertEqual(self.store.queue_due(),[])
    def test_old_token_momentum_not_excluded(self):
        p=pair(age=20000)
        self.assertIn('momentum',[x['key'] for x in detect_patterns(p,[],[],NOW)])
    def test_social_counts_exclude_reposts_backlog_deleted(self):
        feed=J7Feed(self.store,token='fake')
        feed.ingest(event())
        feed.ingest(event(id='1990123412341234568',isRetweet=True))
        feed.ingest(event(id='1990123412341234569'),backlog=True)
        self.assertEqual(self.store.social_context(MINT)['authors_5m'],1)
        self.store.mark_social_deleted('1990123412341234567')
        self.assertEqual(self.store.social_context(MINT)['authors_5m'],0)
    def test_existing_social_coin_priority(self):
        radar=Radar(str(Path(self.tmp.name)/'r.db'),'/nonexistent',limit=2)
        for i,m in enumerate(['C'*32,'E'*32,MINT]):
            radar.store.save_coin({'mint':m,'symbol':'T','name':'T','score':50,'status':'surveillance','price_usd':1},time.time()-100+i)
        radar.social_wakeup(MINT)
        seen=[]
        def batch(mints):seen.extend(mints);return {}
        with patch('radar.engine.providers.discoveries',return_value=({},[])),patch.object(radar.wallet_monitor,'scan',return_value=(set(),[])),patch('radar.engine.providers.dex_pairs_batch',side_effect=batch),patch('radar.engine.providers.quote_same_pools',return_value=({},[])):
            radar.run_once()
        self.assertEqual(seen[0],MINT)
    def test_evaluation_includes_hidden_risk(self):
        self.store.record_signal({'mint':MINT,'status':'risque','score':1,'price_usd':1})
        self.assertIn(MINT,self.store.evaluation_due())

if __name__=='__main__':unittest.main()
