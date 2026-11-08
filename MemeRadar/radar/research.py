"""Durable discovery queue and forward-only evaluation. Never executes a trade."""
import json
import time
import statistics

HORIZONS = (600, 1200, 3600, 10800, 21600)
SCHEMA = '''
CREATE TABLE IF NOT EXISTS candidate_queue (
 mint TEXT PRIMARY KEY, first_at REAL NOT NULL, event_at REAL NOT NULL,
 next_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 source TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS research_signals (
 mint TEXT PRIMARY KEY, ts REAL NOT NULL, snapshot TEXT NOT NULL,
 last_poll REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS research_prices (
 mint TEXT NOT NULL, ts REAL NOT NULL, price REAL NOT NULL,
 PRIMARY KEY(mint,ts));
CREATE TABLE IF NOT EXISTS research_results (
 mint TEXT NOT NULL, horizon INTEGER NOT NULL, state TEXT NOT NULL,
 observed_at REAL, return_pct REAL, PRIMARY KEY(mint,horizon));
CREATE TABLE IF NOT EXISTS j7_events (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, ts REAL NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS j7_notified (post TEXT, mint TEXT, PRIMARY KEY(post,mint));
CREATE TABLE IF NOT EXISTS x_profiles (
 author_id TEXT PRIMARY KEY, checked_at REAL NOT NULL, profile_json TEXT NOT NULL);
'''

