"""Experimental *early research* on bonding-curve-like markets.

DexScreener may quote a live pump.fun / Meteora DBC market while omitting
liquidity.usd. This is not liquidity=0. The regime is inferred from the DEX
label, not verified on-chain. Do not pretend virtual reserves are real USD LP.
No trading, no graduation progress estimate, no investment probability.
"""
from .source_scanner import number

CURVE_DEX_MARKERS = ('pumpfun', 'pump.fun', 'meteora', 'meteora-dbc', 'meteora dbc', 'dynamic_bonding_curve')


def is_probable_curve(pair):
    if not isinstance(pair, dict):
        return False
    if number((pair.get('liquidity') or {}).get('usd')) is not None:
        return False
    label = str(pair.get('dexId') or '').lower() + ' ' + str(pair.get('url') or '').lower()
    return any(word in label for word in CURVE_DEX_MARKERS)


def assess_curve(pair, safety, baseline, now):
    """Separate score and alert thresholds for *probable* bonding curves.

    Returns None for normal AMM pools. Tokens without verified safety cannot
    become review candidates, regardless of their activity.
    """
    if not is_probable_curve(pair):
        return None
    safety = safety or {}
    market_cap = number(pair.get('marketCap')) or number(pair.get('fdv'))
    px = number(pair.get('priceUsd'))
    v5 = number((pair.get('volume') or {}).get('m5'))
    change = number((pair.get('priceChange') or {}).get('m5'))
    tx = (pair.get('txns') or {}).get('m5') or {}
    buys, sells = number(tx.get('buys')), number(tx.get('sells'))
    count = (buys+sells) if buys is not None and sells is not None else 0
    share = buys / count if count else None
    created = number(pair.get('pairCreatedAt'))
    age = (now-created/1000)/60 if created is not None and created/1000<=now else None
    # Never reclassify a rug, active mint/freeze or severe provider issue as safe.
    hard_risk = bool(baseline.get('risks'))
    authority_ok = safety.get('mint_active') is False and safety.get('freeze_active') is False
    rug_available = safety.get('rugcheck_risk_score') is not None
    facts = [
        market_cap is not None, px is not None, v5 is not None,
        buys is not None and sells is not None, change is not None,
        created is not None, safety.get('mint_active') is not None,
        safety.get('freeze_active') is not None, rug_available,
    ]
    evidence = round(sum(facts) / len(facts) * 100)
    score_parts = {
        'cap marché (courbe)': (20 if market_cap is not None and 3000 <= market_cap <= 100000 else
                               12 if market_cap is not None and 1500 <= market_cap <= 200000 else 0),
        'volume 5 min (courbe)': (17 if v5 is not None and v5 >= 1500 else
                                 12 if v5 is not None and v5 >= 700 else
                                 5 if v5 is not None and v5 >= 200 else 0),
        'transactions 5 min (courbe)': (19 if count >= 35 else 13 if count >= 18 else
                                      6 if count >= 8 else 0),
        'pression acheteuse (courbe)': (17 if share is not None and share >= .72 and count >= 12 else
                                      12 if share is not None and share >= .62 and count >= 12 else 0),
        'prix sans euphorie': (9 if change is not None and -5 <= change <= 5 else
                              5 if change is not None and -12 <= change <= 15 else 0),
        'autorités vérifiées': (12 if authority_ok else 0),
        'rapport risques disponible': (6 if rug_available else 0),
    }
    score = round(min(100, sum(score_parts.values())), 1)
    early = (not hard_risk and authority_ok and rug_available and evidence >= 90
             and market_cap is not None and 2000 <= market_cap <= 150000
             and px is not None and px > 0 and age is not None and age <= 180
             and v5 is not None and v5 >= 700 and count >= 18 and buys >= 12
             and share is not None and share >= .62
             and change is not None and -8 <= change <= 12)
    preliminary = (not hard_risk and authority_ok and rug_available
                   and market_cap is not None and market_cap >= 1500
                   and v5 is not None and v5 >= 200 and count >= 8
                   and share is not None and share >= .6 and change is not None and change <= 15)
    unknown = ['Marché sur courbe probable (déduit de DexScreener, non vérifié on-chain)',
               'Réserves, slippage et progression de graduation NON vérifiés : ne pas assimiler à une liquidité DEX',
               'Achats en nombre de transactions, pas d’acheteurs uniques']
    if not authority_ok: unknown.append('Autorités mint/freeze non validées : pas de promotion')
    if market_cap is None: unknown.append('Market cap inconnue : pas de signal précoce')
    if safety.get('top10_pct') is None: unknown.append('Concentration privée non confirmée')
    return {'score':score,'coverage':evidence,'pieces':score_parts,
            'early_candidate':bool(early),'preliminary':bool(preliminary),
            'unknown':unknown, 'market_cap':market_cap,
            'age_min':age, 'buy_share':share,
            'method':'curve_inferred', 'safety_verified':authority_ok and rug_available}
