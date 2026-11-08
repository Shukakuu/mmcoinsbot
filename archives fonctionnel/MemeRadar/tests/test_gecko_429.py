"""Offline regression tests for API throttling; never performs live requests."""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from radar import source_scanner as s


class Gecko429Tests(unittest.TestCase):
    def setUp(self):
        with s._PACE_LOCK:
            s._NEXT_ALLOWED.clear()
            s._PAUSED_UNTIL.clear()
            s._RATE_STRIKES.clear()
            s._GECKO_CACHE.clear()

    def test_discovery_is_cached_without_new_http_requests(self):
        url=s.GECKO+'/networks/solana/new_pools?include=base_token,quote_token'
        payload={'data':[],'included':[]}
        with patch.object(s.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(payload).encode())) as mocked:
            self.assertEqual(s.fetch(url),payload)
            self.assertEqual(s.fetch(url),payload)
            self.assertEqual(mocked.call_count,1)
        self.assertEqual(s._gecko_cache_ttl(url),75)
        self.assertEqual(s._gecko_cache_ttl(s.GECKO+'/networks/solana/trending_pools'),180)

    def test_429_cools_down_without_repeated_requests(self):
        url=s.GECKO+'/networks/solana/trending_pools'
        bad=HTTPError(url,429,'Too Many Requests',{},None)
        with patch.object(s.urllib.request,'urlopen',side_effect=bad) as mocked:
            with self.assertRaisesRegex(s.SourceError,'HTTP 429'):
                s.fetch(url)
            with self.assertRaisesRegex(s.SourceError,'reprise dans'):
                s.fetch(url)
            self.assertEqual(mocked.call_count,1)
        with s._PACE_LOCK:
            remain=s._PAUSED_UNTIL['gecko']-s.time.monotonic()
        self.assertGreater(remain,110)
        self.assertLessEqual(remain,120)

    def test_retry_after_longer_than_default_is_honored(self):
        url=s.GECKO+'/networks/solana/new_pools'
        bad=HTTPError(url,429,'Too Many Requests',{'Retry-After':'250'},None)
        with patch.object(s.urllib.request,'urlopen',side_effect=bad):
            with self.assertRaises(s.SourceError): s.fetch(url)
        with s._PACE_LOCK:
            remain=s._PAUSED_UNTIL['gecko']-s.time.monotonic()
        self.assertGreater(remain,249)

    def test_pool_prices_never_enter_the_discovery_cache(self):
        url=s.GECKO+'/networks/solana/pools/multi/'+'A'*32
        self.assertEqual(s._gecko_cache_ttl(url),0)

    def test_dex_stays_unblocked_when_gecko_paused(self):
        bad=HTTPError(s.GECKO+'/networks/solana/new_pools',429,'Rate limited',{},None)
        with patch.object(s.urllib.request,'urlopen',side_effect=bad):
            with self.assertRaises(s.SourceError): s.fetch(bad.url)
        with patch.object(s.urllib.request,'urlopen',return_value=io.BytesIO(b'[]')):
            self.assertEqual(s.fetch(s.DEX+'/token-profiles/latest/v1'),[])

if __name__ == '__main__': unittest.main()
