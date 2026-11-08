"""Regression cases found in the 2026-11-07 audit; no external network."""
import json
import queue
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from radar.store import Store
from radar.providers import PublicWalletMonitor
from radar.fast_lane import FastLane
from radar.intelligence import clone_groups, wallet_inventory, report
from radar.realtime import normalize_launch, outcome_for_samples, LaunchQuoteWorker
from radar.j7_hub import HighlightTracker
from radar.source_scanner import number
from radar.onchain_risk import parse_risk
from radar.scoring import score_token
from radar.curve import assess_curve

M='69d6eAnot869mAuaDZqyF8qqDmXKQZqfhmDCyfQDapFp'
N='66knKYRLSSsGtmZ4umiBSSW71hU4PwMrcQkQ2L3hpump'

class Audit(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.store=Store(Path(self.temp.name)/'radar.db')

 def test_exact_wallet_unit_above_float_precision(self):
  def item(n):return {'mint':M,'owner':N,'uiTokenAmount':{'amount':str(n),'decimals':20}}
  tx={'meta':{'preTokenBalances':[item(2**64-2)],'postTokenBalances':[item(2**64-1)]}}
  self.assertEqual(PublicWalletMonitor.gained_mints(tx,N),[M])
  tx['meta']['err']={'error':'failed'}
  self.assertEqual(PublicWalletMonitor.gained_mints(tx,N),[])

 def test_transfers_between_owned_accounts_are_not_gains(self):
  def item(n):return {'mint':M,'owner':N,'uiTokenAmount':{'amount':str(n),'decimals':9}}
  self.assertEqual(PublicWalletMonitor.gained_mints({'meta':{'preTokenBalances':[item(200)],'postTokenBalances':[item(50),item(150)]}},N),[])

 def test_wallet_missing_tx_does_not_advance_cursor(self):
  monitor=PublicWalletMonitor(self.store,Path(self.temp.name)/'wallets.txt')
  self.store.set_cursor(N,'old')
  with patch.object(monitor,'wallets',return_value=[N]),patch.object(monitor,'rpc',side_effect=[[{'signature':'new','err':None,'blockTime':time.time()}],None]):
   found,warnings=monitor.scan()
  self.assertEqual(self.store.cursor(N),'old');self.assertFalse(found);self.assertTrue(warnings)

 def test_fast_retry_recovers_unindexed_quote(self):
  lane=FastLane(self.store,threading.Event());lane.observe_immediate([M])
  lane.quote_once(lambda m:{},now=0)
  self.assertEqual(lane.quote_once(lambda m:{},now=4),0)
  lane.quote_once(lambda m:{M:{'priceUsd':'2','baseToken':{'name':'Resolved','symbol':'NEW'}}},now=5)
  self.assertEqual(self.store.get(M)['price_usd'],2)
  self.assertEqual(self.store.get(M)['name'],'Resolved');self.assertFalse(lane.quote_retry)

 def test_full_event_queue_allows_later_resubmit(self):
  lane=FastLane(self.store,threading.Event());lane.events=queue.Queue(maxsize=1)
  lane.events.put(N);self.assertFalse(lane.submit(M));lane.events.get();self.assertTrue(lane.submit(M))

 def test_quote_retry_cannot_erase_risk(self):
  lane=FastLane(self.store,threading.Event());lane.observe_immediate([M])
  self.store.save_coin({'mint':M,'symbol':'X','name':'X','status':'risque','score':10},time.time())
  lane.quote_once(lambda m:{M:{'priceUsd':'4'}},now=0)
  self.assertEqual(self.store.get(M)['status'],'risque')

 def test_retries_bounded(self):
  lane=FastLane(self.store,threading.Event());lane.observe_immediate([M])
  for i in range(12):lane.quote_once(lambda m:{},now=i*100)
  self.assertFalse(lane.quote_retry)

 def test_j7_missing_quote_retry_and_recovery(self):
  t=time.time();r=self.store.record_highlight(M,'post_ca',post_id='123456789',now=t)
  self.store.set_reference(r['id'],1,t)
  tracker=HighlightTracker(self.store,threading.Event(),get_pairs=lambda m:{})
  tracker.tick(t+61)
  with self.store.read_db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM j7_highlight_outcomes').fetchone()[0],0)
  tracker.get_pairs=lambda m:{M:{'priceUsd':'1.25'}};tracker.tick(t+80)
  with self.store.read_db() as db:self.assertEqual(db.execute('SELECT return_pct FROM j7_highlight_outcomes WHERE horizon=60').fetchone()[0],25)

 def test_no_quotes_between_horizons(self):
  t=time.time();r=self.store.record_highlight(M,'post_ca',post_id='123456789',now=t)
  self.store.set_reference(r['id'],1,t)
  self.assertEqual(self.store.tracking_due(t+20),[])

 def test_launch_quotes_reach_six_hours(self):
  t=time.time();self.store.live_launch(normalize_launch({'mint':M}),[{'term':'TEST'}],at=t)
  self.store.live_quote_result(M,{'priceUsd':'1'},at=t+4000)
  self.assertEqual(self.store.live_health()['pending_quotes'],1)
  self.store.live_quote_result(M,{'priceUsd':'1.2'},at=t+21620)
  self.assertEqual(self.store.live_health()['pending_quotes'],1)
  self.store.live_quote_result(M,{},at=t+21841)
  self.assertEqual(self.store.live_health()['pending_quotes'],0)

 def test_explicit_sol_amount_only(self):
  self.assertIsNone(normalize_launch({'mint':M,'initialBuy':999999})['initial_buy_sol'])
  self.assertEqual(normalize_launch({'mint':M,'initialBuy':999999,'solAmount':.2})['initial_buy_sol'],.2)

 def test_schema_migration_clears_wrong_unit_once(self):
  with self.store.db() as db:
   db.execute('PRAGMA user_version=8')
   db.execute("INSERT INTO live_launches(mint,first_at,last_at,name,symbol,platform,initial_buy_sol) VALUES(?,1,1,'a','a','pumpfun',9999)",(M,))
  Store(self.store.path)
  with self.store.read_db() as db:self.assertIsNone(db.execute('SELECT initial_buy_sol FROM live_launches').fetchone()[0])
  with self.store.db() as db:db.execute('UPDATE live_launches SET initial_buy_sol=.2')
  Store(self.store.path)
  with self.store.read_db() as db:self.assertEqual(db.execute('SELECT initial_buy_sol FROM live_launches').fetchone()[0],.2)

 def test_unknown_rpc_not_zero_holdings(self):
  x=parse_risk({'value':{'amount':'100'}},{'value':[{'amount':'20'}]},{'value':[{'bad':'data'}]})
  self.assertIsNone(x['launch_wallet_pct']);self.assertEqual(x['raw_top10_pct'],20)

 def test_invalid_numbers(self):
  for x in (True,False,'NaN','inf',None):self.assertIsNone(number(x))

 def test_wallets_cannot_boost_score(self):
  a=score_token({}, {}, {}, [], [], time.time())
  b=score_token({}, {}, {}, [], [M], time.time())
  self.assertEqual(a['score'],b['score'])

 def test_missing_authority_not_review_candidate(self):
  t=time.time();pair={'liquidity':{'usd':200000},'volume':{'h1':500000},'txns':{'h1':{'buys':100,'sells':20}},'priceChange':{'m5':9},'pairCreatedAt':(t-120)*1000}
  x=score_token(pair,{'top10_pct':10,'rugcheck_risk_score':1},{},['gecko_new_pools','gecko_trending_pools'],[],t)
  self.assertGreaterEqual(x['score'],65);self.assertNotEqual(x['status'],'a_etudier')

 def test_clone_dedup_and_normalization(self):
  rows=[{'mint':M,'name':'Moon   Dog','symbol':'DOG','first_at':1},{'mint':M,'name':'Moon Dog','symbol':'DOG','first_at':2}]
  self.assertEqual(clone_groups(rows),[])
  rows.append({'mint':N,'name':'moon dog','symbol':'dog','first_at':3})
  g=clone_groups(rows)[0];self.assertEqual(g['count'],2);self.assertFalse(g['flow_verified'])

 def test_same_short_ticker_alone_not_clone(self):
  self.assertEqual(clone_groups([{'mint':M,'name':'Moon Dog','symbol':'DOG'},{'mint':N,'name':'Star Dog','symbol':'DOG'}]),[])

 def test_real_registry_counts(self):
  x=wallet_inventory(Path(__file__).resolve().parents[1]/'wallets.txt')
  self.assertEqual(x['registered'],353);self.assertEqual(x['active_count'],5)

 def test_read_connection_cannot_write(self):
  with self.store.read_db() as db:
   with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM coins')

 def test_return_arithmetic_not_peak(self):
  self.assertEqual(outcome_for_samples([(1030,10),(1300,11),(1301,200)],1000,300),10)
  self.assertEqual(outcome_for_samples([(1030,10),(1300,2)],1000,300),-80)

 def test_cohort_never_relabelled_by_later_evidence(self):
  data=normalize_launch({'mint':M})
  self.store.live_launch(data,[],at=100,control=True)
  r=self.store.live_launch(data,[{'term':'LATER'}],at=200)
  self.assertFalse(r['matched']);self.assertTrue(r['control'])

 def test_empty_intelligence_json(self):
  x=report(self.store,Path(self.temp.name)/'wallets.txt');json.dumps(x,allow_nan=False)
  self.assertEqual(x['authors'],[]);self.assertEqual(x['clones'],[])

if __name__=='__main__':unittest.main()
