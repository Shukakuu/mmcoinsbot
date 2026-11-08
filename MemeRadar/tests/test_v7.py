"""v7 guardrails: real account coverage, conservative GTA linking, non-blocking RPC."""
import json
import tempfile
import time
import unittest
import threading
from pathlib import Path
from unittest.mock import patch
from radar.narratives import normal, gta_theme_match, contextual_matches, TrendsMonitor, parse_trends_rss
from radar.j7_accounts import evaluate_coverage, fetch_coverage, PRIORITY_HANDLES
from radar.store import Store
from radar.engine import Radar
from radar.social import J7Feed

ALPHABET='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
def mint_for(n):
 value=int.from_bytes(bytes([n])*32,'big')
 out=''
 while value:
  value,r=divmod(value,58); out=ALPHABET[r]+out
 return out
MINT=mint_for(3)

class NarrativeTests(unittest.TestCase):
 def test_arc_variants_and_clones(self):
  self.assertEqual(normal('Grand Theft Auto VI'), 'gta 6')
  self.assertEqual(normal('GTA6'), 'gta 6')
  self.assertTrue(gta_theme_match('Vice City','GTA 6 trailer released'))
  self.assertTrue(gta_theme_match('GTA VI meme','Grand Theft Auto VI today'))
  self.assertTrue(gta_theme_match('Lucia','GTA 6 trailer', 'RockstarGames'))
  self.assertFalse(gta_theme_match('Lucia','Lucia is trending'))
  self.assertFalse(gta_theme_match('Jason','Jason is good'))
  self.assertFalse(gta_theme_match('GTA VI','GTA Online weekly updates'))
  self.assertFalse(gta_theme_match('Rockstar','Rockstar Games studio releases a song'))
 def test_context_is_not_endorsement(self):
  t=time.time()
  posts=[{'created_at':t,'author':'RockstarGames','text':'GTA VI release trailer'}]
  found=contextual_matches('Vice City Coin',posts,[],now=t)
  self.assertEqual(found[0]['arcs'],['GTA VI'])
  self.assertFalse(found[0]['direct_contract'])
  self.assertFalse(contextual_matches('Lucia', [{'created_at':t,'author':'random','text':'Lucia'}],[],now=t))
  self.assertTrue(contextual_matches('Lucia',posts,[],now=t))
 def test_news_rss_no_old_rebroadcast(self):
  now=time.time()
  xml=f'<rss><channel><item><title>GTA VI live news</title><pubDate>Mon, 05 Jan 2020 10:00:00 GMT</pubDate></item></channel></rss>'
  self.assertEqual(parse_trends_rss(xml.encode(),'GTA',now=now),[])

class AccountsTests(unittest.TestCase):
 def test_coverage_and_no_password_leak(self):
  d={'success':True,'x':{'accounts':[{'handle':'elonmusk'}]},'custom':{'accounts':['RockstarGames'], 'availableAccounts':[], 'maxAccounts':2},'available':{'accounts':['theunipcs']},'hidden':['cz_binance']}
  result=evaluate_coverage(d)
  self.assertEqual(result['tracked'],2)
  self.assertEqual({r['handle']:r['status'] for r in result['accounts']}['theunipcs'],'available_free')
  self.assertEqual({r['handle']:r['status'] for r in result['accounts']}['cz_binance'],'masked')
  self.assertTrue(result['check_only'])
 def test_credentials_only_in_request_header(self):
  class Response:
   def __enter__(self):return self
   def __exit__(self,*a):return False
   def read(self,n):return json.dumps({'success':True,'x':{'accounts':[]}}).encode()
  def opener(req,timeout=0):
   self.assertEqual(req.full_url,'https://core.j7tracker.io/api/watched-accounts')
   self.assertEqual(req.get_header('Authorization'),'Bearer SESSION_PRIVATE')
   return Response()
  result=fetch_coverage('SESSION_PRIVATE',opener=opener)
  self.assertNotIn('SESSION_PRIVATE',str(result))

class IntegrationTests(unittest.TestCase):
 def test_gta_clones_are_not_claimed_official(self):
  with tempfile.TemporaryDirectory() as tmp:
   st=Store(Path(tmp)/'data.db')
   now=time.time()
   for i in range(6):
    mint=mint_for(i+2)
    st.save_coin({'mint':mint,'name':'Vice City Coin','symbol':'VC','score':20,'status':'risque','last_seen':now,'first_seen':now},now)
   found=st.find_theme_mints('New GTA 6 trailer',limit=3,author='RockstarGames')
   self.assertEqual(len(found),3)
   self.assertEqual(len(set(found)),3)
 def test_rpc_not_blocking_discovery(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Radar(Path(tmp)/'data.db',Path(tmp)/'wallets.txt',limit=2)
   started=threading.Event(); finish=threading.Event()
   def slow_rpc():
    started.set(); finish.wait(timeout=2)
    return set(),[]
   with patch.object(r.wallet_monitor,'scan',side_effect=slow_rpc),\
        patch('radar.engine.providers.discoveries',return_value=({},[])),\
        patch('radar.engine.providers.dex_pairs_batch',return_value={}):
    ts=time.monotonic()
    try:self.assertTrue(r.run_once())
    finally:finish.set()
    self.assertLess(time.monotonic()-ts,1)
    self.assertTrue(started.wait(1))
 def test_official_handle_without_followers_still_triggers_theme_research(self):
  with tempfile.TemporaryDirectory() as tmp:
   st=Store(Path(tmp)/'data.db');now=time.time()
   st.save_coin({'mint':MINT,'name':'Vice City Coin','symbol':'VC','score':20,'status':'risque','last_seen':now,'first_seen':now},now)
   seen=[];feed=J7Feed(st,lambda mint: seen.append(mint),token='DUMMY')
   payload={'id':'1910000000000000000','createdAt':now,'author':{'handle':'RockstarGames'},'text':'GTA VI trailer today'}
   post=feed.ingest(payload)
   self.assertIsNotNone(post)
   self.assertIn(MINT,seen)
   self.assertEqual(st.get(MINT)['status'],'risque')

if __name__=='__main__':unittest.main()

class J7SetupTests(unittest.TestCase):
 def test_free_pool_only_explicit(self):
  import sys
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
  from j7_watchlist import add_free_only
  captured={}
  class Response:
   def __enter__(self):return self
   def __exit__(self,*a):return False
   def read(self,n):return b'{"ok":true,"added":1}'
  def opener(req,timeout=0):
   captured['path']=req.full_url
   captured['data']=json.loads(req.data)
   return Response()
  report={'accounts':[{'handle':'RockstarGames','status':'available_free'},
                      {'handle':'elonmusk','status':'tracked'},
                      {'handle':'zzzz','status':'not_tracked'}]}
  res=add_free_only('test-key',report,opener=opener)
  self.assertEqual(captured['path'],'https://core.j7tracker.io/api/accounts/available')
  self.assertEqual(captured['data'],{'handles':['RockstarGames']})
  self.assertEqual(res['added'],1)
