"""J7-first hub (v7.2): ledger of every contract J7 surfaces, schema telemetry, outcome tracking.

READ-ONLY. A "highlight" is only the observation that J7 linked a post (or a launch
card) to a mint. It is never an approval, a safety proof or a buy signal.

What this module adds on top of the old J7 listener:
  * `j7_highlights`  : one row per (mint, via, post). The earliest row of a mint is the
                       one that is tracked ("first_for_mint").
  * latency          : seen_at - post_at, i.e. how late *we* learned about the link.
  * `j7_schema`      : which JSON keys J7 really sends (never values), so unknown fields
                       such as tokenMeta, grok or isContractLaunch stop being guesses.
  * outcomes         : price change measured from the FIRST quote we could get, at
                       +1/+5/+20/+60 min after that quote. Missing data is 'missing',
                       never an automatic -100 %. These are quotes, not executable exits.
  * per-source stats : so "is this author / platform / via worth watching?" is answered
                       by measurements, not by follower counts.
"""
from __future__ import annotations
import json
import math
import statistics
import time

HORIZONS = (60, 300, 600, 1200, 3600, 10800, 21600)
TOLERANCE = 90                 # an outcome must be observed within [h, h+TOLERANCE] after the first quote
TRACK_WINDOW = 21600 + TOLERANCE + 600
MIN_RELIABLE = 10              # below this many observed outcomes, a statistic is "not conclusive"
FLAG_KEYS = ('isContractLaunch', 'playSound', 'isRetweet', 'isQuote', 'isReply')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS j7_highlights (
 id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT NOT NULL, via TEXT NOT NULL,
 post_id TEXT NOT NULL DEFAULT '', platform TEXT NOT NULL DEFAULT '',
 author TEXT NOT NULL DEFAULT '', followers INTEGER, post_at REAL, seen_at REAL NOT NULL,
 latency_s REAL, name TEXT NOT NULL DEFAULT '', symbol TEXT NOT NULL DEFAULT '',
 flags_json TEXT NOT NULL DEFAULT '{}', first_for_mint INTEGER NOT NULL DEFAULT 0,
 ref_price REAL, ref_at REAL,
 UNIQUE(mint, via, post_id));
CREATE INDEX IF NOT EXISTS idx_j7h_seen ON j7_highlights(seen_at);
CREATE INDEX IF NOT EXISTS idx_j7h_mint ON j7_highlights(mint);
CREATE INDEX IF NOT EXISTS idx_j7h_post ON j7_highlights(post_id);
CREATE TABLE IF NOT EXISTS j7_highlight_outcomes (
 highlight_id INTEGER NOT NULL, horizon INTEGER NOT NULL, state TEXT NOT NULL,
 at REAL NOT NULL, price REAL, return_pct REAL,
 PRIMARY KEY(highlight_id, horizon));
CREATE TABLE IF NOT EXISTS j7_schema (
 kind TEXT NOT NULL, shape TEXT NOT NULL, first_seen REAL NOT NULL,
 PRIMARY KEY(kind, shape));
