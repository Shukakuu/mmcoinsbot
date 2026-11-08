"""Local SQLite journal for all analyzed tokens and price snapshots."""
from __future__ import annotations
import json, sqlite3, time, threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS coins (
  mint TEXT PRIMARY KEY, symbol TEXT NOT NULL DEFAULT '?', name TEXT NOT NULL DEFAULT '?',
  first_seen REAL NOT NULL, last_seen REAL NOT NULL, data_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prices (
  mint TEXT NOT NULL, ts REAL NOT NULL, price REAL NOT NULL, liquidity REAL,
  PRIMARY KEY (mint,ts));
CREATE INDEX IF NOT EXISTS idx_prices_mint_time ON prices(mint,ts);
CREATE TABLE IF NOT EXISTS market_snapshots (
 mint TEXT NOT NULL, ts REAL NOT NULL, data_json TEXT NOT NULL,
 PRIMARY KEY(mint,ts));
CREATE INDEX IF NOT EXISTS idx_market_snapshots_mint_time ON market_snapshots(mint,ts);
CREATE TABLE IF NOT EXISTS safety_cache (mint TEXT PRIMARY KEY, ts REAL NOT NULL, data_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS wallet_events (
  mint TEXT NOT NULL, wallet TEXT NOT NULL, signature TEXT NOT NULL,
  ts REAL NOT NULL, PRIMARY KEY (mint,wallet,signature));
CREATE TABLE IF NOT EXISTS wallet_cursors (
  wallet TEXT PRIMARY KEY, signature TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS social_posts (
    id TEXT PRIMARY KEY, created_at REAL NOT NULL, received_at REAL NOT NULL,
    data_json TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_social_post_received ON social_posts(received_at);
CREATE TABLE IF NOT EXISTS social_mints (
    id TEXT NOT NULL, mint TEXT NOT NULL, created_at REAL NOT NULL,
    PRIMARY KEY(id,mint));
CREATE INDEX IF NOT EXISTS idx_social_mints_mint ON social_mints(mint,created_at);
'''

from .research import ResearchStore

class Store(ResearchStore):
    def __init__(self, path):
        self.path = str(Path(path).resolve())
        self._db_lock = threading.RLock()
        with self.db() as db: db.executescript(SCHEMA)
        self.init_research()

    @contextmanager
    def db(self):
        """Commit or roll back, and ALWAYS close the SQLite connection."""
        # A single connection owns the read/modify/write transaction. WAL alone
        # does not avoid SQLITE_BUSY_SNAPSHOT when two writers upgrade reads.
        with self._db_lock:
            db = sqlite3.connect(self.path, timeout=30)
            db.row_factory = sqlite3.Row
            try:
                db.execute('PRAGMA busy_timeout=30000')
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('BEGIN IMMEDIATE')
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    def get(self, mint):
        with self.db() as db:
            row = db.execute('SELECT * FROM coins WHERE mint=?', (mint,)).fetchone()
        return json.loads(row['data_json']) if row else None

    def count_coins(self):
        with self.db() as db:
            return db.execute('SELECT COUNT(*) FROM coins').fetchone()[0]

    def list_coins(self, limit=300):
        with self.db() as db:
            rows = db.execute('SELECT data_json FROM coins ORDER BY last_seen DESC LIMIT ?', (limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_coin(self, item, ts):
        mint = item['mint']
        with self.db() as db:
            prev = db.execute('SELECT first_seen,data_json FROM coins WHERE mint=?', (mint,)).fetchone()
            item['first_seen'] = prev['first_seen'] if prev else ts
            previous_data=json.loads(prev['data_json']) if prev else {}
            initial = previous_data.get('first_price_usd')
            current = item.get('price_usd')
            item['first_price_usd'] = initial if initial is not None else (current if current and current>0 else None)
            item['last_seen'] = ts
            db.execute('''INSERT INTO coins(mint,symbol,name,first_seen,last_seen,data_json)
                VALUES(?,?,?,?,?,?) ON CONFLICT(mint) DO UPDATE SET
                symbol=excluded.symbol,name=excluded.name,last_seen=excluded.last_seen,
                data_json=excluded.data_json''',
                (mint, item['symbol'], item['name'], item['first_seen'],ts,json.dumps(item,ensure_ascii=False)))
            p = item.get('price_usd')
            if p and p > 0:
                db.execute('INSERT OR IGNORE INTO prices(mint,ts,price,liquidity) VALUES(?,?,?,?)',
                           (mint, int(ts),p,item.get('liquidity_usd')))
            # Long-running monitor: keep latest 3 days of 2-min samples, no fake backfill.
            db.execute('DELETE FROM prices WHERE ts < ?', (ts - 3*86400,))

    def save_market_snapshot(self, mint, snapshot):
        """Stores real provider readings. Used for pre-momentum checks only."""
        ts=float(snapshot['ts'])
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO market_snapshots VALUES(?,?,?)',
                       (mint,ts,json.dumps(snapshot)))
            db.execute('DELETE FROM market_snapshots WHERE ts<?', (ts-86400,))

    def market_snapshots(self,mint,limit=12):
        with self.db() as db:
            rows=db.execute('SELECT data_json FROM market_snapshots WHERE mint=? ORDER BY ts DESC LIMIT ?',
                            (mint,limit)).fetchall()
        return [json.loads(r[0]) for r in reversed(rows)]

    def history(self, mint, limit=150):
        with self.db() as db:
            rows = db.execute('SELECT ts,price,liquidity FROM prices WHERE mint=? ORDER BY ts DESC LIMIT ?', (mint,limit)).fetchall()
        return [dict(row) for row in reversed(rows)]

    def cached_safety(self,mint,ttl_s=900):
        with self.db() as db:
            row = db.execute('SELECT * FROM safety_cache WHERE mint=?', (mint,)).fetchone()
        if row and row['ts'] > time.time() - ttl_s: return json.loads(row['data_json'])
        return None

    def save_safety(self,mint,item):
        with self.db() as db:
            db.execute('''INSERT INTO safety_cache VALUES(?,?,?) ON CONFLICT(mint)
                DO UPDATE SET ts=excluded.ts,data_json=excluded.data_json''',
                (mint,time.time(),json.dumps(item)))

    def save_wallet_event(self,mint,wallet,signature,ts):
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO wallet_events VALUES (?,?,?,?)', (mint,wallet,signature,ts))

    def wallet_hits(self,mint,recent_s=900):
        with self.db() as db:
            rows = db.execute('SELECT DISTINCT wallet FROM wallet_events WHERE mint=? AND ts>=?',(mint,time.time()-recent_s)).fetchall()
        return [r[0] for r in rows]

    def wallet_mints(self, recent_s=14400):
        with self.db() as db:
            rows = db.execute('SELECT DISTINCT mint FROM wallet_events WHERE ts>?',(time.time()-recent_s,)).fetchall()
        return [r[0] for r in rows]

    def cursor(self,wallet):
        with self.db() as db:
            row = db.execute('SELECT signature FROM wallet_cursors WHERE wallet=?',(wallet,)).fetchone()
        return row[0] if row else None

    def set_cursor(self,wallet,signature):
        with self.db() as db:
            db.execute('''INSERT INTO wallet_cursors VALUES(?,?) ON CONFLICT(wallet)
                DO UPDATE SET signature=excluded.signature''',(wallet,signature))

    def stats(self):
        coins = self.list_coins()
        return dict(total=len(coins), promising=sum(x['status']=='a_etudier' for x in coins),
                    risky=sum(x['status']=='risque' for x in coins))

    def cached_x_profile(self,author_id,ttl=43200):
        with self.db() as db:
            row=db.execute('SELECT checked_at,profile_json FROM x_profiles WHERE author_id=?',(author_id,)).fetchone()
        if row and row['checked_at']>=time.time()-ttl:
            return json.loads(row['profile_json'])
        return None

    def cache_x_profile(self,author_id,profile):
        with self.db() as db:
            db.execute('INSERT INTO x_profiles VALUES(?,?,?) ON CONFLICT(author_id) DO UPDATE SET checked_at=excluded.checked_at,profile_json=excluded.profile_json',
                      (author_id,time.time(),json.dumps(profile,ensure_ascii=False)))

    def attach_x_profile(self,post_id,profile):
        with self.db() as db:
            row=db.execute('SELECT data_json FROM social_posts WHERE id=?',(str(post_id),)).fetchone()
            if not row:return False
            post=json.loads(row[0])
            if str(post.get('author_id'))!=str(profile.get('id')) or str(post.get('author','')).casefold()!=str(profile.get('handle','')).casefold():
                return False
            post['x_verified']=bool(profile['verified'])
            post['x_verified_source']='x_official_api'
            post['x_checked_at']=profile['checked_at']
            post['x_audience_warnings']=profile.get('warnings') or []
            post['x_audience_audit']='non_disponible'
            if isinstance(profile.get('followers'),int):
                post['followers']=profile['followers']
            db.execute('UPDATE social_posts SET data_json=? WHERE id=?',(json.dumps(post,ensure_ascii=False),str(post_id)))
            return True

    def get_social_post(self, post_id):
        with self.db() as db:
            row=db.execute('SELECT data_json FROM social_posts WHERE id=?',(post_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_social(self, post):
        """Idempotent J7 event upsert. Never overwrites rich fields with empty updates.

        Returns (new_post, newly_observed_contract_addresses).
        """
        with self.db() as db:
            existing=db.execute('SELECT data_json,deleted FROM social_posts WHERE id=?',(post['id'],)).fetchone()
            old=json.loads(existing['data_json']) if existing else {}
            merged={**old,**post}
            if len(old.get('text') or '') > len(post.get('text') or ''):
                merged['text']=old['text']
            # Only verified data fetched from the official X API can authorize
            # trusted social ranking. Never overwrite it with J7 updates.
            for key in ('x_verified','x_verified_source','x_checked_at','x_audience_warnings','x_audience_audit'):
                if key in old: merged[key]=old[key]
            for key in ('j7_verified','j7_badge','j7_verified_type','j7_parody'):
                if post.get(key) is None and key in old:merged[key]=old[key]
            for key in ('followers','author_id'):
                if post.get(key) is None or post.get(key)=='':
                    merged[key]=old.get(key)
            merged['mints']=list(dict.fromkeys((old.get('mints') or []) + (post.get('mints') or [])))[:8]
            merged['tickers']=list(dict.fromkeys((old.get('tickers') or []) + (post.get('tickers') or [])))[:12]
            merged['received_at']=old.get('received_at',post['received_at'])
            merged['created_at']=old.get('created_at',post['created_at'])
            # Sparse revisions must not silently turn a reply/repost into
            # an original post or trigger an incorrect influencer alert.
            merged['is_reply']=old.get('is_reply',False) or post['is_reply']
            merged['is_repost']=old.get('is_repost',False) or post['is_repost']
            merged['is_backlog']=old.get('is_backlog',post['is_backlog'])
            merged['deleted']=bool(existing['deleted']) if existing else False
            if merged.get('followers') is not None:
                merged['tier']='important' if merged['followers']>=100_000 else 'suivi' if merged['followers']>=50_000 else 'standard'
            db.execute('''INSERT INTO social_posts(id,created_at,received_at,data_json,deleted)
                          VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json''',
                       (post['id'],merged['created_at'],merged['received_at'],json.dumps(merged,ensure_ascii=False),int(merged['deleted'])))
            new_mints=[]
            for mint in merged['mints']:
                cur=db.execute('INSERT OR IGNORE INTO social_mints VALUES(?,?,?)',(post['id'],mint,merged['created_at']))
                if cur.rowcount: new_mints.append(mint)
            return existing is None,new_mints

    def attach_social_mint(self, post_id, mint):
        """Link an authenticated J7 token_meta to its parent post.

        Return None if the parent has not arrived; otherwise a boolean that
        indicates whether a new link was actually created.
        """
        with self.db() as db:
            row=db.execute('SELECT data_json FROM social_posts WHERE id=?',(post_id,)).fetchone()
            if not row:return None
            post=json.loads(row[0])
            if mint in (post.get('mints') or []):return False
            post['mints']=list(dict.fromkeys((post.get('mints') or [])+[mint]))[:8]
            db.execute('UPDATE social_posts SET data_json=? WHERE id=?',
                       (json.dumps(post,ensure_ascii=False),post_id))
            return bool(db.execute('INSERT OR IGNORE INTO social_mints VALUES(?,?,?)',
                                   (post_id,mint,post['created_at'])).rowcount)

    def social_diagnostics(self):
        """Counters based on the stored posts; no JWTs or raw event payloads."""
        with self.db() as db:
            count=db.execute('SELECT COUNT(*) FROM social_posts').fetchone()[0]
            matched=db.execute('SELECT COUNT(DISTINCT s.id),COUNT(*) FROM social_mints s JOIN social_posts p ON p.id=s.id WHERE p.deleted=0').fetchone()
            rows=db.execute('SELECT data_json FROM social_posts ORDER BY received_at DESC LIMIT 500').fetchall()
        sample=[json.loads(row[0]) for row in rows]
        return {'stored_posts':count,'linked_posts':matched[0],
                'mint_mentions':matched[1],
                'last_500_with_tickers':sum(bool(p.get('tickers')) for p in sample),
                'last_500_replies':sum(bool(p.get('is_reply')) for p in sample),
                'last_500_reposts':sum(bool(p.get('is_repost')) for p in sample),
                'sample_size':len(sample)}

    def social_is_backlog(self, id):
        with self.db() as db:
            r=db.execute('SELECT data_json FROM social_posts WHERE id=?',(id,)).fetchone()
        return bool(json.loads(r[0]).get('is_backlog')) if r else False

    def mark_social_deleted(self,id):
        with self.db() as db:
            row=db.execute('SELECT data_json FROM social_posts WHERE id=?',(id,)).fetchone()
            if row:
                post=json.loads(row[0]);post['deleted']=True
                db.execute('UPDATE social_posts SET data_json=?,deleted=1 WHERE id=?',(json.dumps(post,ensure_ascii=False),id))

    def recent_social(self,limit=60):
        with self.db() as db:
            rows=db.execute('SELECT data_json FROM social_posts ORDER BY received_at DESC LIMIT ?', (min(int(limit),200),)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def social_mints_recent(self,seconds=900,limit=10):
        with self.db() as db:
            rows=db.execute('''SELECT mint,MAX(created_at) AS ts FROM social_mints
                                WHERE created_at>=? GROUP BY mint ORDER BY ts DESC LIMIT ?''',
                            (time.time()-seconds,min(25,limit))).fetchall()
        return [x['mint'] for x in rows]

    def social_for_mint(self,mint,limit=8):
        with self.db() as db:
            rows=db.execute('''SELECT p.data_json FROM social_posts p JOIN social_mints s ON s.id=p.id
                                WHERE s.mint=? AND p.deleted=0 ORDER BY p.created_at DESC LIMIT ?''',
                            (mint,min(limit,50))).fetchall()
        return [json.loads(x[0]) for x in rows]
