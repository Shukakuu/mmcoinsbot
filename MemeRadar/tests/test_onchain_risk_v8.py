import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from radar.store import Store
from radar.onchain_risk import ratio_pct,parse_risk,SolanaRiskObserver
from radar.realtime import normalize_launch
M='69d6eAnot869mAuaDZqyF8qqDmXKQZqfhmDCyfQDapFp'

class Risks(unittest.TestCase):
 def test_top10_raw_and_owner(self):
  v=parse_risk({'value':{'amount':'1000'}},{'value':[{'amount':'100'},{'amount':'150'}]},
    {'value':[{'account':{'data':{'parsed':{'info':{'tokenAmount':{'amount':'50'}}}}}}]})
  self.assertEqual(v['raw_top10_pct'],25.0)
  self.assertEqual(v['launch_wallet_pct'],5.0)
  self.assertIn('réserves',v['warning'])
 def test_rpc_no_data_unknown(self):
  self.assertIsNone(ratio_pct(100,0))
  self.assertIsNone(ratio_pct(101,100))
  self.assertIsNone(parse_risk({'value':{'amount':'1'}},{'value':[{'amount':'hello'}]}))
 def test_nonblocking_rpc_error_unknown(self):
  with tempfile.TemporaryDirectory() as tmp:
   st=Store(Path(tmp)/'radar.db')
   now=time.time()
   st.live_launch(normalize_launch({'mint':M,'name':'Demo','symbol':'D'}),[{'term':'Demo'}],at=now-30)
   obs=SolanaRiskObserver(st,threading.Event(),request=lambda a,b: (_ for _ in ()).throw(TimeoutError('timeout')))
   self.assertTrue(obs.run_once(now))
   data=st.live_risk(M)
   self.assertIsNone(data['raw_top10_pct'])
   self.assertEqual(data['error'],'TimeoutError')
   self.assertEqual(st.live_health()['matched'],1)
 def test_real_risk_mocked_rpc(self):
  with tempfile.TemporaryDirectory() as tmp:
   st=Store(Path(tmp)/'radar.db');now=time.time()
   st.live_launch(normalize_launch({'mint':M,'name':'Demo','symbol':'D'}),[{'term':'Demo'}],at=now-35)
   obj=SolanaRiskObserver(st,threading.Event(),request=lambda method,params: {'getTokenSupply':{'value':{'amount':'1000'}},'getTokenLargestAccounts':{'value':[{'amount':'150'}]}}[method])
   self.assertTrue(obj.run_once(now))
   self.assertEqual(st.live_risk(M)['raw_top10_pct'],15)
if __name__=='__main__':unittest.main()
