"""v6.9.4: prealert != recommendation, news matching != CA attribution."""
import tempfile, time, unittest, threading
from pathlib import Path
from unittest.mock import patch
from radar.early_watch import observe_early
from radar.narratives import contextual_matches, parse_trends_rss, topic_name, TrendsMonitor
from radar.store import Store
from radar.engine import Radar
from radar.source_scanner import WSOL

M='C'*32
P='D'*32

def pair():
    return {'chainId':'solana','dexId':'pumpfun','pairAddress':P,
            'pairCreatedAt':int((time.time()-20)*1000),
            'baseToken':{'address':M,'name':'OpenAI','symbol':'OPENAI'},
            'quoteToken':{'address':WSOL},'priceUsd':'0.000013',
            'marketCap':4000,'liquidity':None,
            'volume':{'m5':130,'h1':130},
            'txns':{'m5':{'buys':6,'sells':2},'h1':{'buys':6,'sells':2}},
            'priceChange':{'m5':3}}

class Early(unittest.TestCase):
    def test_early_new_curve_without_rugcheck(self):
        r=observe_early(pair(),{}, {'risks':[]}, time.time())
        self.assertIsNotNone(r)
        self.assertFalse(r['safety_verified'])

    def test_known_rug_must_never_early_watch(self):
        self.assertIsNone(observe_early(pair(),{'rugged':True},{'risks':[]},time.time()))
        self.assertIsNone(observe_early(pair(),{'mint_active':True},{'risks':[]},time.time()))
        self.assertIsNone(observe_early(pair(),{}, {'risks':['Rug détecté']},time.time()))

    def test_fomo_not_early_watch(self):
        p=pair();p['priceChange']['m5']=90
        self.assertIsNone(observe_early(p,{}, {'risks':[]}, time.time()))

    def test_no_trade_without_price_not_early_watch(self):
        p=pair();p.pop('priceUsd')
        self.assertIsNone(observe_early(p,{}, {'risks':[]}, time.time()))

    def test_radar_status_surveillance_not_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            radar=Radar(Path(tmp)/'radar.db','/missing',limit=1)
            with patch('radar.engine.providers.discoveries',return_value=({M:{'gecko_new_pools'}},[])),\
                 patch.object(radar.wallet_monitor,'scan',return_value=(set(),[])),\
                 patch('radar.engine.providers.dex_pairs_batch',return_value={M:pair()}),\
                 patch('radar.engine.providers.quote_same_pools',return_value=({},[])),\
                 patch('radar.engine.providers.rug_report',return_value={}):
                self.assertTrue(radar.run_once())
            c=radar.store.get(M)
            self.assertEqual(c['status'],'surveillance')
            self.assertTrue(c['early_watch'])
            self.assertFalse(c['eligible'])
            self.assertLess(c['coverage'],90)
            self.assertTrue(any('Autorités' in v or 'Score RugCheck' in v for v in c['unknown']))

class Narrative(unittest.TestCase):
    def test_name_text_not_ticker_or_substring(self):
        self.assertEqual(topic_name('AI'), '')
        self.assertEqual(topic_name('CAT COIN'), '')
        self.assertEqual(topic_name('GTA VI Coin'), 'gta 6')
        now=time.time()
        posts=[{'author':'elonmusk','text':'OpenAI updates','created_at':now,'is_backlog':False}]
        matches=contextual_matches('OpenAI',posts,[],now)
        self.assertEqual(len(matches),1)
        self.assertFalse(matches[0]['direct_contract'])
        self.assertEqual(contextual_matches('AI',posts,[],now),[])
        self.assertEqual(contextual_matches('OpenAI', [{'text':'MOPENAIR', 'created_at':now}],[],now),[])

    def test_reposts_backlog_and_old_posts_ignored(self):
        now=time.time()
        posts=[{'author':'elonmusk','text':'OpenAI', 'created_at':now-1800},
               {'author':'any','text':'OpenAI','created_at':now,'is_repost':True},
               {'author':'any','text':'OpenAI','created_at':now,'is_backlog':True}]
        self.assertEqual(contextual_matches('OpenAI',posts,[],now),[])

    def test_rss_and_store_independent(self):
        now=time.time()
        rss=b'<rss><channel><item><title>OpenAI model</title></item><item><title>GTA 6</title></item></channel></rss>'
        trends=parse_trends_rss(rss,'FR',now)
        self.assertEqual(len(trends),2)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite')
            store.save_trends(trends)
            got=store.recent_trends(now)
            self.assertEqual(len(got),2)
            self.assertEqual(len(contextual_matches('OpenAI',[],got,now)),1)

    def test_monitor_with_fake_source(self):
        now=time.time()
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite')
            mon=TrendsMonitor(store,threading.Event(),fetch=lambda url:b'<rss><channel><item><title>OpenAI News</title></item></channel></rss>')
            self.assertEqual(mon.update(),2)
            self.assertEqual(len(store.recent_trends(now)),2)

