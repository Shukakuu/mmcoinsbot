import copy
from datetime import datetime, timezone
from email.utils import format_datetime
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from unittest.mock import patch
from main import make_handler
from radar.engine import Radar
from radar.store import Store
from radar.strategies import assess, enforce_gate
from radar.world_watch import parse_feed, social_events, link_events, emerging, WorldMonitor, build_report, search_tokens
from radar.narrative_graph import discover_terms, topic_graph
from radar.event_calendar import date_hints

NOW = 1800000000
MINT = '69d6eAnot869mAuaDZqyF8qqDmXKQZqfhmDCyfQDapFp'


def coin():
    return {'mint': MINT, 'name': 'Nebulax', 'symbol': 'NEBULAX', 'status': 'a_etudier',
            'market_quote_at': NOW, 'safety_checked_at': NOW, 'price_usd': 1,
            'age_min': 60, 'liquidity_usd': 100000, 'change_m5_pct': 5, 'change_h1_pct': 12,
            'pressure_buys_m5': 20, 'pressure_sells_m5': 10, 'buys_h1': 100, 'sells_h1': 40,
            'eligible': True, 'risks': [], 'safety_summary': {'mint_active': False,
            'freeze_active': False, 'top10_pct': 20, 'rugcheck_score': 0, 'lp_locked_pct': 100,
            'top10_method': 'excluded_verified_protocol_accounts'}}


def event(title='Nebulax launch announced', stamp=NOW-10, source='BBC'):
    date = format_datetime(datetime.fromtimestamp(stamp, timezone.utc))
    raw = f'<rss><channel><item><title>{title}</title><link>https://example.org/{stamp}</link><pubDate>{date}</pubDate></item></channel></rss>'
    return parse_feed(raw.encode(), source, NOW)[0]


class Strategies(unittest.TestCase):
    def test_fast_and_trend_separate(self):
        result = assess(coin(), now=NOW)['strategies']
        self.assertEqual(result[0]['state'], 'review')
        self.assertEqual(result[1]['state'], 'watch')
        self.assertEqual(result[2]['state'], 'watch')

    def test_rug_overrides_every_horizon(self):
        c = coin(); c['safety_summary']['rugged'] = True
        self.assertTrue(all(s['state']=='blocked' for s in assess(c, now=NOW)['strategies']))

    def test_trend_needs_event_within_six_hours(self):
        links=[{'source':'BBC','published_at':NOW-86400}]
        self.assertEqual(assess(coin(),links,NOW)['strategies'][1]['state'],'watch')
        links[0]['published_at']=NOW-10
        self.assertEqual(assess(coin(),links,NOW)['strategies'][1]['state'],'review')

    def test_unknown_is_never_safe(self):
        c = coin(); c['safety_summary']['freeze_active'] = None
        self.assertEqual(assess(c, now=NOW)['risk']['state'], 'unverified')

    def test_stale_and_future_quotes(self):
        for stamp in (NOW-400, NOW+1, None):
            c=coin();c['market_quote_at']=stamp
            self.assertNotEqual(assess(c,now=NOW)['strategies'][0]['state'],'review')

    def test_old_safety_does_not_refresh_with_price(self):
        c=coin();c['safety_checked_at']=NOW-901
        self.assertEqual(assess(c,now=NOW)['risk']['state'],'unverified')

    def test_severe_concentration_and_lp_veto(self):
        for field,value in [('top10_pct',56),('lp_locked_pct',30),('mint_active',True),
                            ('rugcheck_risks_at_quote',[{'level':'danger','name':'holder concentration'}])]:
            c=coin();c['safety_summary'][field]=value
            self.assertEqual(assess(c,now=NOW)['risk']['state'],'blocked')

    def test_onchain_launch_wallet_veto_but_raw_pool_not_insider(self):
        c=coin();c['onchain_risk']={'raw_top10_pct':99,'launch_wallet_pct':None}
        self.assertEqual(assess(c,now=NOW)['risk']['state'],'reviewable')
        c['onchain_risk']['launch_wallet_pct']=21
        self.assertEqual(assess(c,now=NOW)['risk']['state'],'blocked')

    def test_nonfinite_data_never_qualifies(self):
        for field in ('liquidity_usd','price_usd','market_quote_at','age_min'):
            c=coin();c[field]=float('nan')
            self.assertNotEqual(assess(c,now=NOW)['strategies'][0]['state'],'review')

    def test_legacy_veto(self):
        c=coin();c['safety_summary']['top10_pct']=70
        enforce_gate(c,NOW)
        self.assertEqual(c['status'],'risque');self.assertFalse(c['eligible'])

    def test_growth_requires_real_history_and_diverse_persistent_events(self):
        c=coin();c['age_min']=3000
        links=[{'source':'BBC','published_at':NOW-90000},{'source':'Guardian','published_at':NOW-10}]
        self.assertEqual(assess(c,links,NOW)['strategies'][2]['state'],'watch')
        c['strategy_history']=[{'observed_at':NOW-90000+i*7200,'price':1,'liquidity':80000,'top10':25} for i in range(13)]
        self.assertEqual(assess(c,links,NOW)['strategies'][2]['state'],'review')
        c['liquidity_usd']=60000
        self.assertEqual(assess(c,links,NOW)['strategies'][2]['state'],'watch')


