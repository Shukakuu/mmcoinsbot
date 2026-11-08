"""Independent, read-only launch ledger and delayed quote observation.

Every detected launch is kept briefly, but only narrative matches and a
DETERMINISTIC random control cohort receive follow-up quotes. No orders,
private keys or unpriced 'safe' labels. Never converts SOL market cap to USD.
"""
from __future__ import annotations
import hashlib
import json
import math
import sqlite3
import threading
import time
from contextlib import contextmanager
from .narrative_intelligence import watch_evidence
from .social import is_solana_address

SCHEMA_VERSION = 9
SCHEMA = '''
CREATE TABLE IF NOT EXISTS live_launches (
 mint TEXT PRIMARY KEY, first_at REAL NOT NULL, last_at REAL NOT NULL,
 name TEXT NOT NULL, symbol TEXT NOT NULL, platform TEXT NOT NULL,
 creator TEXT NOT NULL DEFAULT '', signature TEXT NOT NULL DEFAULT '',
 market_cap_sol REAL, initial_buy_sol REAL, virtual_sol REAL, virtual_token REAL,
 matched INTEGER NOT NULL DEFAULT 0, control_cohort INTEGER NOT NULL DEFAULT 0,
 evidence_json TEXT NOT NULL DEFAULT '[]');
CREATE INDEX IF NOT EXISTS idx_live_launches_at ON live_launches(first_at DESC);
CREATE INDEX IF NOT EXISTS idx_live_launches_groups ON live_launches(matched,control_cohort,first_at);
CREATE TABLE IF NOT EXISTS live_price_samples (
 mint TEXT NOT NULL, observed_at REAL NOT NULL, price_usd REAL NOT NULL,
 liquidity_usd REAL, pair_address TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(mint,observed_at));
CREATE INDEX IF NOT EXISTS idx_live_price_samples_at ON live_price_samples(mint,observed_at);
CREATE TABLE IF NOT EXISTS live_risk_observations (
 mint TEXT PRIMARY KEY, checked_at REAL NOT NULL, details_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS live_quote_jobs (
 mint TEXT PRIMARY KEY, next_due REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 completed INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_live_quote_due ON live_quote_jobs(completed,next_due);
'''


def positive(value):
    try:
        if value is None or isinstance(value, bool):return None
        n=float(value)
        return n if math.isfinite(n) and n > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def normalize_launch(obj):
    if not isinstance(obj,dict) or not is_solana_address(obj.get('mint')):
        return None
    return {
        'mint':obj['mint'], 'name':str(obj.get('name') or '?')[:80],
        'symbol':str(obj.get('symbol') or '?')[:25],
        'creator':str(obj.get('traderPublicKey') or obj.get('creator') or '')[:50],
        'signature':str(obj.get('signature') or '')[:120],
        'market_cap_sol':positive(obj.get('marketCapSol')),
        'initial_buy_sol':positive(obj.get('solAmount')),
        'virtual_sol':positive(obj.get('vSolInBondingCurve')),
        'virtual_token':positive(obj.get('vTokensInBondingCurve')),
        'platform':str(obj.get('pool') or 'pumpfun')[:30],
    }


def is_control(mint, divisor=30):
    """Stable blind sample chosen independent of a token's outcome or name."""
    return int.from_bytes(hashlib.sha256(mint.encode('ascii')).digest()[:8], 'big') % divisor == 0


