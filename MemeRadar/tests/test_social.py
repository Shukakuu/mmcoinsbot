"""Offline regression suite for J7 live tweets and read-only contract matching."""
import tempfile, time, unittest
from pathlib import Path
from unittest.mock import Mock
from radar.social import J7Feed, extract_mints, is_solana_address, normalize_post
from radar.store import Store
from radar.engine import Radar

MINT='6PtLvzA8eY1NwUw1E9h48c7xphRvD6fK2ymDGQY1d1Nd'


def event(id='1990123412341234567', follower=120000, text=None, **patch):
    result={'id':id,'createdAt':int(time.time()*1000), 'type':'TWEET',
            'text':text if text is not None else f'Found this coin! {MINT} $CHAD',
            'author':{'handle':'realtrader','id':'9876543210','followersCount':follower}}
    result.update(patch)
    return result


class SocialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db=Store(str(Path(self.temp.name)/'test.db'))
        self.notifications=[]
        self.feed=J7Feed(self.db,self.notifications.append,token='not_real_test_token')

    def test_validate_solana_not_evm(self):
        self.assertTrue(is_solana_address(MINT))
        self.assertFalse(is_solana_address('0x'+'a'*40))
        self.assertFalse(is_solana_address('invalid0oO'))

    def test_explicit_ca_not_ticker_only(self):
        self.assertEqual(extract_mints(event()),[MINT])
        self.assertEqual(normalize_post(event(text='$CHAD pump now'))['mints'],[])
        self.assertEqual(normalize_post(event(text='$CHAD pump now'))['tickers'],['CHAD'])

    def test_high_follower_new_tweet_triggers_once(self):
        self.feed.ingest(event())
        self.feed.ingest(event())
        self.feed.ingest(event(text=f'longer tweet about the coin {MINT} $CHAD'))
        self.assertEqual(self.notifications,[MINT])
        self.assertEqual(len(self.db.recent_social()),1)

    def test_later_ca_enrichment_wakes_one_scan(self):
        self.feed.ingest(event(text='$CHAD'))
        self.assertEqual(self.notifications,[])
        self.feed.ingest(event(text=f'Added CA {MINT}'))
        self.assertEqual(self.notifications,[MINT])

    def test_backlog_never_triggers_scan_even_after_update(self):
        self.feed.ingest(event(),backlog=True)
        self.feed.ingest(event(text=f'new text with same contract {MINT}'))
        self.assertEqual(self.notifications,[])

    def test_tweet_reposts_do_not_trigger_scan(self):
        self.feed.ingest(event(isRetweet=True))
        self.assertEqual(self.notifications,[])

    def test_small_accounts_visible_but_do_not_wake(self):
        self.feed.ingest(event(follower=120))
        self.assertEqual(self.notifications,[])
        self.assertEqual(self.db.recent_social()[0]['tier'],'standard')

    def test_feed_keeps_rich_fields_on_sparse_update(self):
        self.feed.ingest(event())
        self.feed.ingest(event(text='short',author={'handle':'realtrader'}))
        saved=self.db.recent_social()[0]
        self.assertIn(MINT,saved['text'])
        self.assertEqual(saved['followers'],120000)
        self.assertEqual(saved['mints'],[MINT])

    def test_deletion_excludes_deleted_posts(self):
        self.feed.ingest(event())
        self.db.mark_social_deleted('1990123412341234567')
        self.assertTrue(self.db.recent_social()[0]['deleted'])
        self.assertEqual(self.db.social_for_mint(MINT),[])

    def test_old_tweets_do_not_wake_scanner(self):
        self.feed.ingest(event(createdAt=int((time.time()-600)*1000)))
        self.assertEqual(self.notifications,[])

    def test_mints_reachable_as_new_discovery_without_buying(self):
        self.feed.ingest(event())
        self.assertIn(MINT,self.db.social_mints_recent())
        self.assertEqual(len(self.db.social_for_mint(MINT)),1)

    def test_source_is_not_high_score_bonus(self):
        from radar.scoring import score_token
        from radar.source_scanner import candidate
        # Mathematical source points remain 0 for J7-only discovery.
        import inspect
        code=inspect.getsource(score_token)
        self.assertNotIn("'j7_direct_contract' in sources",code)

    def test_no_token_run_does_not_attempt_network(self):
        feed=J7Feed(self.db,token='')
        feed.run()
        self.assertEqual(feed.report()['state'],'inactive')

    def test_social_wakeup_limited(self):
        radar=Radar(str(Path(self.temp.name)/'radar.db'),str(Path(self.temp.name)/'none.txt'))
        radar.status['last_scan']=time.time()-30
        radar.social_wakeup(MINT)
        self.assertTrue(radar.refresh_event.is_set())
        radar.refresh_event.clear()
        radar.social_wakeup(MINT)
        self.assertFalse(radar.refresh_event.is_set())

    def test_j7_does_not_require_wallet_keys(self):
        feed=J7Feed(self.db,token='fake_token')
        self.assertNotIn('fake_token',repr(feed.report()))

if __name__=='__main__':unittest.main()
