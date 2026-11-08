"""Prospective observations anchored to the exact alert time, not initial token discovery.

Missing liquidity/quote data are censored, not magically profitable nor automatically -100%.
Do not mix the legacy research_signals table with v2 cohorts.
"""
import json
import statistics
import time

HORIZONS_V2 = (300, 600, 1200, 3600)
EARLY_S = 90
LATE_S = 300
SCHEMA_V2 = '''
CREATE TABLE IF NOT EXISTS research_events_v2 (
 id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT NOT NULL, pool TEXT NOT NULL,
 at REAL NOT NULL, reference REAL NOT NULL, kind TEXT NOT NULL,
 cohort TEXT NOT NULL, score REAL, age_min REAL, liquidity REAL,
 payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_research_v2_mint ON research_events_v2(mint,at);
CREATE TABLE IF NOT EXISTS research_outcomes_v2 (
 event_id INTEGER NOT NULL, horizon INTEGER NOT NULL, state TEXT NOT NULL,
 observed_at REAL, price REAL, return_pct REAL,
 PRIMARY KEY(event_id,horizon));
CREATE TABLE IF NOT EXISTS research_probes_v2 (
 mint TEXT PRIMARY KEY, last_probe REAL NOT NULL);
'''

class ResearchV2:
    def init_research_v2(self):
        with self.db() as db: db.executescript(SCHEMA_V2)

    def record_research_event(self, item, previous=None, now=None):
        now = time.time() if now is None else now
        price=item.get('price_usd')
        pool=item.get('pair_address')
        if not isinstance(price,(int,float)) or price<=0 or not pool: return
        previous=previous or {}
        kinds=[]
        if not previous and not item.get('prewatch') and item.get('status')!='a_etudier':
            kinds.append(('baseline','control'))
        if item.get('prewatch') and not previous.get('prewatch') and not item.get('risks'):
            kinds.append(('pression_initiale','alert'))
        if item.get('pre_impulse') and not previous.get('pre_impulse') and not item.get('risks'):
            kinds.append(('pression_confirmee','alert'))
        if item.get('status')=='a_etudier' and previous.get('status')!='a_etudier':
            kinds.append(('a_etudier','alert'))
        if not kinds:return
        payload={k:item.get(k) for k in ('score','coverage','age_min','liquidity_usd','patterns','prewatch','pre_impulse','sources','risks','market_quote_at','quote_lag_s')}
        with self.db() as db:
            for kind,cohort in kinds:
                recent=db.execute('SELECT 1 FROM research_events_v2 WHERE mint=? AND pool=? AND kind=? AND cohort=? AND at>? LIMIT 1',
                    (item['mint'],pool,kind,cohort,now-4*3600)).fetchone()
                if recent: continue
                db.execute('''INSERT INTO research_events_v2
                    (mint,pool,at,reference,kind,cohort,score,age_min,liquidity,payload)
                    VALUES(?,?,?,?,?,?,?,?,?,?)''',
                    (item['mint'],pool,now,price,kind,cohort,item.get('score'),item.get('age_min'),
                     item.get('liquidity_usd'),json.dumps(payload,ensure_ascii=False)))

    def observation_v2(self, mint, pair, price, liquidity, at=None):
        at=time.time() if at is None else at
        if not pair: return
        with self.db() as db:
            for event in db.execute('SELECT id,at,reference FROM research_events_v2 WHERE mint=? AND pool=?',(mint,pair)).fetchall():
                for horizon in HORIZONS_V2:
                    target=event['at']+horizon
                    if not target-EARLY_S<=at<=target+LATE_S: continue
                    existing=db.execute('SELECT * FROM research_outcomes_v2 WHERE event_id=? AND horizon=?',
                                        (event['id'],horizon)).fetchone()
                    if existing and existing['observed_at'] is not None and abs(existing['observed_at']-target)<=abs(at-target):
                        continue
                    if liquidity is not None and liquidity<=0:
                        state,ret,observed='sans_liquidite',-100.0,price
                    elif isinstance(price,(int,float)) and price>0:
                        state,ret,observed='observed',(price/event['reference']-1)*100,price
                    else:
                        continue
                    db.execute('''INSERT INTO research_outcomes_v2 VALUES(?,?,?,?,?,?)
                        ON CONFLICT(event_id,horizon) DO UPDATE SET
                        state=excluded.state,observed_at=excluded.observed_at,
                        price=excluded.price,return_pct=excluded.return_pct''',
                        (event['id'],horizon,state,at,observed,ret))

    def evaluation_due_v2(self, limit=20, now=None):
        now=time.time() if now is None else now
        with self.db() as db:
            due=db.execute('''SELECT DISTINCT e.mint FROM research_events_v2 e
                JOIN (SELECT 300 AS h UNION ALL SELECT 600 UNION ALL SELECT 1200 UNION ALL SELECT 3600) horizons
                LEFT JOIN research_outcomes_v2 o ON o.event_id=e.id AND o.horizon=horizons.h
                LEFT JOIN research_probes_v2 p ON p.mint=e.mint
                WHERE o.event_id IS NULL AND e.at+horizons.h BETWEEN ? AND ?
                AND (p.last_probe IS NULL OR p.last_probe<?)
                ORDER BY e.at+horizons.h LIMIT ?''',
                (now-LATE_S,now+EARLY_S,now-25,limit)).fetchall()
            for row in due:
                db.execute('''INSERT INTO research_probes_v2(mint,last_probe) VALUES(?,?)
                    ON CONFLICT(mint) DO UPDATE SET last_probe=excluded.last_probe''',(row[0],now))
            return [r[0] for r in due]

    def research_report_v2(self, now=None):
        now=time.time() if now is None else now
        with self.db() as db:
            rows=db.execute('SELECT * FROM research_events_v2 ORDER BY at DESC').fetchall()
            results=db.execute('SELECT * FROM research_outcomes_v2').fetchall()
            outcomes={(r['event_id'],r['horizon']):dict(r) for r in results}
            groups={}
            for event in rows:
                for h in HORIZONS_V2:
                    if now<event['at']+h+LATE_S:continue
                    age=event['age_min']
                    ageband=('0-5min' if age is not None and age<=5 else '5-30min'
                        if age is not None and age<=30 else '30-180min'
                        if age is not None and age<=180 else '>180min' if age is not None else 'inconnu')
                    liq=event['liquidity']
                    liqband=('<5k' if liq is not None and liq<5000 else '5-25k'
                        if liq is not None and liq<25000 else '25-100k'
                        if liq is not None and liq<100000 else '>100k' if liq is not None else 'inconnue')
                    key=(event['cohort'],event['kind'],h,ageband,liqband)
                    g=groups.setdefault(key,{'cohort':event['cohort'],'signal':event['kind'],'minutes':h//60,
                                             'age_paire':ageband,'classe_liquidite':liqband,
                                             'values':[],'missing':0,'illiquid':0,'count':0})
                    g['count']+=1
                    outcome=outcomes.get((event['id'],h))
                    if outcome and outcome['state']=='observed': g['values'].append(outcome['return_pct'])
                    elif outcome and outcome['state']=='sans_liquidite': g['illiquid']+=1
                    else: g['missing']+=1
            summary=[]
            for group in groups.values():
                observed=group.pop('values')
                count=group['count']
                # Missing/unquoted observations CANNOT be silently removed from the denominator.
                lower=observed+[-100.0]*(group['missing']+group['illiquid'])
                upper=observed+[0.0]*group['missing']+[-100.0]*group['illiquid']
                group.update(n_observed=len(observed),
                             observed_median=round(statistics.median(observed),2) if observed else None,
                             pessimistic_median=round(statistics.median(lower),2) if lower else None,
                             missing_neutral_median=round(statistics.median(upper),2) if upper else None,
                             positive_observed=len([v for v in observed if v>0]),
                             valid_rate_pct=round(100*len(observed)/count,1) if count else 0)
                summary.append(group)
        return {'version':2,'total_events':len(rows),'groups':summary,
                'horizons_min':[h//60 for h in HORIZONS_V2],
                'note':('Prospectif v6.8 : prix/heure au premier signal exact, horizon −90/+300 s, même pool. '
                        '« Sans liquidité » vaut -100 % dans le scénario de sortie; les données manquantes sont '
                        'présentées avec deux sensibilités, jamais assimilées à des gains. '
                        'Groupe témoin descriptif, NON apparié ni causal; aucune rentabilité prouvée.')}

    def research_for_v2(self,mint):
        with self.db() as db:
            events=db.execute('SELECT * FROM research_events_v2 WHERE mint=? ORDER BY at DESC LIMIT 12',(mint,)).fetchall()
            out=[]
            for e in events:
                outcomes=[dict(r) for r in db.execute('SELECT horizon,state,observed_at,price,return_pct FROM research_outcomes_v2 WHERE event_id=? ORDER BY horizon',(e['id'],)).fetchall()]
                out.append({'at':e['at'],'reference_price':e['reference'],'pair':e['pool'],'kind':e['kind'],
                            'cohort':e['cohort'],'score_at_signal':e['score'],'outcomes':outcomes})
            return {'version':2,'events':out}
