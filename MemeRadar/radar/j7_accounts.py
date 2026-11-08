"""Read-only coverage audit of *user-owned* J7 watchlists. No auth tokens logged.

The account list endpoint does NOT authorize adding accounts or spending slots;
this module intentionally never POSTs. Use J7's own app to manage accounts.
"""
from __future__ import annotations
import json
import urllib.request

# Priorities for narrative tracking. Presence is verified via the user's J7 API,
# not inferred from popularity on X or past appearance in a database.
PRIORITY_HANDLES = ('elonmusk', 'RockstarGames', 'RockstarSupport',
                    'blknoiz06', 'MustStopMurad', 'cz_binance', 'theunipcs')
ENDPOINT = 'https://core.j7tracker.io/api/watched-accounts'


def evaluate_coverage(payload, requested=PRIORITY_HANDLES):
    x = payload.get('x') or {}
    custom = payload.get('custom') or {}
    available = payload.get('available') or {}
    def handles(v):
        return {str(k.get('handle') if isinstance(k,dict) else k).lower().lstrip('@')
                for k in (v or [])}
    active = handles(x.get('accounts')) | handles(custom.get('accounts')) | handles(custom.get('availableAccounts'))
    free = handles(available.get('accounts'))
    hidden = handles(payload.get('hidden'))
    rows = []
    for handle in requested:
        norm=handle.lower().lstrip('@')
        status = ('masked' if norm in hidden else 'tracked' if norm in active else
                  'available_free' if norm in free else 'not_tracked')
        rows.append({'handle':handle, 'status':status})
    return {'total':len(rows),'tracked':sum(r['status']=='tracked' for r in rows),
            'accounts':rows,'slots':custom.get('maxAccounts'),
            'check_only':True}


def fetch_coverage(token, timeout=5, opener=None):
    if not token:
        raise ValueError('J7_FEED_TOKEN absent')
    req=urllib.request.Request(ENDPOINT,headers={'Authorization':'Bearer '+token,
                        'Accept':'application/json','User-Agent':'MemeRadar/7.0'})
    with (opener or urllib.request.urlopen)(req,timeout=timeout) as response:
        data=response.read(400_001)
    if len(data)>400_000:
        raise ValueError('Réponse J7 trop volumineuse')
    payload=json.loads(data)
    if not isinstance(payload,dict) or payload.get('success') is False:
        raise ValueError('J7 refuse la lecture des comptes')
    return evaluate_coverage(payload)
