"""Regression: old tokens beyond the most recent 1000 never steal new slots."""
import json, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
from radar.engine import Radar
from radar.store import Store

OLD='3'+'e'*34
NEW='4'+'f'*34

class DiscoveryRegression(unittest.TestCase):
    def test_all_known_mints_includes_archives_outside_1000_limit(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'state.db')
            now=time.time()
            with st.db() as db:
                for i in range(1200):
                    mint=f'coin_{i}'
                    db.execute('INSERT INTO coins VALUES (?,?,?,?,?,?)',
                               (mint,'X','X',now-1200+i,now-1200+i,json.dumps({'mint':mint,'last_seen':now-1200+i})))
            self.assertEqual(len(st.list_coins(1000)),1000)
            self.assertEqual(len(st.known_mints()),1200)
            self.assertIn('coin_0',st.known_mints())

    def test_discovered_old_not_consumed_as_new(self):
        # With >1000 persisted mints, old and new appear in source discovery.
        # The old mint is in SQLite but excluded from the last-1000 page.
        with tempfile.TemporaryDirectory() as td:
            radar=Radar(Path(td)/'state.db',str(Path(td)/'wallets.txt'),limit=3)
            now=time.time()
            with radar.store.db() as db:
                for i in range(1101):
                    mint=OLD if i==0 else f'mint_{i}'
                    db.execute('INSERT INTO coins VALUES (?,?,?,?,?,?)',
                               (mint,'X','X',now-20000+i,now-20000+i,json.dumps({'mint':mint,'last_seen':now-20000+i,'score':1,'status':'risque','patterns':[]})))
            examined=[]
            def batch(mints):
                examined.extend(mints)
                return {}
            with patch('radar.engine.providers.discoveries',return_value=({OLD:{'gecko_new_pools'},NEW:{'gecko_new_pools'}},[])),\
                 patch.object(radar.wallet_monitor,'scan',return_value=(set(),[])),\
                 patch('radar.engine.providers.dex_pairs_batch',side_effect=batch),\
                 patch('radar.engine.providers.quote_same_pools',return_value=({},[])):
                self.assertTrue(radar.run_once())
            self.assertEqual(radar.status['new_candidates'],1)
            self.assertIn(NEW,examined)
            self.assertEqual(radar.status['known_total'],1101)
            self.assertEqual(radar.status['engine_version'],'v2.0')

if __name__=='__main__':unittest.main()
