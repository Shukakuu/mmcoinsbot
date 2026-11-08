"""v7.2: J7-first hub. Ledger, schema telemetry, non-X contracts, outcome tracking."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from radar.engine import Radar
from radar.fast_lane import FastLane
from radar.j7_hub import HighlightTracker, HORIZONS, MIN_RELIABLE, extract_flags, shape_of, token_meta_info
from radar.social import J7Feed
from radar.store import Store

ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def mint_for(n):
    value = int.from_bytes(bytes([n]) * 32, 'big')
    out = ''
    while value:
        value, r = divmod(value, 58)
        out = ALPHABET[r] + out
    return out


M1, M2, M3 = mint_for(3), mint_for(4), mint_for(5)
POST = '1910000000000000001'


def new_store(tmp):
    return Store(Path(tmp) / 'data.db')


class HelperTests(unittest.TestCase):
    def test_shape_keeps_keys_never_values(self):
        shape = shape_of({'author': {'handle': 'secret-value', 'id': 1}, 'text': 'hello', 'isContractLaunch': True})
        self.assertIn('author.handle', shape)
        self.assertIn('isContractLaunch', shape)
        self.assertNotIn('secret-value', json.dumps(shape))
        self.assertNotIn('hello', json.dumps(shape))

    def test_flags_are_booleans_without_free_text(self):
        flags = extract_flags({'isContractLaunch': 1, 'playSound': False, 'grok': 'long analysis text', 'card': {}, 'x': 1})
        self.assertEqual(flags, {'isContractLaunch': True, 'playSound': False, 'has_grok': True, 'has_card': False})

    def test_token_meta_info_is_defensive(self):
        self.assertEqual(token_meta_info({'tokenMeta': {'name': ' Vice ', 'ticker': 'VC'}}), {'name': 'Vice', 'symbol': 'VC'})
        self.assertEqual(token_meta_info({'tokenMeta': 'broken'}), {'name': '', 'symbol': ''})
        self.assertEqual(token_meta_info(None), {'name': '', 'symbol': ''})


class LedgerTests(unittest.TestCase):
    def test_first_flag_idempotence_and_latency(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            now = 1_800_000_000.0
            a = st.record_highlight(M1, 'token_meta', post_id=POST, author='@Elon', post_at=now - 4.5, now=now)
            self.assertTrue(a['first'])
            again = st.record_highlight(M1, 'token_meta', post_id=POST, author='Elon', post_at=now - 4.5, now=now + 5)
            self.assertFalse(again['first'])
            self.assertEqual(again['id'], a['id'])
            other = st.record_highlight(M1, 'post_ca', post_id=POST, author='Elon', now=now + 6)
            self.assertFalse(other['first'])
            hl = st.first_highlight(M1)
            self.assertEqual((hl['author'], hl['via']), ('Elon', 'token_meta'))
            self.assertAlmostEqual(hl['latency_s'], 4.5)

    def test_invalid_mint_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            self.assertIsNone(st.record_highlight('not-a-mint', 'token_meta'))
            self.assertIsNone(st.first_highlight('not-a-mint'))

    def test_late_enrichment_fills_blank_author_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            now = 1_800_000_000.0
            st.record_highlight(M1, 'token_meta', post_id=POST, now=now)           # token_meta before the tweet
            self.assertEqual(st.enrich_highlights(POST, author='Rock', followers=5_000_000, post_at=now - 3, platform='X'), 1)
            hl = st.first_highlight(M1)
            self.assertEqual((hl['author'], hl['followers']), ('Rock', 5_000_000))
            self.assertAlmostEqual(hl['latency_s'], 3)
            st.enrich_highlights(POST, author='Someone else', post_at=now - 99)      # never overwrites
            self.assertEqual(st.first_highlight(M1)['author'], 'Rock')

    def test_schema_telemetry_is_bounded_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            self.assertTrue(st.record_shape('token_meta', {'id': 1, 'tokenMeta': {'name': 'x'}}))
            self.assertFalse(st.record_shape('token_meta', {'id': 2, 'tokenMeta': {'name': 'y'}}))
            self.assertFalse(st.record_shape('token_meta', 'garbage'))
            report = st.schema_report()
            self.assertEqual(len(report), 1)
            self.assertIn('tokenMeta.name', report[0]['keys'])


class FeedIntegrationTests(unittest.TestCase):
    def feed(self, st):
        woken = []
        return J7Feed(st, lambda mint: woken.append(mint), token='DUMMY'), woken

    def test_token_meta_after_tweet_records_highlight_with_author_and_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            feed, woken = self.feed(st)
            now = time.time()
            feed.ingest({'id': POST, 'createdAt': now - 2, 'author': {'handle': 'RockstarGames', 'followersCount': 9_000_000},
                         'text': 'GTA VI trailer 2'})
            feed.ingest_event('token_meta', {'id': POST, 'mint': M1, 'tokenMeta': {'chain': 'solana', 'name': 'Vice City', 'symbol': 'VICE'}})
            hl = st.first_highlight(M1)
            self.assertEqual((hl['via'], hl['author'], hl['name'], hl['symbol']), ('token_meta', 'RockstarGames', 'Vice City', 'VICE'))
            self.assertLess(hl['latency_s'], 10)
            self.assertIn(M1, woken)
            self.assertTrue(any(s['kind'] == 'token_meta' for s in st.schema_report()))

    def test_token_meta_before_tweet_is_completed_when_tweet_arrives(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            feed, _ = self.feed(st)
            now = time.time()
            feed.ingest_event('token_meta', {'id': POST, 'mint': M1, 'tokenMeta': {'chain': 'solana'}})
            self.assertEqual(st.first_highlight(M1)['author'], '')
            feed.ingest({'id': POST, 'createdAt': now - 1, 'author': {'handle': 'elonmusk', 'followersCount': 200_000_000}, 'text': 'meme'})
            self.assertEqual(st.first_highlight(M1)['author'], 'elonmusk')

    def test_backlog_tweet_never_creates_highlight(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            feed, _ = self.feed(st)
            feed.ingest({'id': POST, 'createdAt': time.time() - 5, 'author': {'handle': 'a_b', 'followersCount': 9},
                         'text': 'CA ' + M1}, backlog=True)
            self.assertIsNone(st.first_highlight(M1))
            feed.ingest_event('token_meta', {'id': POST, 'mint': M1, 'tokenMeta': {}})
            self.assertIsNone(st.first_highlight(M1))   # parent tweet is backlog: latency would be meaningless

    def test_x_post_with_contract_and_reply_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            feed, _ = self.feed(st)
            now = time.time()
            feed.ingest({'id': POST, 'createdAt': now - 1, 'author': {'handle': 'trader', 'followersCount': 60_000},
                         'text': 'new gem ' + M1, 'isContractLaunch': True, 'grok': 'analysis'})
            hl = st.j7_report()['recent'][0]
            self.assertEqual((hl['via'], hl['author']), ('post_ca', 'trader'))
            self.assertTrue(hl['flags']['isContractLaunch'])
            self.assertTrue(hl['flags']['has_grok'])
            feed.ingest({'id': '1910000000000000002', 'createdAt': now - 1, 'author': {'handle': 'spammer', 'followersCount': 10},
                         'text': 'buy ' + M2, 'isReply': True})
            self.assertIsNone(st.first_highlight(M2))   # reply spam is not a J7 highlight

    def test_contract_in_non_x_post_is_now_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            feed, woken = self.feed(st)
            now = time.time()
            item = {'id': 'ts-1', 'platform': 'Truth Social', 'isTruthSocial': True, 'source': 'external', 'createdAt': now - 3,
                    'author': {'handle': 'someone', 'followersCount': 7}, 'text': 'my coin ' + M1, 'isContractLaunch': True}
            feed.ingest_external(item)
            hl = st.first_highlight(M1)
            self.assertEqual((hl['via'], hl['platform'], hl['author']), ('external_ca', 'Truth Social', 'someone'))
            self.assertIn(M1, woken)
            self.assertTrue(any(s['kind'].startswith('external:') for s in st.schema_report()))
            # a stale or backlog post is not a live highlight
            feed.ingest_external({**item, 'id': 'ts-2', 'text': 'old ' + M2, 'createdAt': now - 4000})
            feed.ingest_external({**item, 'id': 'ts-3', 'text': 'bl ' + M3}, backlog=True)
            self.assertIsNone(st.first_highlight(M2))
            self.assertIsNone(st.first_highlight(M3))

    def test_launch_card_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            feed, _ = self.feed(st)
            feed.ingest_external({'id': 'w1', 'isWebhook': True, 'createdAt': time.time(), 'platform': 'webhook',
                                  'webhook': {'handle': 'pumppairs', 'embeds': [{'address': M1}]}})
            self.assertEqual(st.first_highlight(M1)['via'], 'launch_card:pumppairs')


class TrackerTests(unittest.TestCase):
    def tracker(self, st, prices):
        return HighlightTracker(st, threading.Event(), get_pairs=lambda mints: {m: {'priceUsd': str(prices[m])} for m in mints if prices.get(m)})

    def test_reference_then_outcomes_then_missing_never_minus_100(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            t0 = 1_800_000_000.0
            st.record_highlight(M1, 'token_meta', post_id=POST, author='a', post_at=t0 - 2, now=t0)
            prices = {M1: 0.001}
            tr = self.tracker(st, prices)
            tr.tick(t0 + 5)                                   # first quote -> reference, 5 s late
            hl = st.j7_report(now=t0 + 6)['recent'][0]
            self.assertEqual(hl['quoted_lag_s'], 5.0)
            prices[M1] = 0.0012
            tr.tick(t0 + 5 + 61)                              # +60 s observed: +20 %
            prices[M1] = None
            tr.tick(t0 + 5 + 305)                             # +300 s: no quote -> missing, NOT -100 %
            out = st.j7_report(now=t0 + 400)['recent'][0]['outcomes']
            self.assertEqual(out['60'], 20.0)
            self.assertIsNone(out['300'])
            with st.db() as db:
                states = {r['horizon']: r['state'] for r in db.execute('SELECT horizon,state FROM j7_highlight_outcomes')}
            self.assertEqual(states[60], 'observed')
            self.assertNotIn(300, states)  # retry throughout tolerance, then mark missing
            tr.tick(t0 + 5 + 391)
            with st.db() as db:
                state=db.execute('SELECT state FROM j7_highlight_outcomes WHERE horizon=300').fetchone()[0]
            self.assertEqual(state,'missing')

    def test_late_tick_cannot_fill_two_horizons_with_one_quote(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            t0 = 1_800_000_000.0
            st.record_highlight(M1, 'token_meta', post_id=POST, now=t0)
            prices = {M1: 1.0}
            tr = self.tracker(st, prices)
            tr.tick(t0)
            prices[M1] = 2.0
            tr.tick(t0 + 1300)                                # far past +60 and +300, inside +1200 tolerance? no: 1300 > 1290
            with st.db() as db:
                states = {r['horizon']: r['state'] for r in db.execute('SELECT horizon,state FROM j7_highlight_outcomes')}
            self.assertEqual(states[60], 'missing')
            self.assertEqual(states[300], 'missing')
            self.assertEqual(states[1200], 'missing')

    def test_only_first_highlight_of_a_mint_is_tracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            t0 = time.time()
            st.record_highlight(M1, 'token_meta', post_id=POST, now=t0)
            st.record_highlight(M1, 'post_ca', post_id=POST, now=t0)
            self.assertEqual(len(st.tracking_due(t0 + 1)), 1)

    def test_provider_error_does_not_kill_the_loop(self):
        stop = threading.Event()

        def boom(mints):
            stop.set()
            raise RuntimeError('network down')
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            st.record_highlight(M1, 'token_meta', post_id=POST)
            tr = HighlightTracker(st, stop, get_pairs=boom, interval=0)
            tr.run()
            self.assertEqual(tr.status['error'], 'RuntimeError')


class ReportAndProvenanceTests(unittest.TestCase):
    def test_small_samples_are_flagged_not_conclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            t0 = time.time()
            for i in range(3):
                m = mint_for(10 + i)
                r = st.record_highlight(m, 'token_meta', post_id=str(2000 + i), author='trader1', platform='X', post_at=t0 - 1, now=t0)
                st.record_outcome(r['id'], 300, 'observed', t0, 1.0, 10.0 * (i + 1))
            rep = st.j7_report(now=t0 + 5)
            author = rep['authors'][0]
            self.assertEqual((author['key'], author['n'], author['ret_300_n']), ('X / trader1', 3, 3))
            self.assertEqual(author['ret_300_median'], 20.0)
            self.assertFalse(author['ret_300_conclusive'])
            self.assertLess(3, MIN_RELIABLE)
            self.assertIn('témoin', rep['note'])

    def test_fast_lane_keeps_j7_origin_and_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = new_store(tmp)
            st.record_highlight(M1, 'token_meta', post_id=POST, author='elonmusk', name='Doge Dog', symbol='DD')
            lane = FastLane(st, threading.Event())
            self.assertEqual(lane.observe([M1], get_pairs=lambda mints: {}), 1)
            coin = st.get(M1)
            self.assertEqual(coin['status'], 'incomplet')
            self.assertEqual(coin['score'], 0)
            self.assertEqual((coin['symbol'], coin['name']), ('DD', 'Doge Dog'))
            self.assertEqual(coin['j7_origin']['author'], 'elonmusk')

    def test_engine_view_exposes_origin_without_boosting_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            radar = Radar(Path(tmp) / 'data.db', Path(tmp) / 'wallets.txt', limit=2)
            now = time.time()
            radar.store.save_coin({'mint': M1, 'name': 'X', 'symbol': 'X', 'score': 20, 'status': 'surveillance',
                                   'last_seen': now, 'first_seen': now}, now)
            radar.store.record_highlight(M1, 'token_meta', post_id=POST, author='elonmusk')
            coin = radar.view()['coins'][0]
            self.assertEqual(coin['j7']['author'], 'elonmusk')
            self.assertEqual(coin['score'], 20)          # a highlight never changes the score
            self.assertEqual(radar.status['engine_version'], 'v2.0')


if __name__ == '__main__':
    unittest.main()
