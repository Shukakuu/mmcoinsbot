"""Regression cases extracted from the conversation-to-code audit."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from test_product_v2 import coin, event, NOW, MINT
from radar.engine import Radar
from radar.store import Store
from radar.world_intel import WorldIntel, context_for_token
from radar.world_watch import parse_feed, emerging, social_events, link_events
from radar.security_gate import risk_gate
from radar.decision_engine import apply_decision, assess
from radar import strategy_fast, strategy_trend, strategy_growth
from main import make_handler


class Alignment(unittest.TestCase):
    def test_all_three_strategy_modules_are_executed(self):
        with patch.object(strategy_fast,'evaluate',return_value=['fast']) as fast, \
             patch.object(strategy_trend,'evaluate',return_value=['trend']) as trend, \
             patch.object(strategy_growth,'evaluate',return_value=['growth']) as growth:
            result=assess(coin(),now=NOW)
        self.assertEqual([x['reasons'] for x in result['strategies']],[['fast'],['trend'],['growth']])
        self.assertEqual([fast.call_count,trend.call_count,growth.call_count],[1,1,1])

    def test_high_legacy_score_cannot_override_strategy_failure(self):
        c=coin();c.update(score=100,liquidity_usd=6000,eligible=True)
        apply_decision(c,now=NOW)
        self.assertFalse(c['eligible']);self.assertEqual(c['status'],'surveillance')

    def test_low_legacy_score_does_not_hide_valid_fast_observation(self):
        c=coin();c.update(score=0,eligible=False)
        apply_decision(c,now=NOW)
        self.assertTrue(c['eligible']);self.assertEqual(c['status'],'a_etudier')

    def test_old_quote_revokes_eligibility(self):
        c=coin();c['market_quote_at']=NOW-400
        apply_decision(c,now=NOW)
        self.assertFalse(c['eligible'])

    def test_invalid_percentages_are_unknown(self):
        for key,value in [('lp_locked_pct',110),('top10_pct',-3)]:
            c=coin();c['safety_summary'][key]=value
            self.assertEqual(risk_gate(c,NOW)['state'],'unverified')

    def test_severe_unqualified_provider_alert_blocks(self):
        c=coin();c['safety_summary']['rugcheck_risk_levels']=['danger']
        self.assertEqual(risk_gate(c,NOW)['state'],'blocked')

    def test_bbc_sections_are_one_voice(self):
        events=[event('Nebulax rocket',source='BBC World'),event('Nebulax satellite',source='BBC Technology'),event('Nebulax science',source='BBC Science')]
        group=next(x for x in emerging(events,NOW) if x['term']=='NEBULAX')
        self.assertEqual(group['sources'],['BBC']);self.assertFalse(group['emerging'])

    def test_zero_new_mentions_is_visible_decline(self):
        group=emerging([event(stamp=NOW-4000)],NOW)[0]
        self.assertEqual(group['phase'],'decline');self.assertEqual(group['current'],0)

    def test_atom_feed_with_alternate_link(self):
        raw=b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Nebulax launch</title>
        <published>2027-01-15T08:00:00Z</published><link rel="self" href="https://example.org/feed"/>
        <link rel="alternate" href="https://example.org/story"/></entry></feed>'''
        from datetime import datetime,timezone
        now=datetime(2027,1,15,9,tzinfo=timezone.utc).timestamp()
        events=parse_feed(raw,'publisher',now)
        self.assertEqual(len(events),1);self.assertEqual(events[0]['url'],'https://example.org/story')

    def test_j7_metadata_contract_is_not_lost(self):
        events=social_events([{'id':'12345678','created_at':NOW-1,'text':'An announcement','mints':[MINT]}],NOW)
        links=link_events(coin(),events)
        self.assertEqual(links[0]['relation'],'contract_mention')


class AlignmentIntegration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'audit.db')

    def test_social_refresh_does_not_refetch_rss_or_exceed_search_budget(self):
        fetch_calls=[];search_calls=[]
        def fetch(url):fetch_calls.append(url);return b'<rss/>'
        def search(term):search_calls.append(term);return []
        monitor=WorldIntel(self.store,threading.Event(),sources={'BBC':'https://example.org/rss'},fetch=fetch,search=search)
        post={'id':'12345678','created_at':NOW,'text':'Nebulax SpaceForge mission'}
        with patch.object(self.store,'recent_social',return_value=[post]) as social:
            with patch('radar.world_watch.time.time',return_value=NOW):monitor.update()
            first_searches=len(search_calls)
            with patch('radar.world_watch.time.time',return_value=NOW+30):monitor.update()
            self.assertEqual(len(fetch_calls),1);self.assertEqual(len(search_calls),first_searches)
            self.assertEqual(social.call_count,2)
            with patch('radar.world_watch.time.time',return_value=NOW+301):monitor.update()
        self.assertEqual(len(fetch_calls),2)

    def test_world_api_and_context_query(self):
        self.store.save_world_events([event()],NOW)
        links=context_for_token(self.store,MINT,'Nebulax',now=NOW)
        self.assertEqual(links[0]['relation'],'thematic_hypothesis')
        radar=Radar(self.store.path,Path(self.temp.name)/'wallets.txt')
        monitor=WorldIntel(self.store,threading.Event(),sources={})
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(radar,world=monitor))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with urlopen('http://127.0.0.1:'+str(server.server_port)+'/api/world') as response:
                payload=json.load(response)
            self.assertTrue(payload['manual_only']);self.assertIn('upcoming',payload)
        finally:server.shutdown();server.server_close();thread.join()

    def test_view_uses_actual_strategy_decision(self):
        c=coin();c.update(score=100,liquidity_usd=6000)
        self.store.save_coin(c,NOW)
        radar=Radar(self.store.path,Path(self.temp.name)/'wallets.txt')
        row=radar.view(now=NOW)['coins'][0]
        self.assertEqual(row['decision_method'],'v2_strategies_manual_only')
        self.assertFalse(row['eligible']);self.assertEqual(row['status'],'surveillance')

    def test_view_and_v2_report_share_decisions(self):
        from radar.world_watch import build_report
        self.store.save_coin(coin(),NOW)
        radar=Radar(self.store.path,Path(self.temp.name)/'wallets.txt')
        rows=radar.view(now=NOW)['coins']
        payload=build_report(rows,[],NOW)
        self.assertEqual(rows[0]['strategy_decisions'],payload['coins'][0]['strategies'])

    def test_historical_alert_retains_decision_evidence(self):
        c=coin();c['analysis_version']='v2.0'
        apply_decision(c,now=NOW)
        self.store.record_v3(c,{},NOW)
        with self.store.read_db() as db:
            row=db.execute('SELECT payload_json FROM research_v3_events').fetchone()
        saved=json.loads(row[0])
        self.assertEqual(saved['decision_method'],'v2_strategies_manual_only')
        self.assertEqual(len(saved['strategy_decisions']),3)
        self.assertIn('security_gate',saved)