if __name__=='__main__':unittest.main()

class Triggers(unittest.TestCase):
    def test_large_j7_headline_wakes_only_existing_named_mint(self):
        from radar.social import J7Feed
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite')
            store.save_coin({'mint':'6PtLvzA8eY1NwUw1E9h48c7xphRvD6fK2ymDGQY1d1Nd',
                            'symbol':'OPENAI','name':'OpenAI Coin','status':'incomplet','score':9},time.time())
            wakes=[]
            feed=J7Feed(store,wakes.append,token='fake')
            post={'id':'1990123412341234567','text':'OpenAI shares a new model today',
                  'createdAt':int(time.time()*1000),
                  'author':{'id':'3000','handle':'bigaccount','followersCount':200000}}
            feed.ingest(post)
            self.assertEqual(wakes,['6PtLvzA8eY1NwUw1E9h48c7xphRvD6fK2ymDGQY1d1Nd'])
            feed.ingest(post)
            self.assertEqual(len(wakes),1)
            self.assertEqual(store.queue_due(limit=10)[0]['source'],'j7_thematic')

    def test_broad_topic_or_clones_no_forced_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite')
            from radar.social import is_solana_address
            mints=['6PtLvzA8eY1NwUw1E9h48c7xphRvD6fK2ymDGQY1d1Nd',
                   '69d6eAnot869mAuaDZqyF8qqDmXKQZqfhmDCyfQDapFp',
                   '66knKYRLSSsGtmZ4umiBSSW71hU4PwMrcQkQ2L3hpump']
            for m in mints:
                self.assertTrue(is_solana_address(m))
                store.save_coin({'mint':m,'symbol':'OPENAI','name':'OpenAI Coin','score':0,'status':'incomplet'},time.time())
            self.assertEqual(store.find_theme_mints('OpenAI model',limit=2),[])
            self.assertEqual(store.find_theme_mints('The dog is viral',limit=2),[])

class Prospective(unittest.TestCase):
    def test_early_watch_event_is_logged_even_with_unknown_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite')
            now=time.time()
            item={'mint':M,'pair_address':P,'price_usd':0.001,'status':'surveillance',
                  'score_method':'curve_experimentale','early_watch':True,'age_min':0.5,
                  'risks':[],'coverage':40,'score':15,'safety_summary':{},
                  'market_cap_usd':4000,'narrative_matches':[]}
            store.record_v3(item,{},now)
            events=store.research_for_v3(M)['events']
            self.assertTrue(any(e['kind']=='veille_precoce' and e['cohort']=='alert' for e in events))
            store.record_v3(item,item,now+20)
            self.assertEqual(len(store.research_for_v3(M)['events']),len(events))

    def test_known_risk_still_excluded_from_early_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite')
            store.record_v3({'mint':M,'price_usd':0.001,'early_watch':True,
                             'risks':['Mint authority active'],'safety_summary':{}},{},time.time())
            self.assertEqual(store.research_for_v3(M)['events'],[])

class FastFirstPass(unittest.TestCase):
    def test_provisional_visible_before_slow_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            radar=Radar(Path(tmp)/'radar.db','/missing',limit=1)
            observed=[]
            def inspect_before_gecko(pairs):
                observed.append(radar.store.get(M))
                return {},[]
            with patch('radar.engine.providers.discoveries',return_value=({M:{'gecko_new_pools'}},[])),\
                 patch.object(radar.wallet_monitor,'scan',return_value=(set(),[])),\
                 patch('radar.engine.providers.dex_pairs_batch',return_value={M:pair()}),\
                 patch('radar.engine.providers.quote_same_pools',side_effect=inspect_before_gecko),\
                 patch('radar.engine.providers.rug_report',return_value={}):
                self.assertTrue(radar.run_once())
            self.assertEqual(len(observed),1)
            self.assertTrue(observed[0]['early_watch'])
            self.assertEqual(observed[0]['status'],'surveillance')
            self.assertFalse(observed[0]['eligible'])
            self.assertTrue(any('en attente' in x for x in observed[0]['unknown']))
            # First-pass event is timestamped at emission, not after vendor fetch.
            self.assertTrue(any(e['kind']=='veille_precoce' for e in radar.store.research_for_v3(M)['events']))
