"""Bounded public RSS observation and auditable event/token associations."""
from __future__ import annotations
import hashlib
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from urllib.parse import urlparse, quote
from .narrative_intelligence import extract_phrases, topic_is_related
from .narratives import normal
from .decision_engine import assess
from .event_calendar import upcoming
from .narrative_graph import discover_terms, topic_graph, source_voice

SOURCES = (
    ('BBC World', 'https://feeds.bbci.co.uk/news/world/rss.xml'),
    ('Guardian World', 'https://www.theguardian.com/world/rss'),
    ('BBC Technology', 'https://feeds.bbci.co.uk/news/technology/rss.xml'),
    ('BBC Business', 'https://feeds.bbci.co.uk/news/business/rss.xml'),
    ('BBC Science', 'https://feeds.bbci.co.uk/news/science_and_environment/rss.xml'),
    ('BBC Culture', 'https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml'),
    ('France 24', 'https://www.france24.com/fr/rss'),
)


def safe_url(value):
    value = str(value or '')[:1000]
    try:
        parsed = urlparse(value)
        return value if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username else ''
    except ValueError:
        return ''


def parse_date(value):
    if not value:
        return None
    try:
        result = parsedate_to_datetime(value)
    except (ValueError, TypeError, OverflowError):
        try:
            result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except (ValueError, TypeError, OverflowError):
            return None
    if result.tzinfo is None:
        return None  # Never invent a publication timezone.
    return result.timestamp()


def parse_feed(raw, source, now):
    if len(raw) > 1_000_000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('RSS invalide ou trop volumineux')
    root = ET.fromstring(raw)
    result = []
    for item in (root.findall('.//item') + root.findall('.//{*}entry'))[:100]:
        title = ' '.join((item.findtext('title') or item.findtext('{*}title') or '').split())[:250]
        published = parse_date(item.findtext('pubDate') or item.findtext('{*}published') or item.findtext('{*}updated'))
        if not title or published is None or not now - 7 * 86400 <= published <= now:
            continue
        url = safe_url(item.findtext('link'))
        if not url:
            for link in item.findall('{*}link'):
                if link.get('rel', 'alternate')=='alternate':
                    url = safe_url(link.get('href'))
                    if url:
                        break
        identity = source + '|' + (url or normal(title))
        result.append({'id': hashlib.sha256(identity.encode()).hexdigest(),
                       'title': title, 'source': source, 'url': url,
                       'published_at': published, 'received_at': now,
                       'terms': discover_terms(title), 'kind': 'news'})
    return result


