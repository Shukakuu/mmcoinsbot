"""Regressions for real J7 feed event shapes and post/mint linking."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from radar.social import J7Feed, extract_mints
from radar.store import Store
from test_social import MINT,event

MINT2='So11111111111111111111111111111111111111112'

class Social62(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.addCleanup(self.tmp.cleanup)
  self.store=Store(str(Path(self.tmp.name)/'db.sqlite3'))
  self.seen=[]
  self.feed=J7Feed(self.store,self.seen.append,token='test-only')
 def meta(self,mint=MINT,parent='1990123412341234567'):
  return {'id':parent,'mint':mint,'tokenMeta':{'mint':mint,'symbol':'X','name':'Token','market':'pumpfun'}}
 def test_meta_enrichment_after_tweet(self):
  self.feed.ingest(event(text='launch soon'))
  self.feed.ingest_event('token_meta',self.meta())
  self.assertIn(MINT,self.store.recent_social()[0]['mints'])
  self.assertEqual(self.store.social_diagnostics()['linked_posts'],1)
  self.assertEqual(self.seen,[MINT])
 def test_meta_early_is_buffered_until_tweet(self):
  self.feed.ingest_event('token_meta',self.meta())
  self.assertEqual(self.store.recent_social(),[])
  self.feed.ingest(event(text='watch now'))
  self.assertEqual(self.store.recent_social()[0]['mints'],[MINT])
 def test_same_parent_multiple_token_meta_events_not_dropped(self):
  self.feed.ingest(event(text='launch soon'))
  self.feed.ingest_event('token_meta',self.meta())
  self.feed.ingest_event('token_meta',self.meta(MINT2))
  self.feed.ingest_event('token_meta',self.meta())
  self.assertEqual(set(self.store.recent_social()[0]['mints']),{MINT,MINT2})
  self.assertEqual(self.store.social_diagnostics()['mint_mentions'],2)
  self.assertEqual(self.seen,[MINT,MINT2])
 def test_sparse_j7_update_without_author_can_add_ca(self):
  self.feed.ingest(event(text='watch now',isReply=True))
  before=self.store.get_social_post('1990123412341234567')
  self.feed.ingest({'id':before['id'],'card':{'description':'CA: '+MINT},'text':' '})
  post=self.store.get_social_post(before['id'])
  self.assertEqual(post['mints'],[MINT])
  self.assertTrue(post['is_reply'])
  self.assertEqual(self.seen,[])
  self.assertEqual(post['created_at'],before['created_at'])
 def test_late_update_keeps_meta_link(self):
  self.feed.ingest(event(text='watch now'))
  self.feed.ingest_event('token_meta',self.meta())
  self.feed.ingest(event(text='other news'))
  self.assertEqual(self.store.recent_social()[0]['mints'],[MINT])
 def test_strict_mint_in_own_rich_content(self):
  self.assertEqual(extract_mints({'text':'coin soon', 'card':{'description':'CA: '+MINT}}),[MINT])
  self.assertEqual(extract_mints({'text':'coin soon', 'article':{'title':'Token '+MINT}}),[MINT])
  self.assertEqual(extract_mints({'components':[{'type':'text','text':'Pump: '+MINT}]}),[MINT])
  self.assertEqual(extract_mints({'quotedTweet':{'text':MINT},'text':'interesting'}),[])
 def test_json_export_sample_has_no_contract(self):
  # Example user data is a general-purpose X feed, not guaranteed meme feed.
  sample={'id':'2115452523737969143','createdAt':int(time.time()*1000),
          'author':{'handle':'Gemini','followersCount':635272},
          'text':'Bitcoin dipped below $80K and closed back above it'}
  self.assertEqual(self.feed.ingest(sample)['mints'],[])
  self.assertEqual(self.feed.report()['received'],1)
  self.assertEqual(self.feed.report()['new_mints'],0)
 def test_stats_do_not_leak_jwt(self):
  self.feed.ingest(event())
  self.assertNotIn('test-only',json.dumps(self.store.social_diagnostics()))

if __name__=='__main__':unittest.main()
