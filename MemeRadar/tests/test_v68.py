"""Regression tests focused on risk and forward-only signals, not trading returns."""
import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from radar.source_scanner import rugcheck
from radar.scoring import score_token
from radar.prebreakout import prebreakout,market_snapshot
from radar.store import Store
from test_memeradar import pair,safe,PAIR,MINT,NOW

class SafeRankingTests(unittest.TestCase):
    def test_pool_and_curve_excluded_only_with_evidence(self):
        user_holders=[{'address':chr(65+i)*32,'owner':chr(65+i)*32,'pct':1.0} for i in range(12)]
        response={'risks':[{'name':'Top 10 holders high ownership','level':'danger'}],
                 'token':{'mintAuthority':None,'freezeAuthority':None},'score_normalised':99,
                 'topHolders':[{'address':'Z'*32,'owner':'Q'*32,'pct':80.0}]+user_holders,
                 'markets':[{'liquidityA':'Z'*32,'liquidityB':'Y'*32}],
                 'knownAccounts':{},'rugged':False}
        sf=rugcheck(MINT,get=lambda _:response)
        self.assertEqual(sf['top10_raw_pct'],89)
        self.assertEqual(sf['top10_pct'],10)
        self.assertEqual(sf['holder_exclusions'][0]['reason'],'market_reserve')
        r=score_token(pair(),sf,{},set(),[],NOW)
        self.assertNotEqual(r['status'],'risque')
        self.assertTrue(any('détenteurs' in x for x in r['unknown']))
    def test_unknown_reserves_never_guessed(self):
        holders=[{'address':str(i)*32,'owner':'A'*32,'pct':9} for i in range(10)]
        sf=rugcheck(MINT,get=lambda _: {'risks':[], 'token':{'mintAuthority':None,'freezeAuthority':None},
             'score_normalised':90,'topHolders':holders})
        self.assertEqual(sf['top10_raw_pct'],90)
        self.assertEqual(sf['top10_pct'],90) # Unrecognized holders remain suspicious, but not a hard veto.
        self.assertNotEqual(score_token(pair(),sf,{},set(),[],NOW)['status'],'risque')
    def test_gecko_gap_is_not_fraud_proof(self):
        s=score_token(pair(),safe(),{'pair_address':PAIR,'price':.0018},set(),[],NOW)
        self.assertNotEqual(s['status'],'risque')
        self.assertTrue(any('latence' in x for x in s['unknown']))
    def test_critical_mint_and_no_liquidity_still_block(self):
        sf=safe();sf['mint_active']=True
        self.assertEqual(score_token(pair(),sf,{},set(),[],NOW)['status'],'risque')
        self.assertEqual(score_token(pair(liquidity=0),safe(),{},set(),[],NOW)['status'],'risque')

class EarlySignals(unittest.TestCase):
    def setUp(self):
        self.now=time.time()
        self.p=pair(age=4,liquidity=30000,change=.2)
        self.p['txns']['m5']={'buys':65,'sells':21}
        self.p['volume']['m5']=6000
        self.p['priceChange']['h1']=1.2
        self.sf=safe()
    def run_signal(self,earlier):
        report=score_token(self.p,self.sf,{},set(),[],self.now)
        return prebreakout(self.p,[market_snapshot(self.p,self.now-earlier)],report,self.sf,self.now)
    def test_no_overlapping_5m_confirmation(self):
        self.assertFalse(self.run_signal(70)['confirmed'])
        self.assertTrue(self.run_signal(70)['prewatch'])
    def test_non_overlap_is_confirmation_not_proof_of_unique_buyers(self):
        self.assertTrue(self.run_signal(330)['confirmed'])
    def test_unknown_holders_do_not_block_early_pressure(self):
        self.sf['top10_pct']=None
        self.assertTrue(self.run_signal(330)['confirmed'])
    def test_rugged_still_blocks(self):
        self.sf['rugged']=True
        self.assertFalse(self.run_signal(330)['prewatch'])

class ProspectiveTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.store=Store(Path(t.name)/'test.db')
    def record(self,ts,kind='alert',p=1.0):
        c={'mint':MINT,'pair_address':PAIR,'price_usd':p,'status':'a_etudier' if kind=='alert' else 'surveillance',
           'age_min':2,'liquidity_usd':20000,'score':65,'prewatch':kind=='alert','pre_impulse':False,'risks':[]}
        self.store.record_research_event(c,{},ts)
    def test_alert_anchor_not_initial_coin_price(self):
        self.record(1000,p=2)
        self.store.observation_v2(MINT,PAIR,4,20000,1600)
        rep=self.store.research_report_v2(1901)
        row=[r for r in rep['groups'] if r['signal']=='a_etudier' and r['minutes']==10][0]
        self.assertEqual(row['observed_median'],100)
    def test_future_never_fills_old_window(self):
        self.record(1000)
        self.store.observation_v2(MINT,PAIR,9,20000,2100)
        rows=[r for r in self.store.research_report_v2(2100)['groups'] if r['minutes']==10 and r['signal']=='a_etudier']
        self.assertEqual(rows[0]['missing'],1)
    def test_different_pool_never_used_as_recovery(self):
        self.record(1000)
        self.store.observation_v2(MINT,'Y'*32,99,900000,1600)
        row=[r for r in self.store.research_report_v2(1901)['groups'] if r['minutes']==10 and r['signal']=='a_etudier'][0]
        self.assertEqual(row['n_observed'],0)
    def test_explicit_zero_liquidity_counts_pessimistic_100_loss(self):
        self.record(1000)
        self.store.observation_v2(MINT,PAIR,.7,0,1600)
        row=[r for r in self.store.research_report_v2(1901)['groups'] if r['minutes']==10 and r['signal']=='a_etudier'][0]
        self.assertEqual(row['illiquid'],1)
        self.assertEqual(row['pessimistic_median'],-100)
    def test_quote_unavailable_does_not_automatically_mean_rug(self):
        self.record(1000)
        self.store.observation_v2(MINT,None,None,None,1600)
        row=[r for r in self.store.research_report_v2(1901)['groups'] if r['minutes']==10 and r['signal']=='a_etudier'][0]
        self.assertEqual(row['illiquid'],0)
        self.assertEqual(row['missing'],1)
    def test_enough_time_for_prospective_five_minute_alert(self):
        self.record(1000)
        self.assertIn(MINT,self.store.evaluation_due_v2(now=1280))
    def test_control_cohort_observation(self):
        self.record(1000,'control')
        r=self.store.research_report_v2(1901)
        self.assertTrue(any(g['cohort']=='control' for g in r['groups']))

if __name__=='__main__':unittest.main()