class World(unittest.TestCase):
    def test_mixed_case_new_entities_not_predefined(self):
        self.assertIn('SPACEFORGE', [t['term'] for t in discover_terms('SpaceForge launches a rocket')])

    def test_topic_search_rejects_other_chains_and_unrelated_tokens(self):
        pairs=[{'chainId':'ethereum','baseToken':{'address':MINT,'name':'Nebulax'}},
               {'chainId':'solana','baseToken':{'address':MINT,'name':'Unrelated'}},
               {'chainId':'solana','baseToken':{'address':MINT,'name':'Nebulax'}}]
        self.assertEqual(search_tokens('NEBULAX',lambda url:{'pairs':pairs}),[MINT])

    def test_graph_retains_provenance(self):
        graph=topic_graph([event('Nebulax rocket'),event('Nebulax satellite',stamp=NOW-20)])
        item=next(g for g in graph if g['term']=='NEBULAX')
        self.assertEqual(item['event_count'],2);self.assertEqual(item['sources'],['BBC'])

    def test_dynamic_topic_and_exact_contract_are_distinct(self):
        links=link_events(coin(),[event(),event(MINT)])
        self.assertEqual([x['relation'] for x in links],['thematic_hypothesis','contract_mention'])
        self.assertTrue(all(not x['affiliation_verified'] for x in links))

    def test_no_substring_contract_match(self):
        self.assertEqual(link_events(coin(),[event('X'+MINT+'X')]),[])

    def test_feed_rejects_missing_dates_entities_and_oversize(self):
        self.assertEqual(parse_feed(b'<rss><item><title>News</title></item></rss>','x',NOW),[])
        for raw in (b'<!DOCTYPE rss><rss/>',b'x'*1000001):
            with self.assertRaises(ValueError):parse_feed(raw,'x',NOW)

    def test_old_and_future_feed_dates_rejected(self):
        for stamp in (NOW+600,NOW-8*86400):
            with self.assertRaises(IndexError):event(stamp=stamp)

    def test_social_backlog_reposts_deleted_not_new_signals(self):
        posts=[{'id':str(i),'text':'Nebulax','created_at':NOW-1,flag:True} for i,flag in enumerate(('deleted','is_backlog','is_repost','is_reply'))]
        self.assertEqual(social_events(posts,NOW),[])

    def test_emergence_needs_multiple_sources_and_no_duplicate_titles(self):
        events=[event('Nebulax announces rocket',source='BBC'),event('Nebulax launches satellite',source='Guardian'),event('Nebulax unveils capsule',source='J7 @someone')]
        self.assertTrue(next(x for x in emerging(events,NOW) if x['term']=='NEBULAX')['emerging'])
        self.assertFalse(emerging([events[0]]*5,NOW)[0]['emerging'])

    def test_calendar_explicit_date_and_context_only(self):
        date=datetime.fromtimestamp(NOW+86400,timezone.utc).date().isoformat()
        self.assertEqual(date_hints('Launch scheduled '+date,NOW),[date])
        self.assertEqual(date_hints('Market prices '+date,NOW),[])
        self.assertEqual(date_hints('Launch 2027-99-99',NOW),[])


class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'radar.db')

    def test_dedup_preserves_first_reception(self):
        e=event();self.assertEqual(len(self.store.save_world_events([e],NOW)),1)
        e['received_at']+=100
        self.assertEqual(self.store.save_world_events([e],NOW),[])
        self.assertEqual(self.store.world_events(NOW)[0]['received_at'],NOW)

    def test_source_failure_does_not_stop_other_feeds(self):
        date=format_datetime(datetime.now(timezone.utc))
        raw=f'<rss><item><title>Nebulax</title><pubDate>{date}</pubDate></item></rss>'.encode()
        def fetch(url):
            if url=='bad':raise TimeoutError()
            return raw
        monitor=WorldMonitor(self.store,threading.Event(),fetch,search=lambda term:[])
        with patch('radar.world_watch.SOURCES',[('bad','bad'),('good','good')]):monitor.update()
        self.assertEqual(monitor.status['sources']['bad']['error'],'TimeoutError')
        self.assertEqual(monitor.status['sources']['good']['items'],1)

    def test_history_and_cached_safety_keep_original_time(self):
        c=coin();self.store.save_strategy_sample(c,NOW)
        self.store.save_strategy_sample(c,NOW+1)
        self.assertEqual(len(self.store.strategy_histories([MINT],NOW+1)[MINT]),1)
        self.store.save_safety(MINT,{'top10_method':'unverified'})
        first=self.store.cached_safety(MINT)['_checked_at']
        self.assertEqual(self.store.cached_safety(MINT)['_checked_at'],first)

    def test_onchain_risk_attached(self):
        self.store.record_live_risk(MINT,{'launch_wallet_pct':30},NOW)
        self.assertEqual(self.store.observed_risks([MINT])[MINT]['launch_wallet_pct'],30)

    def test_live_and_demo_routes(self):
        radar=Radar(self.store.path,Path(self.tmp.name)/'wallets.txt')
        for demo in (False,True):
            server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(radar,demo))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                url='http://127.0.0.1:'+str(server.server_port)
                with urlopen(url+'/api/v2') as response:data=json.load(response)
                self.assertTrue(data['manual_only']);self.assertEqual(data['demo'],demo)
                with urlopen(url+'/v2.js') as response:self.assertEqual(response.status,200)
            finally:server.shutdown();server.server_close();thread.join()

    def test_restart_keeps_news_and_history(self):
        self.store.save_world_events([event()],NOW)
        self.store.save_strategy_sample(coin(),NOW)
        other=Store(self.store.path)
        self.assertEqual(len(other.world_events(NOW)),1)
        self.assertEqual(len(other.strategy_histories([MINT],NOW)[MINT]),1)
