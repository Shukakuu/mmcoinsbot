import tempfile,time,unittest,threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from radar.store import Store
from radar.social import J7Feed
from radar.engine import Radar
from radar import source_scanner as ss
from test_social import MINT,event
from test_memeradar import pair,safe,PAIR

class Regression61(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.store=Store(str(Path(self.tmp.name)/'test.db'))
 def test_concurrent_feed_and_research_writes(self):
  gate=threading.Barrier(4)
  def worker(n):
   # Separate Store instances also exercise SQLite's transaction reservation.
   store=Store(self.store.path);feed=J7Feed(store,token='fake')
   gate.wait()
   for i in range(20):
    feed.ingest(event(id=str(1990123412341234567+n*100+i)))
    store.record_signal({'mint':MINT,'price_usd':1,'score':50})
    store.observe(MINT,1,time.time())
    store.research_report()
  with ThreadPoolExecutor(max_workers=4) as pool:
   list(pool.map(worker,range(4)))
  self.assertEqual(len(self.store.recent_social(100)),80)
 def test_gecko_429_does_not_stop_coin_analysis(self):
  radar=Radar(str(Path(self.tmp.name)/'r.db'),'/missing')
  p=pair();mint=p['baseToken']['address']
  with patch('radar.engine.providers.discoveries',return_value=({mint:{'dex_profiles'}},[])),patch.object(radar.wallet_monitor,'scan',return_value=(set(),[])),patch('radar.engine.providers.dex_pairs_batch',return_value={mint:p}),patch('radar.engine.providers.quote_same_pools',return_value=({},['Gecko confirmation prix: gecko HTTP 429'])),patch('radar.engine.providers.rug_report',return_value=safe()),patch('radar.engine.gecko_pause_seconds',return_value=120):
   self.assertTrue(radar.run_once())
  saved=radar.store.get(mint)
  self.assertIsNotNone(saved)
  self.assertEqual(saved['coverage'],90)
  self.assertGreater(radar.status['gecko_resume_at'],time.time())
  self.assertEqual(radar.status['errors'],[])
 def test_old_records_are_explicitly_not_eligible_v2(self):
  radar=Radar(self.store.path,'/missing')
  self.store.save_coin({'mint':MINT,'symbol':'OLD','name':'Old','score':60,'status':'surveillance','price_usd':1},time.time()-86400)
  coins=radar.view()['coins'];self.assertEqual(len(coins),1)
  self.assertFalse(coins[0]['eligible'])
  self.assertEqual(coins[0]['security_gate']['state'],'unverified')
 def test_j7_update_error_clears_after_success(self):
  feed=J7Feed(self.store,token='fake');feed._state(error='Mise à jour ignorée : OperationalError')
  feed.ingest(event());self.assertIsNone(feed.report()['error'])

if __name__=='__main__':unittest.main()
