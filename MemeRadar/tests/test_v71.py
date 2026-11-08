"""V7.1 contracts: no trade, real identity, provenance, safe provisional lane."""
import tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock
from radar.store import Store
from radar.social import J7Feed
from radar.narrative_intelligence import extract_phrases,topic_is_related,watch_evidence
from radar.live_launches import LaunchFeed
from radar.fast_lane import FastLane
from radar.engine import Radar

M1='6PtLvzA8eY1NwUw1E9h48c7xphRvD6fK2ymDGQY1d1Nd'
M2='69d6eAnot869mAuaDZqyF8qqDmXKQZqfhmDCyfQDapFp'

class Words(unittest.TestCase):
 def test_j7_highlight_like_word_not_contract(self):
  xs=extract_phrases('More than 50 governments preparing for DOOMSDAY!')
  self.assertIn('DOOMSDAY',[x['term'] for x in xs]);self.assertTrue(all('mint' not in x for x in xs))
 def test_no_urls_handles_or_bait(self):
  xs=extract_phrases('BREAKING NEWS https://example.com/DOOMSDAY @ELONMUSK LIVE')
  self.assertEqual(xs,[])
 def test_gta_alias_and_openai(self):
  self.assertIn('GTA VI',[x['term'] for x in extract_phrases('the GTA6 trailer in Vice City')])
  self.assertIn('OPENAI',[x['term'] for x in extract_phrases('OpenAI announces a model')])
 def test_ticker_no_fuzzy_identity(self):
  self.assertTrue(topic_is_related('DOOMSDAY','Doomsday Coin','Doom'))
  self.assertFalse(topic_is_related('DOOMSDAY','Doomed Cat','Doom'))
  self.assertFalse(topic_is_related('OPENAI','A.I. Moon', 'AI'))
 def test_no_social_lookahead(self):
  future=time.time()+100
  self.assertEqual(watch_evidence('Doomsday','DOOMSDAY',[{'term':'DOOMSDAY','received_at':future}]),[])

class Pipeline(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.store=Store(Path(self.temp.name)/'radar.db')
 def test_social_event_persists_and_relaunch_matches(self):
  author={'id':'999','handle':'elonmusk','followersCount':1000000}
  feed=J7Feed(self.store,token='fake')
  event={'id':'2090000000000000001','createdAt':time.time(),'author':author,
         'text':'DOOMSDAY, coming soon.'}
  feed.ingest(event)
  self.assertTrue(any(n['term']=='DOOMSDAY' for n in self.store.narrative_summary()))
  self.assertEqual(feed.ingest(event)['id'],event['id'])
  summary=[n for n in self.store.narrative_summary() if n['term']=='DOOMSDAY']
  self.assertEqual(summary[0]['mentions'],1)
  launches=LaunchFeed(self.store,__import__('threading').Event(),key='')
  self.assertTrue(launches.ingest({'mint':M1,'name':'Doomsday Coin','symbol':'DOOMSDAY','txType':'create'}))
  self.assertFalse(launches.ingest({'mint':M1,'name':'Doomsday Coin','symbol':'DOOMSDAY','txType':'create'}))
  self.assertEqual(self.store.queue_due()[0]['source'],'launch_narrative')
 def test_clones_as_candidates_not_certified(self):
  for m in (M1,M2):
   self.store.save_coin({'mint':m,'name':'Doomsday Coin','symbol':'DOOMSDAY','status':'risque','score':0},time.time())
  self.assertEqual(set(self.store.find_phrase_candidates('DOOMSDAY is coming',limit=10)),{M1,M2})
  self.assertEqual(self.store.get(M1)['status'],'risque')
 def test_external_webhook_explicit_address_only(self):
  seen=[];feed=J7Feed(self.store,seen.append,token='dummy')
  card={'id':'wh-pumppairs:xyz','isWebhook':True,'webhook':{'handle':'pumppairs',
        'embeds':[{'address':M1},{'address':'not-a-valid-mint'}]},'text':'NEW PUMP PAIR'}
  feed.ingest_external(card)
  self.assertEqual(seen,[M1]);self.assertEqual(self.store.launch_recent()[0]['mint'],M1)
  feed.ingest_external(card)
  self.assertEqual(seen,[M1])
 def test_external_social_hashtags_and_no_contract(self):
  feed=J7Feed(self.store,token='fake')
  post={'id':'yt-somevideo','platform':'YOUTUBE','author':{'handle':'gamer'},
        'createdAt':time.time(),'text':'#Doomsday just went viral'}
  feed.ingest_external(post)
  self.assertIn('DOOMSDAY',[x['term'] for x in self.store.narrative_summary()])
  self.assertEqual(self.store.launch_recent(),[])
 def test_fast_lane_never_overrides_risk(self):
  self.store.save_coin({'mint':M1,'name':'BAD','symbol':'BAD','status':'risque','score':7,'risks':['dev sold']},time.time())
  self.store.launch_event(M1,'creation','Bad','BAD')
  lane=FastLane(self.store,__import__('threading').Event())
  lane.observe([M1],get_pairs=lambda m:{M1:{'baseToken':{'name':'Bad'}}})
  self.assertEqual(self.store.get(M1)['status'],'risque')
 def test_fast_lane_no_fake_safety(self):
  self.store.launch_event(M1,'creation','Doomsday Coin','DOOMSDAY')
  lane=FastLane(self.store,__import__('threading').Event())
  lane.observe([M1],get_pairs=lambda m:{})
  row=self.store.get(M1)
  self.assertEqual(row['status'],'incomplet')
  self.assertFalse(row['eligible'])
  self.assertIsNone(row['price_usd'])
  self.assertEqual(row['risk_assessment'],'not_yet_available')
 def test_no_paid_subscriptions(self):
  from radar import live_launches
  import inspect
  s=inspect.getsource(live_launches.LaunchFeed.run)
  self.assertNotIn("'method':'subscribeTokenTrade'",s)
  self.assertIn('subscribeNewToken',s)
  self.assertIn('subscribeMigration',s)
 def test_no_auto_transactions(self):
  import inspect
  from radar import fast_lane
  s=inspect.getsource(fast_lane)
  for term in ('sendTransaction','buy_token','sell_token','sign_transaction'):
   self.assertNotIn(term,s)

if __name__=='__main__':unittest.main()
