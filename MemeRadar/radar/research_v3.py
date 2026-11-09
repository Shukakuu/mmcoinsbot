"""V3 prospective research: migration-safe, outage-aware, disjoint time windows.

No missing quote is automatically -100%. These are *observations*, not fills.
All old V2 results remain in their own tables (never mixed with V3).
"""
import json, math, statistics, time

HORIZONS = (300, 600, 1200, 3600)
TOLERANCE = 85  # symmetrical and disjoint; one quote cannot fill two horizons
SCHEMA = '''
CREATE TABLE IF NOT EXISTS research_v3_events (
 id INTEGER PRIMARY KEY, mint TEXT NOT NULL, pool TEXT, at REAL NOT NULL,
 reference REAL NOT NULL, kind TEXT NOT NULL, cohort TEXT NOT NULL,
 regime TEXT NOT NULL, age_band TEXT NOT NULL, size_band TEXT NOT NULL,
 score REAL, payload_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_rv3_events ON research_v3_events(mint,at);
CREATE TABLE IF NOT EXISTS research_v3_outcomes (
 event_id INTEGER NOT NULL, horizon INTEGER NOT NULL, state TEXT NOT NULL,
 at REAL NOT NULL, price REAL NOT NULL, return_pct REAL NOT NULL, pool TEXT,
 PRIMARY KEY(event_id,horizon));
CREATE TABLE IF NOT EXISTS research_v3_heartbeat (at REAL PRIMARY KEY);
CREATE TABLE IF NOT EXISTS research_v3_probe (mint TEXT PRIMARY KEY, at REAL NOT NULL);
'''


def band(age, size, curve):
    age_band = ('0-5m' if age is not None and age<=5 else
                '5-30m' if age is not None and age<=30 else
                '30-180m' if age is not None and age<=180 else 'older')
    # Curve size = cap; pool size = actual liquidity. Never confuse the two.
    size_band = ('unknown' if size is None else '<5k' if size<5000 else
                 '5k-25k' if size<25000 else '25k-100k' if size<100000 else '100k+')
    return age_band, size_band


def wilson_positive(values):
    n=len(values)
    if not n:return None
    k=sum(v>0 for v in values)
    z=1.96; p=k/n; d=1+z*z/n
    center=(p+z*z/(2*n))/d
    spread=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [round(max(0,center-spread)*100,1),round(min(1,center+spread)*100,1)]