class RealtimeStore:
    def init_realtime(self):
        # Original constructors have already created legacy tables. Migrations
        # are idempotent; user_version is bumped only after successful DDL.
        with self.db() as db:
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError('Base créée avec une version de MemeRadar plus récente')
            db.executescript(SCHEMA)
            if version<9:
                # v8 wrote initialBuy into a column labelled SOL; unit was unverified.
                db.execute('UPDATE live_launches SET initial_buy_sol=NULL')
            db.execute('PRAGMA user_version='+str(SCHEMA_VERSION))

    @contextmanager
    def live_db(self, write=False):
        # Independent short-lived WAL connection: no legacy Python-wide DB lock.
        conn=sqlite3.connect(self.path,timeout=8,isolation_level=None)
        conn.row_factory=sqlite3.Row
        try:
            conn.execute('PRAGMA busy_timeout=8000')
            if write:conn.execute('BEGIN IMMEDIATE')
            yield conn
            if write:conn.commit()
        except Exception:
            if write:conn.rollback()
            raise
        finally:
            conn.close()

    def live_launch(self, data, evidence=(), at=None, control=None):
        """Insert launch, preserve earliest evidence, return materialization flags."""
        if not data or not is_solana_address(data.get('mint')):
            return {'new':False,'matched':False,'control':False}
        at=time.time() if at is None else float(at)
        matched=bool(evidence)
        control=is_control(data['mint']) if control is None else bool(control)
        ev=json.dumps(list(evidence)[:5],ensure_ascii=False)
        with self.live_db(True) as db:
            r=db.execute('SELECT matched,control_cohort FROM live_launches WHERE mint=?', (data['mint'],)).fetchone()
            if r is None:
                db.execute('''INSERT INTO live_launches(mint,first_at,last_at,name,symbol,platform,creator,signature,
                    market_cap_sol,initial_buy_sol,virtual_sol,virtual_token,matched,control_cohort,evidence_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
                    data['mint'],at,at,data.get('name','?'),data.get('symbol','?'),data.get('platform','pumpfun'),
                    data.get('creator',''),data.get('signature',''),positive(data.get('market_cap_sol')),
                    positive(data.get('initial_buy_sol')),positive(data.get('virtual_sol')),
                    positive(data.get('virtual_token')),int(matched),int(control),ev))
                if matched or control:
                    db.execute('INSERT OR IGNORE INTO live_quote_jobs(mint,next_due) VALUES(?,?)',(data['mint'],at+15))
            # Cohort assignment is frozen at first receipt: no retroactive social label.
            return {'new':r is None,'matched':matched if r is None else bool(r['matched']),
                    'control':control if r is None else bool(r['control_cohort'])}

    def live_due(self, limit=8, at=None):
        now=time.time() if at is None else at
        with self.live_db() as db:
            rows=db.execute('''SELECT j.mint,j.attempts,l.first_at,l.matched,l.control_cohort
              FROM live_quote_jobs j JOIN live_launches l USING(mint)
              WHERE j.completed=0 AND j.next_due<=? ORDER BY j.next_due ASC,l.matched DESC LIMIT ?''',
              (now,min(30,max(1,limit)))).fetchall()
        return [dict(x) for x in rows]

    def live_quote_result(self,mint,quote,at=None,error=''):
        now=time.time() if at is None else at
        p=positive((quote or {}).get('priceUsd'))
        liq=positive(((quote or {}).get('liquidity') or {}).get('usd'))
        with self.live_db(True) as db:
            r=db.execute('SELECT j.attempts,l.first_at FROM live_quote_jobs j JOIN live_launches l USING(mint) WHERE j.mint=?',
                         (mint,)).fetchone()
            if r is None:return False
            if p:
                db.execute('''INSERT OR IGNORE INTO live_price_samples VALUES(?,?,?,?,?)''',
                    (mint,now,p,liq,str((quote or {}).get('pairAddress') or '')[:80]))
            attempts=r['attempts']+1
            # Continue sampling even after first quote: outcomes must use measured
            # observations at each future horizon, not the future peak.
            age=max(0,now-r['first_at'])
            done=age>=21840 or attempts>=400
            delay=15 if age<60 else 60 if age<600 else 90
            db.execute('''UPDATE live_quote_jobs SET attempts=?,next_due=?,completed=?,last_error=? WHERE mint=?''',
                      (attempts,now+delay,int(done),str(error)[:80],mint))
        return p is not None

    def live_recent(self,limit=20):
        with self.live_db() as db:
            rows=db.execute('''SELECT l.*, r.checked_at AS risk_checked_at,r.details_json AS risk_json, (SELECT MIN(s.observed_at) FROM live_price_samples s
                      WHERE s.mint=l.mint) AS first_quote_at,
                      (SELECT s.price_usd FROM live_price_samples s WHERE s.mint=l.mint
                       ORDER BY s.observed_at DESC LIMIT 1) AS last_price_usd
                      FROM live_launches l LEFT JOIN live_risk_observations r USING(mint) WHERE l.matched=1 ORDER BY l.last_at DESC LIMIT ?''',
                      (max(1,min(limit,100)),)).fetchall()
        out=[]
        for r in rows:
            d=dict(r);d['evidence']=json.loads(d.pop('evidence_json') or '[]');
            risk=d.pop('risk_json');checked=d.pop('risk_checked_at')
            d['onchain_risk']=dict(json.loads(risk),checked_at=checked) if risk else None
            out.append(d)
        return out

    def record_live_risk(self,mint,details,at=None):
        now=time.time() if at is None else at
        with self.live_db(True) as db:
            db.execute('INSERT OR REPLACE INTO live_risk_observations(mint,checked_at,details_json) VALUES(?,?,?)',
                       (mint,now,json.dumps(details,ensure_ascii=False)))

    def live_risk(self,mint):
        with self.live_db() as db:
            r=db.execute('SELECT checked_at,details_json FROM live_risk_observations WHERE mint=?',(mint,)).fetchone()
        return dict(json.loads(r['details_json']),checked_at=r['checked_at']) if r else None

    def live_prune(self,now=None,days=7):
        now=time.time() if now is None else now
        cutoff=now-days*86400
        # Never delete the historical coins or old research/alerts.
        with self.live_db(True) as db:
            for table in ('live_price_samples','live_quote_jobs','live_risk_observations'):
                db.execute('DELETE FROM '+table+' WHERE mint IN (SELECT mint FROM live_launches WHERE first_at<?)',(cutoff,))
            db.execute('DELETE FROM live_launches WHERE first_at<?',(cutoff,))

    def live_health(self):
        with self.live_db() as db:
            a=db.execute('''SELECT COUNT(*) AS total, SUM(matched) AS matched,
              SUM(control_cohort) AS controls, MAX(first_at) AS last_at FROM live_launches''').fetchone()
            b=db.execute('SELECT COUNT(*) FROM live_quote_jobs WHERE completed=0').fetchone()[0]
            c=db.execute('SELECT COUNT(DISTINCT mint) FROM live_price_samples').fetchone()[0]
        return {'total':a['total'],'matched':a['matched'] or 0,'controls':a['controls'] or 0,
                'last_at':a['last_at'],'pending_quotes':b,'quoted_tokens':c,
                'note':'Prix DEX ultérieurs seulement ; lancement en SOL, sans prix USD vérifié.'}


def outcome_for_samples(samples, first_at, horizon, lag=30, tolerance=130):
    """No look-ahead: choose first observed quote AFTER each target, never peak.

    Entry begins 30 seconds AFTER discovery (manual delay). Both entry and
    exit require actually observed USD quotes. No extrapolation or fill.
    """
    samples=sorted((float(ts),float(p)) for ts,p in samples if positive(p) is not None)
    entry=min(((ts,p) for ts,p in samples if first_at+lag<=ts<=first_at+lag+tolerance),default=None)
    end=min(((ts,p) for ts,p in samples if first_at+horizon<=ts<=first_at+horizon+tolerance),default=None)
    if entry is None or end is None or end[0]<=entry[0]:return None
    return round((end[1]/entry[1]-1)*100,4)


def cohort_summary(rows, horizon=300):
    """Descriptive only; no calibration, no claim of executable returns."""
    import statistics
    result={}
    for key in ('matched','controls'):
        sample=[x['return_pct'] for x in rows if x['group']==key and x['return_pct'] is not None]
        result[key]={'observations':len(sample),'median_price_change_pct':round(statistics.median(sample),2) if sample else None,
                     'positive_quotes':sum(v>0 for v in sample)}
    return result


def compare_cohorts(store,horizon=300,now=None):
    """Blind time/platform/cap matched controls, without peeking at outcomes.

    Missing quotes remain missing; matching never uses future prices.
    """
    now=time.time() if now is None else now
    with store.live_db() as db:
        launches=[dict(r) for r in db.execute('SELECT mint,first_at,matched,control_cohort,platform,market_cap_sol FROM live_launches WHERE first_at<=? AND first_at>=? AND (matched=1 OR control_cohort=1) ORDER BY first_at DESC LIMIT 3000',(now-horizon-180,now-8*86400)).fetchall()]
        signals=[r for r in launches if r['matched']]
        controls=[r for r in launches if not r['matched'] and r['control_cohort']]
        used=set();pairs=[]
        for signal in signals:
            candidates=[]
            for c in controls:
                if c['mint'] in used or c['platform']!=signal['platform'] or abs(c['first_at']-signal['first_at'])>900:
                    continue
                a=positive(signal['market_cap_sol']);b=positive(c['market_cap_sol'])
                if a is not None and b is not None and not (a/3<=b<=a*3):continue
                candidates.append(c)
            if not candidates:continue
            c=min(candidates,key=lambda r:(abs(r['first_at']-signal['first_at']),r['mint']))
            used.add(c['mint']);pairs.append((signal,c))
        results=[]
        for signal,control in pairs:
            for launch,group in ((signal,'matched'),(control,'controls')):
                samples=db.execute('SELECT observed_at,price_usd FROM live_price_samples WHERE mint=? ORDER BY observed_at',(launch['mint'],)).fetchall()
                ret=outcome_for_samples([(x[0],x[1]) for x in samples],launch['first_at'],horizon)
                results.append({'group':group,'return_pct':ret})
    return {'horizon_seconds':horizon,'entry_delay_seconds':30,'comparison':cohort_summary(results,horizon),
        'candidate_signals':len(signals),'matched_pairs':len(pairs),'unmatched_signals':len(signals)-len(pairs),
        'unpriced_or_missing':sum(r['return_pct'] is None for r in results),
        'valid_for_trading':False,
        'caveat':'Descriptif, témoins appariés par heure ±15 min, plateforme et cap initiale ×3 si connue. Sans frais, slippage, contrôle causal ni garantie de revente.'}


class LaunchQuoteWorker:
    def __init__(self,store,stop_event,get_pairs=None):
        self.store=store;self.stop_event=stop_event;self.get_pairs=get_pairs
        self.status={'running':False,'batches':0,'quoted':0,'last_error':None}
    def run_once(self,now=None):
        from .providers import dex_pairs_batch
        due=self.store.live_due(30,now)
        if not due:return 0
        f=self.get_pairs or dex_pairs_batch
        try:quotes=f([d['mint'] for d in due]);self.status['last_error']=None
        except Exception as exc:
            quotes={};self.status['last_error']=type(exc).__name__
        for d in due:
            if self.store.live_quote_result(d['mint'],quotes.get(d['mint']) or {},at=now,error=self.status['last_error'] or ''):
                self.store.update_provisional_quote(d['mint'],quotes[d['mint']],now=now)
                self.status['quoted']+=1
        self.status['batches']+=1
        return len(due)
    def run(self):
        self.status['running']=True
        try:
            while not self.stop_event.is_set():
                self.run_once()
                self.stop_event.wait(4)
        finally:self.status['running']=False
