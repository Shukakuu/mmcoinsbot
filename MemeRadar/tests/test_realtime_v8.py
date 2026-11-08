"""V8: no look-ahead, no trade API, read-only launches, unknown-is-unknown."""
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from radar.store import Store
from radar.live_launches import LaunchFeed
from radar.realtime import normalize_launch, positive, outcome_for_samples, compare_cohorts, LaunchQuoteWorker, is_control
from radar.fast_lane import FastLane

M1='69d6eAnot869mAuaDZqyF8qqDmXKQZqfhmDCyfQDapFp'
M2='66knKYRLSSsGtmZ4umiBSSW71hU4PwMrcQkQ2L3hpump'

class V8(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.path=Path(tmp.name)/'data.db'
  self.store=Store(self.path)

 def test_schema_version_and_idempotence(self):
  with self.store.read_db() as db:
   self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],9)
  again=Store(self.path)
  self.assertEqual(again.live_health()['total'],0)
  self.assertFalse(again.live_launch(None)['new'])

 def test_normalize_no_fake_price(self):
  data=normalize_launch({'mint':M1,'name':'Doomsday','symbol':'DOOM','marketCapSol':52,'initialBuy':0.3,'vSolInBondingCurve':28,'vTokensInBondingCurve':999000000})
  self.assertEqual(data['market_cap_sol'],52)
  self.assertIsNone(data['initial_buy_sol'])  # initialBuy unit is not SOL
  self.assertNotIn('price_usd',data)
  self.assertIsNone(positive('nan'))
  self.assertIsNone(positive(float('inf')))
  self.assertIsNone(positive(-1))

 def test_j7_then_create_immediate_unpriced(self):
  now=time.time()
  self.store.record_narrative('test-event',[{'term':'DOOMSDAY','evidence':'uppercase'}],author='elonmusk',received_at=now)
  feed=LaunchFeed(self.store,threading.Event(),key='')
  with patch('radar.providers.dex_pairs_batch',side_effect=AssertionError('No DEX on event')):
   self.assertTrue(feed.ingest({'mint':M1,'name':'Doomsday','symbol':'DOOMSDAY','txType':'create','marketCapSol':80}))
  item=self.store.get(M1)
  self.assertEqual(item['status'],'incomplet')
  self.assertIsNone(item['price_usd'])
  self.assertIsNone(item['score'])
  self.assertEqual(item['narrative_signals'][0]['term'],'DOOMSDAY')
  self.assertFalse(feed.ingest({'mint':M1,'name':'Doomsday','symbol':'DOOMSDAY','txType':'create'}))
  self.assertEqual(self.store.live_health()['total'],1)
  self.assertEqual(len(self.store.live_due()),0) # due after 15s

 def test_two_clones_independent_and_no_social_risk_override(self):
  now=time.time()
  ev=[{'term':'DOOMSDAY','received_at':now,'platform':'X','author':'elonmusk'}]
  self.store.record_narrative('id', [{'term':'DOOMSDAY','evidence':'uppercase'}],received_at=now)
  feed=LaunchFeed(self.store,threading.Event(),key='')
  self.assertTrue(feed.ingest({'mint':M1,'name':'Doomsday','symbol':'DOOMSDAY'}))
  self.assertTrue(feed.ingest({'mint':M2,'name':'Doomsday','symbol':'DOOMSDAY'}))
  self.assertEqual(self.store.live_health()['matched'],2)
  self.assertEqual(self.store.get(M2)['status'],'incomplet')
  self.store.save_coin({'mint':M2,'name':'Doomsday','symbol':'DOOMSDAY','status':'risque','score':9},time.time())
  self.assertFalse(self.store.update_provisional_quote(M2,{'priceUsd':.0001}))
  self.assertEqual(self.store.get(M2)['status'],'risque')

 def test_unrelated_launch_is_recorded_but_not_promoted(self):
  feed=LaunchFeed(self.store,threading.Event(),key='')
  self.assertTrue(feed.ingest({'mint':M1,'name':'Totally unrelated','symbol':'OTHER'}))
  self.assertIsNone(self.store.get(M1))
  self.assertEqual(self.store.live_health()['total'],1)

 def test_zero_latency_not_invented_with_future_j7_timestamp(self):
  self.store.record_highlight(M1,'contract',post_id='one',post_at=2000,now=1930)
  self.assertLess(self.store.first_highlights([M1])[M1]['latency_s'],0)

 def test_outcome_no_future_peak_and_missing(self):
  t=1000
  self.assertEqual(outcome_for_samples([(1031,1),(1301,1.2),(1340,99)],t,300),20.0)
  self.assertIsNone(outcome_for_samples([(1001,1),(1301,1.2)],t,300))
  self.assertIsNone(outcome_for_samples([(1031,1)],t,300))

 def test_control_deterministic(self):
  self.assertEqual(is_control(M1),is_control(M1))
  self.assertEqual(is_control(M2),is_control(M2))
  self.assertTrue(self.store.live_launch(normalize_launch({'mint':M1,'name':'Social','symbol':'SOC'}),[{'term':'SOC'}],control=True)['matched'])
  self.assertEqual(self.store.live_health()['controls'],1)
  self.assertEqual(self.store.live_health()['matched'],1)
  self.assertIsNone(compare_cohorts(self.store,now=time.time()+500)['comparison']['matched']['median_price_change_pct'])

 def test_quote_worker_progresses_with_missing_data(self):
  now=time.time()
  data=normalize_launch({'mint':M1,'name':'Demo','symbol':'DMO'})
  self.store.live_launch(data,evidence=[{'term':'DMO'}],at=now-20)
  worker=LaunchQuoteWorker(self.store,threading.Event(),get_pairs=lambda ms:{M1:{'priceUsd':'0.00001','liquidity':{'usd':500}}})
  self.assertEqual(worker.run_once(now=now),1)
  self.assertEqual(self.store.live_health()['quoted_tokens'],1)
  self.assertEqual(self.store.live_health()['pending_quotes'],1)

 def test_fast_lane_no_dex_needed_to_show_candidate(self):
  lane=FastLane(self.store,threading.Event())
  self.assertEqual(lane.observe_immediate([M1]),1)
  self.assertEqual(self.store.get(M1)['status'],'incomplet')
  self.assertIsNone(self.store.get(M1)['price_usd'])
  self.assertFalse(self.store.update_provisional_quote(M1,{}))
  self.assertTrue(self.store.update_provisional_quote(M1,{'priceUsd':'0.00005','pairAddress':M2,'liquidity':{'usd':1200}}))
  self.assertEqual(self.store.get(M1)['status'],'incomplet')
  self.assertEqual(self.store.get(M1)['price_usd'],.00005)

if __name__=='__main__':unittest.main()