class ResearchStore:
    def init_research(self):
        with self.db() as db: db.executescript(SCHEMA)

    def enqueue(self, mint, source='j7_direct_contract', now=None):
        now = time.time() if now is None else now
        with self.db() as db:
            db.execute('''INSERT INTO candidate_queue(mint,first_at,event_at,next_at,source)
                VALUES(?,?,?,?,?) ON CONFLICT(mint) DO UPDATE SET event_at=excluded.event_at,
                next_at=MIN(candidate_queue.next_at,excluded.next_at),source=CASE WHEN excluded.source='j7_direct_contract' THEN candidate_queue.source ELSE excluded.source END,
                state='pending' ''',(mint,now,now,now,source))

    def queue_due(self, limit=8, now=None):
        now=time.time() if now is None else now
        with self.db() as db:
            return [dict(r) for r in db.execute('''SELECT * FROM candidate_queue
                WHERE next_at<=? AND event_at>=? ORDER BY next_at,event_at LIMIT ?''',
                (now,now-21600,limit))]

    def queue_done(self,mint,found,now=None):
        now=time.time() if now is None else now
        with self.db() as db:
            row=db.execute('SELECT attempts FROM candidate_queue WHERE mint=?',(mint,)).fetchone()
            if row:
                attempts=row[0]+1
                db.execute('UPDATE candidate_queue SET state=?,attempts=?,next_at=? WHERE mint=?',
                    ('analyzed' if found else 'waiting_market',attempts,
                     now+(21600 if found else min(600,20*2**min(attempts,5))),mint))

    def claim_notification(self,post,mint):
        with self.db() as db:
            return bool(db.execute('INSERT OR IGNORE INTO j7_notified VALUES(?,?)',(post,mint)).rowcount)

    def record_event(self,id,kind,data):
        with self.db() as db:
            return bool(db.execute('INSERT OR IGNORE INTO j7_events VALUES(?,?,?,?)',
                (id,kind,time.time(),json.dumps(data,ensure_ascii=False))).rowcount)

    def social_context(self,mint,now=None):
        now=time.time() if now is None else now
        with self.db() as db:
            rows=db.execute('''SELECT p.data_json FROM social_posts p JOIN social_mints s ON s.id=p.id
                WHERE s.mint=? AND p.deleted=0 AND p.created_at>=?''',(mint,now-3600)).fetchall()
        posts=[json.loads(r[0]) for r in rows]
        posts=[p for p in posts if not p.get('is_backlog') and not p.get('is_repost') and not p.get('is_reply')]
        recent={p.get('author_id') or p['author'].lower() for p in posts if p['created_at']>=now-300}
        prior={p.get('author_id') or p['author'].lower() for p in posts if now-600<=p['created_at']<now-300}
        influencers={p.get('author_id') or p['author'].lower() for p in posts
                     if p['created_at']>=now-600 and (p.get('followers') or 0)>=50_000}
        verified={p.get('author_id') or p['author'].lower() for p in posts
                  if p['created_at']>=now-600 and (p.get('followers') or 0)>=50_000
                  and p.get('x_verified') is True
                  and p.get('x_verified_source')=='x_official_api'
                  and not p.get('x_audience_warnings')}
        j7_confirmed={p.get('author_id') or p['author'].lower() for p in posts
                       if p['created_at']>=now-600 and (p.get('followers') or 0)>=50_000
                       and p.get('j7_verified') is True and p.get('j7_parody') is not True
                       and p.get('x_verified') is not False and not p.get('x_audience_warnings')}
        upstream_only=j7_confirmed-verified
        return {'authors_5m':len(recent),'authors_previous_5m':len(prior),
                'acceleration':len(recent)-len(prior),
                'influential_authors_10m':len(influencers),
                'verified_influential_authors_10m':len(verified),
                'j7_badged_authors_10m':len(j7_confirmed),
                'j7_unconfirmed_authors_10m':len(upstream_only),
                'independence':'non vérifiée',
                'mentions':[{'author':p['author'],'url':p['url'],'created_at':p['created_at']} for p in posts[-8:]]}

    def record_signal(self,item,now=None):
        now=time.time() if now is None else now
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO research_signals(mint,ts,snapshot) VALUES(?,?,?)',
                (item['mint'],now,json.dumps(item,ensure_ascii=False)))

    def evaluation_due(self,limit=8,now=None):
        now=time.time() if now is None else now
        with self.db() as db:
            return [r[0] for r in db.execute('''SELECT mint FROM research_signals
                WHERE ts>=? AND last_poll<=? ORDER BY last_poll,ts LIMIT ?''',
                (now-21900,now-30,limit))]

    def observe(self,mint,price,now=None):
        now=time.time() if now is None else now
        with self.db() as db:
            db.execute('UPDATE research_signals SET last_poll=? WHERE mint=?',(now,mint))
            if price and price>0:
                db.execute('INSERT OR IGNORE INTO research_prices VALUES(?,?,?)',(mint,now,price))

    def research_report(self,now=None):
        now=time.time() if now is None else now
        with self.db() as db:
            # Late/missing data stays missing; never substitute a future snapshot silently.
            rows=db.execute('SELECT * FROM research_signals ORDER BY ts DESC').fetchall()
            for r in rows:
                base=json.loads(r['snapshot']).get('price_usd')
                for h in HORIZONS:
                    if now<r['ts']+h: continue
                    obs=db.execute('''SELECT ts,price FROM research_prices WHERE mint=? AND ts>=? AND ts<=?
                        ORDER BY ts LIMIT 1''',(r['mint'],r['ts']+h,r['ts']+h+120)).fetchone()
                    if obs and base and base>0:
                        db.execute('INSERT OR IGNORE INTO research_results VALUES(?,?,?,?,?)',
                            (r['mint'],h,'observed',obs[0],(obs[1]/base-1)*100))
                    elif now>r['ts']+h+120:
                        db.execute('INSERT OR IGNORE INTO research_results VALUES(?,?,?,?,?)',
                            (r['mint'],h,'missing',None,None))
            groups={}
            for r in rows:
                s=json.loads(r['snapshot']); score=s.get('score',0)
                source='J7' if any(x.startswith('j7') for x in s.get('sources',[])) else 'DEX / wallets'
                bucket=f'{int(score//10)*10}–{min(100,int(score//10)*10+9)}'
                for result in db.execute('SELECT * FROM research_results WHERE mint=?',(r['mint'],)):
                    key=(source,s.get('regime','inconnu'),bucket,result['horizon'])
                    g=groups.setdefault(key,{'source':source,'regime':key[1],'bucket':bucket,
                        'minutes':key[3]//60,'values':[],'missing':0})
                    if result['state']=='observed':g['values'].append(result['return_pct'])
                    else:g['missing']+=1
            summary=[]
            for g in groups.values():
                values=g.pop('values'); n=len(values)
                g.update(n=n,median_pct=statistics.median(values) if values else None,
                         positive_pct=100*sum(v>0 for v in values)/n if n else None,
                         calibration='Non calibré')
                summary.append(g)
            queue=dict(db.execute('SELECT state,COUNT(*) FROM candidate_queue WHERE event_at>=? GROUP BY state',(now-21600,)).fetchall())
            return {'total':len(rows),'groups':summary,'queue':queue,
                    'note':'Rendements indicatifs depuis la première analyse v6 ; aucune sortie automatique. Coûts et exécution non mesurés.'}

    def research_for(self,mint):
        with self.db() as db:
            r=db.execute('SELECT * FROM research_signals WHERE mint=?',(mint,)).fetchone()
            if not r:return None
            points=db.execute('SELECT MIN(price),MAX(price),COUNT(*) FROM research_prices WHERE mint=?',(mint,)).fetchone()
            s=json.loads(r['snapshot']); base=s.get('price_usd')
            return {'at':r['ts'],'initial_score':s.get('score'),'initial_status':s.get('status'),
                    'initial_patterns':s.get('patterns',[]),'samples':points[2],
                    'min_pct':(points[0]/base-1)*100 if points[0] and base else None,
                    'max_pct':(points[1]/base-1)*100 if points[1] and base else None,
                    'outcomes':[dict(x) for x in db.execute('SELECT * FROM research_results WHERE mint=? ORDER BY horizon',(mint,))]}