class WorldStore:
    def init_world(self):
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS world_events (
                id TEXT PRIMARY KEY, published_at REAL NOT NULL, data_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_world_time ON world_events(published_at);
                CREATE TABLE IF NOT EXISTS strategy_samples (
                    mint TEXT NOT NULL, bucket INTEGER NOT NULL, observed_at REAL NOT NULL,
                    price REAL, liquidity REAL, top10 REAL,
                    PRIMARY KEY(mint,bucket));''')

    def save_strategy_sample(self, coin, now):
        # One sample per hour, preserving the original observation of that hour.
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO strategy_samples VALUES (?,?,?,?,?,?)',
                       (coin['mint'], int(now//3600), now, coin.get('price_usd'),
                        coin.get('liquidity_usd'), (coin.get('safety_summary') or {}).get('top10_pct')))
            db.execute('DELETE FROM strategy_samples WHERE observed_at<?', (now-30*86400,))

    def strategy_histories(self, mints, now):
        if not mints:
            return {}
        with self.read_db() as db:
            rows = db.execute('SELECT * FROM strategy_samples WHERE mint IN (' + ','.join('?' for _ in mints) + ') AND observed_at>=? ORDER BY observed_at',
                              (*mints, now-7*86400)).fetchall()
        result = {}
        for row in rows:
            result.setdefault(row['mint'], []).append(dict(row))
        return result

    def observed_risks(self, mints):
        if not mints:
            return {}
        with self.read_db() as db:
            rows = db.execute('SELECT mint,checked_at,details_json FROM live_risk_observations WHERE mint IN (' + ','.join('?' for _ in mints) + ')', mints).fetchall()
        return {r['mint']: dict(json.loads(r['details_json']), checked_at=r['checked_at']) for r in rows}

    def save_world_events(self, events, now):
        added = []
        with self.db() as db:
            for event in events[:100]:
                if db.execute('INSERT OR IGNORE INTO world_events VALUES (?,?,?)',
                              (event['id'], event['published_at'], json.dumps(event))).rowcount:
                    added.append(event)
            db.execute('DELETE FROM world_events WHERE published_at < ?', (now - 7 * 86400,))
        return added

    def world_events(self, now=None):
        now = time.time() if now is None else now
        with self.read_db() as db:
            rows = db.execute('SELECT data_json FROM world_events WHERE published_at BETWEEN ? AND ? ORDER BY published_at DESC LIMIT 1000',
                              (now - 7 * 86400, now)).fetchall()
        return [json.loads(x[0]) for x in rows]


class WorldMonitor:
    def __init__(self, store, stop_event, fetch=None, search=None, sources=None):
        self.store, self.stop_event = store, stop_event
        self.fetch = fetch or self._fetch
        self.search = search or search_tokens
        self.searched = {}
        self.sources = sources
        self.next_rss = 0
        self.next_search = 0
        self.status = {'interval_s': 30, 'rss_interval_s':300, 'sources': {}, 'last_cycle': None}

    def _news_results(self, now):
        if now < self.next_rss or self.stop_event.is_set():
            return
        self.next_rss = now+300
        sources = SOURCES if self.sources is None else self.sources
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix='world-rss') as pool:
            jobs = {pool.submit(self.fetch, url):name for name,url in sources}
            for job in as_completed(jobs):
                if self.stop_event.is_set():
                    break
                try:
                    yield jobs[job], job.result(), None
                except Exception as exc:
                    yield jobs[job], None, type(exc).__name__

    @staticmethod
    def _fetch(url):
        request = urllib.request.Request(url, headers={'User-Agent': 'MemeRadar/2.0 (read-only RSS)'})
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.read(1_000_001)

    def update(self):
        now = time.time()
        queued = set()
        candidates = []
        for name, raw, error in self._news_results(now):
            if self.stop_event.is_set():
                break
            previous = self.status['sources'].get(name, {})
            if error:
                self.status['sources'][name] = {**previous, 'error':error, 'last_failure':now}
                continue
            try:
                events = parse_feed(raw, name, now)
                added = self.store.save_world_events(events, now)
                candidates.extend(e for e in added if now-e['published_at'] <= 3600)
                self.status['sources'][name] = {'last_success': now, 'items': len(events),
                                                'new': len(added), 'error': None}
                # New headlines may revive known tokens; cap work independently of feed size.
                for event in added[:10]:
                    if now-event['published_at'] > 3600:
                        continue
                    for mint in self.store.find_phrase_candidates(event['title'], limit=3):
                        if mint not in queued and len(queued) < 12:
                            self.store.enqueue(mint, 'world_news_thematic')
                            queued.add(mint)
            except Exception as exc:
                self.status['sources'][name] = {**previous, 'error': type(exc).__name__, 'last_failure': now}
        candidates.extend(social_events(self.store.recent_social(100), now))
        self.status['social_checked_at'] = now
        if now < self.next_search:
            candidates = []
        else:
            self.next_search = now+300
        self.searched = {term: stamp for term, stamp in self.searched.items() if now-stamp < 3600}
        searches = 0
        self.status['search_error'] = None
        for event in sorted(candidates, key=lambda e:e['published_at'], reverse=True):
            if self.stop_event.is_set() or searches >= 3 or len(queued) >= 12:
                break
            if now-event['published_at'] > 3600:
                continue
            for term in event['terms'][:2]:
                if searches >= 3 or len(queued) >= 12:
                    break
                if term['term'] in self.searched:
                    continue
                self.searched[term['term']] = now
                searches += 1
                try:
                    for mint in self.search(term['term'])[:3]:
                        if mint not in queued and len(queued)<12:
                            self.store.enqueue(mint, 'world_topic_search')
                            queued.add(mint)
                except Exception as exc:
                    self.status['search_error'] = type(exc).__name__
        self.status['searches'] = searches
        self.status['queued'] = len(queued)
        self.status['last_cycle'] = now

    def run(self):
        if self.stop_event.wait(2):
            return
        while not self.stop_event.is_set():
            try:
                self.update()
            except Exception as exc:
                self.status['error'] = type(exc).__name__
            self.stop_event.wait(30)


def search_tokens(term, get=None):
    """Public discovery only. Exact Solana contract and literal topic validation."""
    from .source_scanner import fetch, DEX, candidate
    get = get or fetch
    data = get(DEX + '/latest/dex/search?q=' + quote(term))
    out = []
    for pair in (data.get('pairs') or [])[:30]:
        base = pair.get('baseToken') or {}
        mint = base.get('address')
        if pair.get('chainId') == 'solana' and candidate(mint) and topic_is_related(term, base.get('name'), base.get('symbol')) and mint not in out:
            out.append(mint)
    return out[:3]


def social_events(posts, now):
    from .social import is_solana_address
    out = []
    for post in posts:
        if any(post.get(k) for k in ('deleted', 'is_backlog', 'is_repost', 'is_reply')):
            continue
        published = post.get('created_at') or 0
        if not now - 7 * 86400 <= published <= now:
            continue
        title = str(post.get('text') or '')[:1200]
        out.append({'id': 'j7:' + str(post.get('id')), 'title': title,
                    'source': 'J7 @' + str(post.get('author') or '?'),
                    'url': safe_url(post.get('url')), 'published_at': published,
                    'received_at': post.get('received_at'), 'kind': 'social',
                    'mints':[mint for mint in (post.get('mints') or [])[:10] if is_solana_address(mint)],
                    'terms': discover_terms(title)})
    return out


@lru_cache(maxsize=4096)
def _topic_pattern(term):
    phrase = normal(term)
    return phrase, re.compile(r'(?<![a-z0-9])'+re.escape(phrase)+r'(?![a-z0-9])')


def link_events(coin, events):
    links = []
    mint = str(coin.get('mint') or '')
    name, symbol = normal(coin.get('name')), normal(coin.get('symbol'))
    related = {}
    for event in events:
        direct = bool(mint and (mint in event.get('mints', []) or (mint in event['title'] and re.search(r'(?<![A-Za-z0-9])' + re.escape(mint) + r'(?![A-Za-z0-9])', event['title']))))
        terms = []
        for item in event['terms']:
            term = item['term']
            if term not in related:
                phrase, pattern = _topic_pattern(term)
                related[term] = (topic_is_related(term, name, symbol) if term=='GTA VI' else
                                 bool(phrase and ((name and pattern.search(name)) or (len(phrase)>=5 and phrase==symbol))))
            if related[term]:
                terms.append(term)
        if direct or terms:
            links.append({'event_id': event['id'], 'source': event['source'], 'url': event['url'],
                          'title': event['title'][:250], 'published_at': event['published_at'],
                          'relation': 'contract_mention' if direct else 'thematic_hypothesis',
                          'terms': terms, 'affiliation_verified': False})
    return links


def emerging(events, now):
    groups = {}
    for event in events:
        age = now - event['published_at']
        if not 0 <= age < 7200:
            continue
        for term in {x['term'] for x in event['terms']}:
            g = groups.setdefault(term, {'term': term, 'current': 0, 'previous': 0, 'sources': set(), 'titles': set()})
            # Syndicated identical headlines are one observation, not independent confirmation.
            title = normal(event['title'])
            if title in g['titles']:
                continue
            g['titles'].add(title)
            g['current' if age < 3600 else 'previous'] += 1
            if age < 3600:
                g['sources'].add(source_voice(event['source']))
    out = []
    for g in groups.values():
        g.pop('titles')
        g['sources'] = sorted(g['sources'])
        g['emerging'] = g['current'] >= 3 and len(g['sources']) >= 2 and g['current'] > 2 * g['previous']
        g['phase'] = ('acceleration' if g['emerging'] else 'appearance' if g['previous']==0 else
                      'decline' if g['current'] < g['previous'] else 'persistent')
        if g['current'] or g['previous']:
            out.append(g)
    return sorted(out, key=lambda g: (g['emerging'], g['current']), reverse=True)[:30]


def build_report(coins, events, now=None):
    now = time.time() if now is None else now
    events = sorted(events, key=lambda e: e['published_at'], reverse=True)
    rows = []
    for coin in coins:
        evaluated = coin.get('decision_evaluated_at') == now and 'strategy_decisions' in coin
        links = coin['world_context'] if evaluated else link_events(coin, events)
        decision = {'risk':coin['security_gate'], 'strategies':coin['strategy_decisions']} if evaluated else assess(coin, links, now)
        rows.append({'mint': coin['mint'], 'symbol': coin.get('symbol'), 'name': coin.get('name'),
                     **decision, 'events': links[:12], 'event_count': coin.get('world_event_count', len(links)) if evaluated else len(links)})
    return {'version': '2.0', 'generated_at': now, 'manual_only': True, 'coins': rows,
            'events': events[:60], 'narratives': emerging(events, now), 'upcoming': upcoming(events, now),
            'topic_graph': topic_graph(events),
            'coverage': {'tokens_evaluated': len(coins), 'events_evaluated': len(events)},
            'note': 'Périmètre borné : 300 tokens, 1 000 titres RSS et 500 posts J7 ; 7 jours maximum. Liens thématiques sans affiliation prouvée. Scores non calibrés.'}