'''


# ---------------------------------------------------------------- pure helpers
def _clean(value, size):
    return str(value or '').strip()[:size]


def shape_of(obj, limit=70):
    """Sorted key names (one nested level). Values are NEVER kept."""
    if not isinstance(obj, dict):
        return []
    keys = []
    for k, v in obj.items():
        keys.append(_clean(k, 35))
        if isinstance(v, dict):
            keys.extend(_clean(k, 20) + '.' + _clean(s, 20) for s in v)
    return sorted(set(keys))[:limit]


def extract_flags(item):
    """Booleans J7 attaches to a post, plus presence of rich fields. No free text."""
    if not isinstance(item, dict):
        return {}
    flags = {k: bool(item[k]) for k in FLAG_KEYS if k in item}
    for out, key in (('has_grok', 'grok'), ('has_card', 'card'), ('has_coin_pairs', 'coinPairs')):
        if key in item:
            flags[out] = bool(item[key])
    return flags


def token_meta_info(data):
    """Name/symbol J7 may attach to a highlighted token. Defensive: field names are unverified."""
    meta = data.get('tokenMeta') if isinstance(data, dict) and isinstance(data.get('tokenMeta'), dict) else {}

    def pick(*keys):
        for key in keys:
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ''
    return {'name': pick('name', 'tokenName')[:80], 'symbol': pick('symbol', 'ticker', 'tokenSymbol')[:25]}


def _median(values):
    return round(statistics.median(values), 2) if values else None


def _price(pair):
    from .source_scanner import number
    value = number((pair or {}).get('priceUsd'))
    return value if isinstance(value, (int, float)) and math.isfinite(value) and value > 0 else None


# ---------------------------------------------------------------- store mixin
class J7Hub:
    def init_j7_hub(self):
        with self.db() as db:
            db.executescript(SCHEMA)

    # -- telemetry -------------------------------------------------------
    def record_shape(self, kind, obj, now=None):
        keys = shape_of(obj)
        if not keys:
            return False
        now = time.time() if now is None else now
        with self.db() as db:
            added = bool(db.execute('INSERT OR IGNORE INTO j7_schema(kind,shape,first_seen) VALUES(?,?,?)',
                                    (_clean(kind, 60), json.dumps(keys), now)).rowcount)
            # bounded: telemetry must never grow without limit
            db.execute('DELETE FROM j7_schema WHERE rowid NOT IN (SELECT rowid FROM j7_schema ORDER BY first_seen DESC LIMIT 300)')
        return added

    def schema_report(self, limit=40):
        with self.read_db() as db:
            rows = db.execute('SELECT kind,shape,first_seen FROM j7_schema ORDER BY first_seen DESC LIMIT ?', (limit,)).fetchall()
        return [{'kind': r['kind'], 'keys': json.loads(r['shape']), 'first_seen': r['first_seen']} for r in rows]

    # -- ledger ----------------------------------------------------------
    def record_highlight(self, mint, via, *, post_id='', platform='', author='', followers=None,
                         post_at=None, name='', symbol='', flags=None, now=None):
        from .social import is_solana_address
        if not is_solana_address(mint):
            return None
        now = time.time() if now is None else now
        post_at = float(post_at) if isinstance(post_at, (int, float)) and not isinstance(post_at, bool) else None
        latency = (now - post_at) if post_at else None  # signed: future J7 timestamps are clock skew, not 0s speed
        followers = int(followers) if isinstance(followers, (int, float)) and not isinstance(followers, bool) and math.isfinite(followers) and followers >= 0 else None
        clean_flags = {k: bool(v) for k, v in (flags or {}).items() if isinstance(k, str)}
        with self.db() as db:
            first = db.execute('SELECT 1 FROM j7_highlights WHERE mint=? LIMIT 1', (mint,)).fetchone() is None
            cur = db.execute('''INSERT OR IGNORE INTO j7_highlights
                (mint,via,post_id,platform,author,followers,post_at,seen_at,latency_s,name,symbol,flags_json,first_for_mint)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (mint, _clean(via, 40), _clean(post_id, 40), _clean(platform, 35), _clean(author, 40).lstrip('@'),
                 followers, post_at, now, latency, _clean(name, 80), _clean(symbol, 25),
                 json.dumps(clean_flags, sort_keys=True), 1 if first else 0))
            if cur.rowcount:
                row_id = cur.lastrowid
            else:
                row = db.execute('SELECT id,author,name,symbol FROM j7_highlights WHERE mint=? AND via=? AND post_id=?',
                                 (mint, _clean(via, 40), _clean(post_id, 40))).fetchone()
                row_id, first = row['id'], False
                # late enrichment must never erase what we already know
                if (not row['author'] and author) or (not row['name'] and name) or (not row['symbol'] and symbol):
                    db.execute('''UPDATE j7_highlights SET author=CASE WHEN author='' THEN ? ELSE author END,
                        name=CASE WHEN name='' THEN ? ELSE name END, symbol=CASE WHEN symbol='' THEN ? ELSE symbol END
                        WHERE id=?''', (_clean(author, 40).lstrip('@'), _clean(name, 80), _clean(symbol, 25), row_id))
        return {'id': row_id, 'first': first}

    def enrich_highlights(self, post_id, *, author='', followers=None, post_at=None, platform=''):
        """The J7 token_meta event can precede its tweet: fill author/latency once the post arrives."""
        if not post_id:
            return 0
        followers = int(followers) if isinstance(followers, (int, float)) and not isinstance(followers, bool) and math.isfinite(followers) and followers >= 0 else None
        with self.db() as db:
            rows = db.execute("SELECT id,seen_at FROM j7_highlights WHERE post_id=? AND author=''", (_clean(post_id, 40),)).fetchall()
            for row in rows:
                latency = (row['seen_at'] - post_at) if isinstance(post_at, (int, float)) and post_at else None
                db.execute('''UPDATE j7_highlights SET author=?, followers=COALESCE(followers,?), post_at=COALESCE(post_at,?),
                    latency_s=COALESCE(latency_s,?), platform=CASE WHEN platform='' THEN ? ELSE platform END WHERE id=?''',
                    (_clean(author, 40).lstrip('@'), followers, post_at, latency, _clean(platform, 35), row['id']))
        return len(rows)

    def first_highlights(self, mints):
        """mint -> earliest highlight (provenance shown next to a coin)."""
        out = {}
        mints = [m for m in dict.fromkeys(mints) if isinstance(m, str)]
        with self.db() as db:
            for i in range(0, len(mints), 400):
                chunk = mints[i:i + 400]
                marks = ','.join('?' * len(chunk))
                for r in db.execute(f'''SELECT mint,via,platform,author,followers,seen_at,latency_s,name,symbol
                        FROM j7_highlights WHERE first_for_mint=1 AND mint IN ({marks})''', chunk):
                    out[r['mint']] = {k: r[k] for k in r.keys() if k != 'mint'}
        return out

    def first_highlight(self, mint):
        return self.first_highlights([mint]).get(mint)

    # -- outcomes --------------------------------------------------------
    def tracking_due(self, now=None, limit=60):
        now = time.time() if now is None else now
        with self.db() as db:
            rows = [dict(r) for r in db.execute('''SELECT id,mint,seen_at,ref_price,ref_at FROM j7_highlights
                WHERE first_for_mint=1 AND seen_at>? ORDER BY seen_at ASC LIMIT ?''', (now - TRACK_WINDOW, 3000))]
            ids = [r['id'] for r in rows]
            done = {}
            if ids:
                marks = ','.join('?' * len(ids))
                for r in db.execute(f'SELECT highlight_id,horizon FROM j7_highlight_outcomes WHERE highlight_id IN ({marks})', ids):
                    done.setdefault(r['highlight_id'], set()).add(r['horizon'])
        out = []
        for r in rows:
            r['done'] = done.get(r['id'], set())
            if r['ref_at'] is None and now-r['seen_at']>600:continue
            pending=[h for h in HORIZONS if h not in r['done']]
            if not pending:continue
            target=(r['ref_at']+min(pending)) if r['ref_at'] is not None else r['seen_at']
            if target<=now:
                r['_due']=target
                out.append(r)
        return sorted(out,key=lambda r:r['_due'])[:limit]

    def set_reference(self, highlight_id, price, at):
        with self.db() as db:
            db.execute('UPDATE j7_highlights SET ref_price=?, ref_at=? WHERE id=? AND ref_price IS NULL', (price, at, highlight_id))

    def record_outcome(self, highlight_id, horizon, state, at, price=None, return_pct=None):
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO j7_highlight_outcomes VALUES(?,?,?,?,?,?)',
                       (highlight_id, horizon, state, at, price, return_pct))

    # -- report ----------------------------------------------------------
    def j7_report(self, limit=40, now=None, days=7):
        now = time.time() if now is None else now
        with self.read_db() as db:
            rows = [dict(r) for r in db.execute('''SELECT * FROM j7_highlights WHERE first_for_mint=1 AND seen_at>?
                ORDER BY seen_at DESC LIMIT 1500''', (now - days * 86400,))]
            outs = {}
            if rows:
                low = min(r['id'] for r in rows)
                for o in db.execute('SELECT highlight_id,horizon,state,return_pct FROM j7_highlight_outcomes WHERE highlight_id>=?', (low,)):
                    outs.setdefault(o['highlight_id'], {})[o['horizon']] = (o['state'], o['return_pct'])
        recent = []
        for r in rows[:limit]:
            coin = self.get(r['mint']) or {}
            recent.append({
                'mint': r['mint'], 'via': r['via'], 'platform': r['platform'], 'author': r['author'],
                'followers': r['followers'], 'age_s': int(now - r['seen_at']), 'latency_s': r['latency_s'],
                'name': r['name'] or coin.get('name') or '', 'symbol': r['symbol'] or coin.get('symbol') or '',
                'status': coin.get('status'), 'score': coin.get('score'),
                'quoted_lag_s': (round(r['ref_at'] - r['seen_at'], 1) if r['ref_at'] else None),
                'flags': json.loads(r['flags_json'] or '{}'),
                'outcomes': {str(h): (outs.get(r['id'], {}).get(h) or (None, None))[1] for h in HORIZONS}})

        def aggregate(key_fn):
            groups = {}
            for r in rows:
                groups.setdefault(key_fn(r), []).append(r)
            result = []
            for key, items in groups.items():
                entry = {'key': key, 'n': len(items),
                         'latency_median_s': _median([r['latency_s'] for r in items if r['latency_s'] is not None]),
                         'quoted': sum(r['ref_price'] is not None for r in items)}
                for h in (300, 1200):
                    values = [outs[r['id']][h][1] for r in items if h in outs.get(r['id'], {}) and outs[r['id']][h][0] == 'observed']
                    entry[f'ret_{h}_median'] = _median(values)
                    entry[f'ret_{h}_n'] = len(values)
                    entry[f'ret_{h}_conclusive'] = len(values) >= MIN_RELIABLE
                result.append(entry)
            return sorted(result, key=lambda e: e['n'], reverse=True)

        authors = aggregate(lambda r: (r['platform'] or '?') + ' / ' + (r['author'] or 'inconnu'))[:15]
        vias = aggregate(lambda r: r['via'])[:10]
        return {'recent': recent, 'authors': authors, 'vias': vias,
                'totals': {'highlights_7d': len(rows), 'min_reliable': MIN_RELIABLE,
                           'latency_median_s': _median([r['latency_s'] for r in rows if r['latency_s'] is not None]),
                           'never_quoted': sum(r['ref_price'] is None and now - r['seen_at'] > 600 for r in rows)},
                'schemas': self.schema_report(30),
                'note': 'Variations mesurées depuis la première cotation obtenue, pas des gains réalisables. '
                        'Sans groupe témoin, aucun résultat ne prouve que le surlignage J7 apporte un avantage.'}


