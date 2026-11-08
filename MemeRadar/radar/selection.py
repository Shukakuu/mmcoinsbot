"""Pure candidate prioritization. Network discovery and quote collection live elsewhere.

No scores or trading rules are changed by this module: extraction from the
legacy orchestrator makes selection independently testable.
"""
from __future__ import annotations
from .source_scanner import number
from .narratives import contextual_matches
from .curve import assess_curve


def discovery_priority(item):
    _,src=item
    return (4 if 'j7_direct_contract' in src else 0,
            3 if 'wallet_public' in src else 0,
            2 if 'gecko_new_pools' in src else 0,
            1 if 'gecko_trending_pools' in src else 0,len(src))


def early_rank(mint,prefetched,t,posts,trends):
    p=prefetched.get(mint) or {}
    if not p:return (-1,0,0,0,0)
    x=(p.get('txns') or {}).get('m5') or {}
    b,s=number(x.get('buys')) or 0,number(x.get('sells')) or 0
    cap=number(p.get('marketCap')) or number(p.get('fdv')) or 0
    v5=number((p.get('volume') or {}).get('m5')) or 0
    created=number(p.get('pairCreatedAt')) or 0
    age_min=(t-created/1000)/60 if created else float('inf')
    thematic=bool(contextual_matches((p.get('baseToken') or {}).get('name'),posts,trends,t))
    curve=assess_curve(p,{}, {'risks':[]},t)
    return (int(0<=age_min<=180),int(thematic and b>=2),int(bool(curve)),int(b>=8 and b>=s),
            min(v5,10000)/10000+min(cap,100000)/100000)


def select_candidates(discovered,known,previous,urgent,limit,t,have_prewatch,fresh_order=None):
    """Use bounded queues, reserve follow-up slots, keep new discoveries alive."""
    fresh=list(fresh_order) if fresh_order is not None else [m for m,_ in sorted(discovered.items(),key=discovery_priority,reverse=True) if m not in known]
    old_budget=max(1,limit//2 if have_prewatch else limit//3)
    urgent_mints=list(dict.fromkeys(q['mint'] for q in urgent))
    excluded=set(urgent_mints)|set(fresh)
    recent=[p for p in previous if p['mint'] not in excluded
            and t-p.get('last_seen',0)>=(20 if p.get('early_watch') else 65)
            and t-p.get('last_seen',0)<=1800]
    recent.sort(key=lambda p:(bool(p.get('early_watch')),bool(p.get('prewatch') and not p.get('pre_impulse')),
           p.get('status')=='a_etudier',p.get('status')=='surveillance',bool(p.get('patterns')),
           p.get('score') or 0,min(t-p.get('last_seen',0),600)),reverse=True)
    archive=[p for p in previous if p['mint'] not in excluded and t-p.get('last_seen',0)>1800]
    archive.sort(key=lambda p:p.get('last_seen',0))
    available_old=max(0,old_budget-len(urgent_mints))
    selected_old=[p['mint'] for p in recent[:max(0,available_old-1)]]
    consumed=len(selected_old)
    if archive and len(selected_old)<available_old:selected_old.append(archive[0]['mint'])
    selected_old.extend(p['mint'] for p in recent[consumed:consumed+available_old-len(selected_old)])
    fresh_budget=max(1,limit-len(urgent_mints)-len(selected_old))
    chosen=list(dict.fromkeys(urgent_mints+fresh[:fresh_budget]+selected_old+fresh[fresh_budget:]))[:limit]
    return {'chosen':chosen,'fresh':fresh,'fresh_selected':sum(x in set(fresh) for x in chosen),
            'urgent':urgent_mints,'old':selected_old}