class ResearchV3:
    def init_research_v3(self):
        with self.db() as db:db.executescript(SCHEMA)

    def heartbeat_v3(self, at=None):
        at=time.time() if at is None else at
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO research_v3_heartbeat(at) VALUES(?)',(at,))
            # Bounded heartbeat history, once a day worth of signals is enough for current report.
            if int(at)%3600<30:
                db.execute('DELETE FROM research_v3_heartbeat WHERE at<?',(at-14*86400,))

    def record_v3(self, item, previous=None, now=None):
        now=time.time() if now is None else now
        previous=previous or {}
        price=item.get('price_usd')
        if not isinstance(price,(float,int)) or not math.isfinite(price) or price<=0 or not item.get('mint'):return
        if item.get('risks'):return  # unsafe coins do not contaminate control cohort
        safety=item.get('safety_summary') or {}
        # Early observational signals must be measurable even BEFORE RugCheck
        # responds. Older signals and controls still require verified safety.
        safety_ok=(safety.get('mint_active') is False and
                   safety.get('freeze_active') is False and
                   safety.get('rugcheck_score') is not None)
        curve=item.get('score_method')=='curve_experimentale'
        regime='curve' if curve else 'amm'
        size=(item.get('market_cap_usd') or item.get('fdv_usd')) if curve else item.get('liquidity_usd')
        age_band,size_band=band(item.get('age_min'),size,curve)
        kinds=[]
        if item.get('early_watch') and not previous.get('early_watch'):
            kinds.append(('veille_precoce','alert'))
        if safety_ok and item.get('curve_candidate') and not previous.get('curve_candidate'):
            kinds.append(('courbe_precoce','alert'))
        if safety_ok and item.get('prewatch') and not previous.get('prewatch'):
            kinds.append(('pression_initiale','alert'))
        if safety_ok and item.get('pre_impulse') and not previous.get('pre_impulse'):
            kinds.append(('pression_confirmee','alert'))
        if safety_ok and item.get('status')=='a_etudier' and previous.get('status')!='a_etudier':
            kinds.append(('a_etudier','alert'))
        if safety_ok and not kinds and not previous and item.get('status')=='surveillance' and item.get('coverage',0)>=70:
            kinds.append(('temoin_surveillance','control'))
        if not kinds:return
        # Snapshot the evidence as it was at alert time. Safety cache can be
        # overwritten later; without this an apparent rug cannot be audited.
        payload={k:item.get(k) for k in
                 ('score','coverage','sources','market_quote_at','quote_lag_s','risks',
                  'safety_summary','liquidity_usd','market_cap_usd','volume_m5_usd',
                  'pressure_buys_m5','pressure_sells_m5','change_m5_pct','score_method',
                  'curve_candidate','pre_impulse','early_watch','early_watch_evidence',
                  'narrative_matches','priority_score','attention_score',
                  'analysis_version','decision_method','strategy_decisions',
                  'security_gate','safety_checked_at','world_context')}
        with self.db() as db:
            for kind,cohort in kinds:
                exists=db.execute('SELECT 1 FROM research_v3_events WHERE mint=? AND kind=? AND at>? LIMIT 1',
                                  (item['mint'],kind,now-4*3600)).fetchone()
                if exists:continue
                db.execute('''INSERT INTO research_v3_events
                    (mint,pool,at,reference,kind,cohort,regime,age_band,size_band,score,payload_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                    (item['mint'],item.get('pair_address'),now,price,kind,cohort,
                     regime,age_band,size_band,item.get('score'),json.dumps(payload,ensure_ascii=False)))

    def observation_v3(self,mint,pool,price,at=None):
        at=time.time() if at is None else at
        if not isinstance(price,(int,float)) or price<=0 or not math.isfinite(price):return
        with self.db() as db:
            rows=db.execute('SELECT id,at,reference,pool FROM research_v3_events WHERE mint=?',(mint,)).fetchall()
            for event in rows:
                for horizon in HORIZONS:
                    target=event['at']+horizon
                    if abs(at-target)>TOLERANCE:continue
                    old=db.execute('SELECT at FROM research_v3_outcomes WHERE event_id=? AND horizon=?',
                                   (event['id'],horizon)).fetchone()
                    if old and abs(old['at']-target)<=abs(at-target):continue
                    state='migrated_pool' if pool and event['pool'] and pool!=event['pool'] else 'observed'
                    db.execute('''INSERT INTO research_v3_outcomes
                         (event_id,horizon,state,at,price,return_pct,pool)
                         VALUES(?,?,?,?,?,?,?) ON CONFLICT(event_id,horizon) DO UPDATE SET
                         state=excluded.state,at=excluded.at,price=excluded.price,
                         return_pct=excluded.return_pct,pool=excluded.pool''',
                         (event['id'],horizon,state,at,price,(price/event['reference']-1)*100,pool))

    def due_v3(self,now=None,limit=12):
        now=time.time() if now is None else now
        with self.db() as db:
            rows=db.execute('''SELECT DISTINCT e.mint FROM research_v3_events e
                JOIN (SELECT 300 AS horizon UNION ALL SELECT 600 UNION ALL SELECT 1200 UNION ALL SELECT 3600) h
                LEFT JOIN research_v3_outcomes o ON o.event_id=e.id AND o.horizon=h.horizon
                LEFT JOIN research_v3_probe p ON p.mint=e.mint
                WHERE o.event_id IS NULL AND e.at+h.horizon BETWEEN ? AND ?
                  AND (p.at IS NULL OR p.at<?)
                ORDER BY e.at+h.horizon LIMIT ?''',
                (now-TOLERANCE,now+TOLERANCE,now-20,limit)).fetchall()
            for row in rows:
                db.execute('INSERT INTO research_v3_probe VALUES (?,?) ON CONFLICT(mint) DO UPDATE SET at=excluded.at',
                           (row[0],now))
        return [r[0] for r in rows]

    def report_v3(self,now=None):
        now=time.time() if now is None else now
        with self.db() as db:
            events=db.execute('SELECT * FROM research_v3_events').fetchall()
            outcomes=db.execute('SELECT * FROM research_v3_outcomes').fetchall()
            beats=[r[0] for r in db.execute('SELECT at FROM research_v3_heartbeat WHERE at<=? ORDER BY at',(now,))]
        measured={(row['event_id'],row['horizon']):row for row in outcomes}
        summary={}
        for e in events:
            for h in HORIZONS:
                target=e['at']+h
                if target+TOLERANCE>now:continue
                # Only compare among regimes and similar age/size; no causal claim.
                key=(e['regime'],e['age_band'],e['size_band'],e['cohort'],e['kind'],h)
                g=summary.setdefault(key,{'regime':e['regime'],'age_band':e['age_band'],
                    'size_band':e['size_band'],'cohort':e['cohort'],'signal':e['kind'],
                    'minutes':h//60,'count':0,'offline':0,'unquoted':0,'migrations':0,'values':[]})
                g['count']+=1
                o=measured.get((e['id'],h))
                if o:
                    g['values'].append(o['return_pct'])
                    if o['state']=='migrated_pool':g['migrations']+=1
                elif not any(abs(b-target)<=150 for b in beats):
                    g['offline']+=1  # paused bot; DO NOT count as a loss
                else:g['unquoted']+=1  # running but no executable/confirmed quote
        groups=[]
        for g in summary.values():
            vals=g.pop('values'); n=len(vals)
            g.update(n_observed=n,valid_rate_pct=round(100*n/g['count'],1),
                observed_median=round(statistics.median(vals),2) if vals else None,
                observed_mean=round(statistics.mean(vals),2) if vals else None,
                positive_observed=sum(v>0 for v in vals),positive_rate_ci95=wilson_positive(vals),
                note='Observation non exécutable; les non-cotés ne valent pas automatiquement −100 %.')
            groups.append(g)
        return {'version':3,'total_events':len(events),'groups':groups,'horizons_min':[5,10,20,60],
            'note':'Données prospectives V3 (séparées des anciennes V2). Migrations suivies par mint, horizons ±85 s sans recouvrement, périodes hors-ligne censurées. Contrôles sûrs, appariement descriptif par régime/âge/taille ; aucune probabilité ou rentabilité validée.'}

    def research_for_v3(self,mint):
        with self.db() as db:
            events=db.execute('SELECT * FROM research_v3_events WHERE mint=? ORDER BY at DESC LIMIT 12',(mint,)).fetchall()
            out=[]
            for e in events:
                results=[dict(x) for x in db.execute('SELECT horizon,state,at AS observed_at,price,return_pct,pool FROM research_v3_outcomes WHERE event_id=? ORDER BY horizon',(e['id'],)).fetchall()]
                out.append({'at':e['at'],'reference_price':e['reference'],'pair':e['pool'],
                    'kind':e['kind'],'cohort':e['cohort'],'score_at_signal':e['score'],'outcomes':results})
        return {'version':3,'events':out}