# ---------------------------------------------------------------- tracker
class HighlightTracker:
    """Measures what happened to a highlighted mint after its first available quote."""

    def __init__(self, store, stop_event, get_pairs=None, interval=15):
        self.store, self.stop_event, self.interval = store, stop_event, interval
        self.get_pairs = get_pairs
        self.status = {'ticks': 0, 'last_tick': None, 'error': None, 'tracked': 0}

    def tick(self, now=None):
        injected_time=now is not None
        now = time.time() if now is None else now
        due = self.store.tracking_due(now)
        self.status.update(tracked=len(due), last_tick=now)
        if not due:
            return 0
        getter = self.get_pairs
        if getter is None:
            from .providers import dex_pairs_batch
            getter = dex_pairs_batch
        pairs = getter(list(dict.fromkeys(r['mint'] for r in due)))
        if not injected_time:now=time.time()  # quote arrival, never request start
        recorded = 0
        for row in due:
            price = _price(pairs.get(row['mint']))
            if row['ref_price'] is None:
                if price:
                    self.store.set_reference(row['id'], price, now)
                continue
            elapsed = now - row['ref_at']
            for horizon in HORIZONS:
                if horizon in row['done'] or elapsed < horizon:
                    continue
                if elapsed <= horizon + TOLERANCE and price:
                    self.store.record_outcome(row['id'], horizon, 'observed', now, price,
                                              round((price / row['ref_price'] - 1) * 100, 2))
                elif elapsed > horizon + TOLERANCE:
                    self.store.record_outcome(row['id'], horizon, 'missing', now)
                else:
                    continue
                recorded += 1
        return recorded

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
                self.status.update(ticks=self.status['ticks'] + 1, error=None)
            except Exception as exc:  # network/provider errors must never stop the loop
                self.status['error'] = type(exc).__name__
            self.stop_event.wait(self.interval)
