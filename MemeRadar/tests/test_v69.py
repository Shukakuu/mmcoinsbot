"""Regression tests for experimental curve discovery and unbiased prospective v3."""
import tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
from radar.curve import assess_curve, is_probable_curve
from radar.engine import Radar
from radar.store import Store
from radar.source_scanner import WSOL

M='C'*32
P='D'*32
Q='E'*32
T=1793260000.0


def curve(ts=T, pool=P):
    return {'chainId':'solana','dexId':'pumpfun','pairAddress':pool,'pairCreatedAt':int((ts-90)*1000),
        'baseToken':{'address':M,'symbol':'EARLY','name':'Test early'},
        'quoteToken':{'address':WSOL},'priceUsd':'0.00003','marketCap':13500,
        'volume':{'m5':2200,'h1':3300},'txns':{'m5':{'buys':23,'sells':7},'h1':{'buys':25,'sells':10}},
        'priceChange':{'m5':0.5,'h1':3},'liquidity':None}


def safe():
    return {'mint_active':False,'freeze_active':False,'rugged':False,'top10_pct':None,
        'rugcheck_risk_score':12,'top10_method':'unverified','risk_details':[],
        'lp_locked_by_pool':{}}


class Curves(unittest.TestCase):
    def test_missing_dex_liquidity_is_not_zero_or_hard_risk(self):
        p=curve()
        self.assertTrue(is_probable_curve(p))
        r=assess_curve(p,safe(),{'risks':[]},T)
        self.assertTrue(r['early_candidate'])
        self.assertGreater(r['score'],65)
        self.assertIn('Réserves', ' '.join(r['unknown']))

    def test_curve_without_cap_or_early_trades_does_not_pass(self):
        p=curve();p.pop('marketCap');p['txns']['m5']={'buys':2,'sells':6}
        r=assess_curve(p,safe(),{'risks':[]},T)
        self.assertFalse(r['early_candidate'])

    def test_unknown_security_and_rug_reject_early(self):
        s=safe();s['freeze_active']=None
        self.assertFalse(assess_curve(curve(),s,{'risks':[]},T)['early_candidate'])
        self.assertFalse(assess_curve(curve(),safe(),{'risks':['Rug détecté']},T)['early_candidate'])

    def test_meteora_without_liquidity_is_probable_curve_not_proven(self):
        p=curve();p['dexId']='meteora'
        self.assertTrue(is_probable_curve(p))

    def test_normal_pool_not_mistaken_for_curve(self):
        p=curve();p['liquidity']={'usd':12000}
        self.assertFalse(is_probable_curve(p))

    def test_radar_promotes_early_curve_without_liquidity_but_disables_eligible(self):
        with tempfile.TemporaryDirectory() as temp:
            radar=Radar(Path(temp)/'db.sqlite', '/missing', limit=2)
            p=curve(time.time())
            with patch('radar.engine.providers.discoveries',return_value=({M:{'gecko_new_pools'}},[])),\
                 patch.object(radar.wallet_monitor,'scan',return_value=(set(),[])),\
                 patch('radar.engine.providers.dex_pairs_batch',return_value={M:p}),\
                 patch('radar.engine.providers.quote_same_pools',return_value=({},[])),\
                 patch('radar.engine.providers.rug_report',return_value=safe()):
                self.assertTrue(radar.run_once())
            c=radar.store.get(M)
            self.assertEqual(c['status'],'a_etudier')
            self.assertEqual(c['score_method'],'curve_experimentale')
            self.assertIsNone(c['liquidity_usd'])
            self.assertFalse(c['eligible'])
            self.assertTrue(c['curve_candidate'])


class Research(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db.sqlite')

    def event(self,kind='alert',at=T):
        c={'mint':M,'pair_address':P,'price_usd':1,'status':'a_etudier' if kind=='alert' else 'surveillance',
           'curve_candidate':kind=='alert','prewatch':kind=='alert','pre_impulse':False,
           'risks':[],'coverage':90,'score':76,'score_method':'curve_experimentale',
           'age_min':2,'market_cap_usd':13500,'safety_summary':{'mint_active':False,'freeze_active':False,'rugcheck_score':12}}
        self.store.record_v3(c,{},at)

    def test_migrated_mint_produces_a_valid_return(self):
        self.event()
        self.store.observation_v3(M,Q,3,T+300)
        rep=self.store.report_v3(T+500)
        groups=[g for g in rep['groups'] if g['signal']=='a_etudier' and g['minutes']==5]
        self.assertEqual(groups[0]['observed_median'],200)
        self.assertEqual(groups[0]['migrations'],1)

    def test_disjoint_windows_one_quote_cannot_populate_two(self):
        self.event()
        self.store.observation_v3(M,P,1.5,T+600)
        out=self.store.research_for_v3(M)['events']
        alert=next(e for e in out if e['kind']=='a_etudier')
        self.assertEqual([e['horizon'] for e in alert['outcomes']],[600])

    def test_offline_missing_censored_not_auto_loss(self):
        self.event()
        rep=self.store.report_v3(T+500)
        g=next(g for g in rep['groups'] if g['signal']=='a_etudier' and g['minutes']==5)
        self.assertEqual(g['offline'],1)
        self.assertIsNone(g['observed_median'])
        self.assertIsNone(g['positive_rate_ci95'])

    def test_online_no_quote_separate_from_offline(self):
        self.event()
        self.store.heartbeat_v3(T+300)
        rep=self.store.report_v3(T+500)
        g=next(g for g in rep['groups'] if g['signal']=='a_etudier' and g['minutes']==5)
        self.assertEqual(g['unquoted'],1)
        self.assertEqual(g['offline'],0)

    def test_risky_cannot_enter_control_cohort(self):
        self.event('control')
        self.assertTrue(any(e['cohort']=='control' for e in self.store.research_for_v3(M)['events']))
        bad={'mint':'F'*32,'pair_address':P,'price_usd':1,'status':'surveillance','coverage':99,
             'risks':['mint active'],'safety_summary':{'mint_active':True,'freeze_active':False,'rugcheck_score':10}}
        self.store.record_v3(bad,{},T)
        self.assertEqual(self.store.research_for_v3('F'*32)['events'],[])

if __name__=='__main__':unittest.main()
