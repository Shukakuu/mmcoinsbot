"""J7 documented author badge is recognized, but weaker than X official lookup."""
import tempfile,unittest
from pathlib import Path
from radar.social import J7Feed
from radar.store import Store
from radar.engine import Radar
from unittest.mock import patch
from test_memeradar import pair, safe
from test_social import event,MINT

class J7BadgeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.store=Store(str(Path(self.tmp.name)/'r.db'))
  self.feed=J7Feed(self.store,token='demo-j7')
 def e(self,num,verified=True,parody=False):
  p=event(follower=150000)
  p['id']=str(1990123412341234000+num)
  p['author']={'id':str(200000000+num),'handle':'trader'+str(num),'followersCount':150000,
               'verified':verified,'badge':'blue','verifiedType':'blue','parody':parody}
  return p
 def test_only_reported_badged_not_parody_counts(self):
  self.feed.ingest(self.e(1,True))
  self.feed.ingest(self.e(2,False))
  self.feed.ingest(self.e(3,True,True))
  c=self.store.social_context(MINT)
  self.assertEqual(c['influential_authors_10m'],3)
  self.assertEqual(c['j7_badged_authors_10m'],1)
  self.assertEqual(c['verified_influential_authors_10m'],0)
  self.assertEqual(c['j7_unconfirmed_authors_10m'],1)
 def test_official_x_no_badge_overrides_upstream(self):
  p=self.e(1)
  self.feed.ingest(p)
  self.store.attach_x_profile(p['id'],{'id':p['author']['id'],'handle':p['author']['handle'],
    'verified':False,'source':'x_official_api','checked_at':1,'warnings':[],'followers':150000})
  self.assertEqual(self.store.social_context(MINT)['j7_badged_authors_10m'],0)
 def test_sparse_update_preserves_upstream_badge(self):
  p=self.e(1);self.feed.ingest(p)
  self.feed.ingest({'id':p['id'],'text':'later update CA '+MINT})
  saved=self.store.get_social_post(p['id'])
  self.assertIs(saved['j7_verified'],True)
  self.assertEqual(saved['j7_verified_type'],'blue')
 def test_j7_badges_affect_priority_but_not_risk(self):
  self.feed.ingest(self.e(1))
  self.feed.ingest(self.e(2))
  radar=Radar(self.store.path,'/missing')
  p=pair(liquidity=1000)
  p['baseToken']['address']=MINT
  with patch('radar.engine.providers.discoveries',return_value=({MINT:{'dex_profiles'}},[])),\
       patch.object(radar.wallet_monitor,'scan',return_value=(set(),[])),\
       patch('radar.engine.providers.dex_pairs_batch',return_value={MINT:p}),\
       patch('radar.engine.providers.quote_same_pools',return_value=({},[])),\
       patch('radar.engine.providers.rug_report',return_value=safe()):
    self.assertTrue(radar.run_once())
  coin=radar.store.get(MINT)
  self.assertGreater(coin['attention_score'],0)
  self.assertEqual(coin['status'],'risque')
  self.assertEqual(coin['social_context']['j7_badged_authors_10m'],2)
 def test_mint_needed_for_attention(self):
  p=self.e(1);p['text']='a popular meme maybe';p['contractAddress']=None
  self.feed.ingest(p)
  self.assertEqual(self.store.social_context(MINT)['j7_badged_authors_10m'],0)

if __name__=='__main__':unittest.main()
