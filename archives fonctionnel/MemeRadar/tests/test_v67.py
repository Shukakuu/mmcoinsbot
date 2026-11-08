"""Forward-only evidence: a pump must not be required for 'review' status."""
import sys, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from radar.prebreakout import prebreakout, market_snapshot, pressure_reading
from radar.scoring import score_token
from radar.store import Store
from radar.engine import Radar
from test_memeradar import pair, safe, MINT, PAIR


def flat_pair():
    p=pair(age=8000,liquidity=30000,buys=140,sells=50,change=0.2)
    p['txns']['m5']={'buys':65,'sells':21}
    p['volume']['m5']=7000
    p['priceChange']['h1']=1.2
    return p


def report(p,now):
    return score_token(p,safe(),{'pair_address':PAIR,'price':.001,'buyers_h1':30},
        {'dex_profiles'},[],now)

class PreImpulseTests(unittest.TestCase):
    def setUp(self):
        self.t=time.time()
        self.p=flat_pair()
    def pre(self,previous=None,changed=None,sv=None):
        p=changed or self.p; sf=sv or safe()
        return prebreakout(p,previous or [],score_token(p,sf,{}, {'dex_profiles'},[],self.t),sf,self.t)
    def test_no_single_snapshot_promotes_token(self):
        d=self.pre()
        self.assertTrue(d['prewatch'])
        self.assertFalse(d['confirmed'])
    def test_confirmed_at_flat_price_before_pump(self):
        earlier=market_snapshot(self.p,self.t-70)
        d=self.pre([earlier])
        self.assertTrue(d['confirmed'])
        self.assertEqual(d['buy_share'],round(65/86,3))
        self.assertLess(self.p['priceChange']['m5'],1.0)
    def test_historic_momentum_does_not_create_false_preimpulse(self):
        old=market_snapshot(self.p,self.t-70)
        pumped=flat_pair();pumped['priceChange']['m5']=22
        self.assertFalse(self.pre([old],pumped)['confirmed'])
    def test_no_old_pool_cross_confirmation(self):
        old=market_snapshot(self.p,self.t-70);old['pool']='Z'*32
        self.assertFalse(self.pre([old])['confirmed'])
    def test_one_second_repeat_is_not_confirmation(self):
        old=market_snapshot(self.p,self.t-1)
        self.assertFalse(self.pre([old])['confirmed'])
    def test_not_confirmed_after_9_minute_gap(self):
        old=market_snapshot(self.p,self.t-550)
        self.assertFalse(self.pre([old])['confirmed'])
    def test_rejects_wash_like_micro_volume(self):
        low=flat_pair();low['volume']['m5']=500
        self.assertFalse(pressure_reading(market_snapshot(low,self.t)))
    def test_not_a_trading_signal_when_safety_fails(self):
        sf=safe();sf['mint_active']=True
        self.assertFalse(self.pre([market_snapshot(self.p,self.t-70)],sv=sf)['prewatch'])
    def test_missing_5m_transactions_not_guess_from_h1(self):
        p=flat_pair();p['txns'].pop('m5')
        self.assertFalse(self.pre([market_snapshot(self.p,self.t-70)],p)['prewatch'])
    def test_storage_snapshots_survive_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.db'; store=Store(path)
            store.save_market_snapshot(MINT,market_snapshot(self.p,self.t-70))
            self.assertEqual(Store(path).market_snapshots(MINT)[0]['pool'],PAIR)
    def test_engine_promotes_before_price_spike(self):
        with tempfile.TemporaryDirectory() as d:
            radar=Radar(Path(d)/'test.db',Path(d)/'no-wallets.txt',limit=14)
            p=flat_pair()
            # Stored prior market measurement; no synthetic future price, no pump.
            old=market_snapshot(p,time.time()-80)
            radar.store.save_market_snapshot(MINT,old)
            with (patch('radar.engine.providers.discoveries',return_value=({MINT:{'dex_profiles'}},[])),
                  patch.object(radar.wallet_monitor,'scan',return_value=(set(),[])),
                  patch('radar.engine.providers.dex_pairs_batch',return_value={MINT:p}),
                  patch('radar.engine.providers.quote_same_pools',return_value=({MINT:{'pair_address':PAIR,'price':.001}},[])),
                  patch('radar.engine.providers.rug_report',return_value=safe())):
                self.assertTrue(radar.run_once())
            c=radar.store.get(MINT)
            self.assertTrue(c['pre_impulse'])
            self.assertEqual(c['status'],'a_etudier')
            self.assertLess(c['change_m5_pct'],1.0)
            self.assertEqual(c['pressure_buys_m5'],65)

if __name__=='__main__':unittest.main()
