"""Evidence-only author, wallet and metadata-copy summaries. No predictive score."""
import json
import re
import statistics
import time
import unicodedata
from collections import defaultdict
from pathlib import Path
from .social import is_solana_address


def normalized(value):
    value=unicodedata.normalize('NFKC',str(value or '')).casefold()
    return ' '.join(re.findall(r'\w+',value))


def clone_groups(rows):
    """Same mint is never a clone; a short ticker alone is not evidence."""
    groups=defaultdict(dict)
    for row in rows:
        name,symbol=normalized(row.get('name')),normalized(row.get('symbol'))
        if len(name)<4 or name in ('unknown','token','coin','test'):continue
        if not symbol:continue
        groups[(name,symbol)][row['mint']]=row
    out=[]
    for (name,symbol),members in groups.items():
        if len(members)<2:continue
        ordered=sorted(members.values(),key=lambda x:(x.get('first_at',0),x['mint']))
        out.append({'name':name,'symbol':symbol,'count':len(ordered),'members':ordered[:20],
                    'evidence':'Même nom normalisé ET ticker, contrats distincts',
                    'status':'copie_possible','flow_verified':False,
                    'note':'Ordre de réception uniquement. Original, affiliation et déplacement de liquidité non prouvés.'})
    return sorted(out,key=lambda g:max(m.get('first_at',0) for m in g['members']),reverse=True)[:30]


def wallet_inventory(wallets_path):
    from .providers import PublicWalletMonitor
    active=PublicWalletMonitor(None,wallets_path).wallets()
    path=Path(wallets_path).with_name('wallets_registry.json')
    try:
        raw=json.loads(path.read_text(encoding='utf8'))
        rows=raw.get('wallets',[]) if isinstance(raw,dict) else raw
        registry={r['trackedWalletAddress']:r for r in rows if isinstance(r,dict) and is_solana_address(r.get('trackedWalletAddress'))}
        error=None
    except (OSError,ValueError,TypeError):registry={};error='Registre absent ou illisible'
    return {'registered':len(registry),'active_count':len(active),
            'active':[{'address':a,'label':registry.get(a,{}).get('name') or a[:8]} for a in active],
            'error':error,'note':'5 wallets maximum interrogés par RPC. Labels fournis, identités et achats non vérifiés.'}


def report(store,wallets_path,now=None):
    now=time.time() if now is None else now
    with store.read_db() as db:
        launches=[dict(r) for r in db.execute('SELECT mint,name,symbol,first_at FROM live_launches WHERE first_at>=? ORDER BY first_at DESC LIMIT 5000',(now-86400,))]
        posts=[json.loads(r[0]) for r in db.execute('SELECT data_json FROM social_posts WHERE deleted=0 AND received_at>=? ORDER BY received_at DESC LIMIT 1000',(now-7*86400,))]
        measurements=[dict(r) for r in db.execute('''SELECT h.post_id,h.mint,o.horizon,o.return_pct,o.at
            FROM j7_highlights h JOIN j7_highlight_outcomes o ON o.highlight_id=h.id
            WHERE h.first_for_mint=1 AND h.via='post_ca' AND o.state='observed'
            AND o.at<=? AND h.seen_at>=?''',(now,now-7*86400))]
    by_post={p['id']:p for p in posts}
    authors={}
    for post in posts:
        key='id:'+str(post['author_id']) if post.get('author_id') else 'handle:'+str(post.get('author','')).casefold()
        entry=authors.setdefault(key,{'identity':key,'handle':post.get('author'),
            'stable_id_available':bool(post.get('author_id')),'followers':post.get('followers'),
            'badge_j7':post.get('j7_verified_type') or post.get('j7_badge'),
            'verified_j7':post.get('j7_verified'),'parody':post.get('j7_parody'),
            'posts':0,'contracts':set(),'_values':defaultdict(dict)})
        entry['posts']+=1
        if not post.get('is_repost') and not post.get('is_reply') and not post.get('is_backlog'):
            entry['contracts'].update(post.get('mints') or [])
        post['_identity']=key
    for m in measurements:
        post=by_post.get(m['post_id'])
        if not post or post.get('is_repost') or post.get('is_reply') or post.get('is_backlog'):continue
        authors[post['_identity']]['_values'][m['horizon']][m['mint']]=m['return_pct']
    for a in authors.values():
        a['contract_count']=len(a.pop('contracts'))
        a['outcomes']={str(h):{'n':len(v),'median_pct':round(statistics.median(v.values()),2),
                              'positive':sum(x>0 for x in v.values())} for h,v in a.pop('_values').items() if v}
        a['bot_share']=None
    return {'authors':sorted(authors.values(),key=lambda x:x['posts'],reverse=True)[:30],
            'clones':clone_groups(launches),'wallets':wallet_inventory(wallets_path),
            'sampled_launches':len(launches),'sampled_posts':len(posts),
            'note':'Historique local descriptif, première mention directe par mint seulement. Badge déclaré par J7, pas identité certifiée. Variations depuis première cotation, pas gains ni causalité. Aucun bonus de score.'}
