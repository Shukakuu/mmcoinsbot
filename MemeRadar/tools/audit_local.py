"""Read-only local database audit. No API request, no trades, no token dump.

Run from MemeRadar/: py -3 tools/audit_local.py --hours 2
"""
import argparse
import collections
import datetime
import json
import sqlite3
import statistics
import sys
from pathlib import Path


def audit(path, hours=2):
    url=Path(path).resolve().as_uri().replace('file://','file:')
    db=sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    def count(t):return db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] if t in tables else 0
    def range_(t,column):
        if t not in tables:return (None,None)
        return tuple(db.execute(f'SELECT MIN({column}),MAX({column}) FROM {t}').fetchone())
    cmax=range_('coins','last_seen')[1]
    cutoff=(cmax or 0)-hours*3600
    n=count('coins')
    rows=[json.loads(r[0]) for r in db.execute('SELECT data_json FROM coins')] if 'coins' in tables else []
    stat=collections.Counter(c.get('status') for c in rows)
    vers=collections.Counter(c.get('analysis_version','ancienne') for c in rows)
    latest=[c for c in rows if c.get('last_seen',0)>=cutoff]
    social_count=count('social_posts'); linked_count=count('social_mints')
    posts=[json.loads(r[0]) for r in db.execute('SELECT data_json FROM social_posts WHERE received_at>=?',(cutoff,))] if 'social_posts' in tables else []
    authors=collections.Counter(str(p.get('author') or '').lower() for p in posts)
    evt_rows=list(db.execute('SELECT e.kind,e.cohort,e.regime,o.horizon,o.return_pct FROM research_v3_events e LEFT JOIN research_v3_outcomes o ON o.event_id=e.id')) if 'research_v3_events' in tables and 'research_v3_outcomes' in tables else []
    # Event counts must not be multiplied by their outcome rows.
    kind_count=collections.Counter(r[0] for r in db.execute('SELECT kind FROM research_v3_events')) if 'research_v3_events' in tables else collections.Counter()
    groups={}
    for kind,cohort,regime,h,r in evt_rows:
        if h is not None and r is not None:groups.setdefault((kind,h),[]).append(float(r))
    print(f'MemeRadar | audit local | dernière donnée {datetime.datetime.fromtimestamp(cmax).isoformat(timespec="seconds") if cmax else "inconnue"}')
    print(f'Fenêtre: {hours:g} heures précédant la dernière observation (pas forcément en continu)')
    print(f'Tokens: {n}; revisités sur la fenêtre: {len(latest)}')
    print(f'Liquidité DEX manquante dans le dernier état: {sum(c.get("liquidity_usd") is None for c in rows)}/{n or 1}')
    print('Statuts enregistrés:',dict(stat))
    print('Versions des dernières analyses:',dict(vers))
    print(f'J7: {social_count} posts cumulés, {len(posts)} reçus pendant la fenêtre, {linked_count} liens post/contrat cumulés')
    print(f'Publications authored par elonmusk: {authors.get("elonmusk",0)} (mentions non incluses)')
    print('Signaux v3:',dict(kind_count))
    for (kind,h),values in sorted(groups.items()):
        if kind not in ('a_etudier','courbe_precoce','temoin_surveillance','pression_initiale'):continue
        print(f' {kind:<21} +{h//60:>2}min n={len(values):>3} gains={sum(v>0 for v in values):>3} médiane={statistics.median(values):.1f}% pertes<=-30%={sum(v<=-30 for v in values)}')
    if 'scan_cycles' in tables:
        cycles=list(db.execute('SELECT * FROM scan_cycles WHERE finished_at >= ? ORDER BY finished_at',(cutoff,)))
        print(f'Cycles instrumentés: {len(cycles)}')
        if cycles:
            print('Durée médiane:',round(statistics.median(r['duration_s'] for r in cycles),2),'s')
            for k in ['discovery','wallets','candidate_selection','dex_quotes','gecko_quotes','token_analysis']:
                vs=[json.loads(r['stages_json']).get(k) for r in cycles];vs=[v for v in vs if isinstance(v,(float,int))]
                if vs:print('  ',k,round(statistics.median(vs),2),'s median')
            print('Médiane nouveaux candidats / cycle:',round(statistics.median(r['new_candidates'] or 0 for r in cycles),1))
            print('Médiane nouveaux examinés / cycle:',round(statistics.median(r['fresh_scanned'] or 0 for r in cycles),1))
    else:print('Cycles: non instrumentés dans cette version. La v6.9.3 commence à les enregistrer.')
    print('ATTENTION: variations de cotation ≠ PnL réalisable. Frais, slippage, latence, non-ventes et survivance non mesurés.')
    db.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Audit SQLite local en lecture seule')
    parser.add_argument('--db',default='radar.db')
    parser.add_argument('--hours',type=float,default=2)
    args=parser.parse_args()
    if args.hours<=0:parser.error('hours doit être positif')
    audit(args.db,args.hours)
