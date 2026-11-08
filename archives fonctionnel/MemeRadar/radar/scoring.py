"""Deterministic and UNCALIBRATED ranking (0-100) with explicit evidence coverage.

A score is NOT a probability of future performance. Absence of data NEVER improves it.
"""
from __future__ import annotations
import math
from .source_scanner import number


def scale(value, low, high, cap):
    if value is None:
        return 0.0
    return max(0.0, min(cap, (value-low)/max(high-low, 0.000001)*cap))


def score_token(pair, safety, gecko, sources, wallets, now):
    """Return ranking, component breakdown, hard risks and missing proofs.

    Market 55 / Safety 25 / Discovery 10 / Verification 10. A paid boost earns zero.
    Wallet observations are evidence annotations, not a calibrated predictive weight.
    """
    reasons, unknown, positives = [], [], []
    sources = set(sources or [])
    safety = safety if isinstance(safety, dict) else {}
    gecko = gecko if isinstance(gecko, dict) else {}
    pair = pair if isinstance(pair, dict) else {}
    liquidity = number((pair.get('liquidity') or {}).get('usd'))
    volume = number((pair.get('volume') or {}).get('h1'))
    txn = (pair.get('txns') or {}).get('h1') or {}
    buys, sells = number(txn.get('buys')), number(txn.get('sells'))
    m5 = number((pair.get('priceChange') or {}).get('m5'))
    age_ms = number(pair.get('pairCreatedAt'))
    age = (now - age_ms / 1000) / 60 if age_ms is not None else None
    top10 = safety.get('top10_pct')
    rug_score = safety.get('rugcheck_risk_score')
    pieces = {}

    # LIQUIDITY: tiny pools are risky even if they look exciting.
    pieces['liquidité'] = scale(math.log10(liquidity) if liquidity and liquidity > 0 else None, 3.5, 5.2, 14)
    if liquidity is None: unknown.append('Liquidité indisponible')
    elif liquidity < 5000: reasons.append('Liquidité < 5 000 $')
    elif liquidity >= 20_000: positives.append('Liquidité ≥ 20 k$')

    pieces['volume/liquidité'] = scale(volume / liquidity if volume is not None and liquidity and liquidity > 0 else None, 0, 1.5, 10)
    if volume is None: unknown.append('Volume horaire indisponible')
    pieces['activité'] = scale((buys or 0)+(sells or 0) if buys is not None and sells is not None else None, 0, 120, 7)
    if buys is None or sells is None: unknown.append('Transactions horaires indisponibles')
    else:
        ratio = buys/(buys+sells) if buys+sells else 0
        pieces['pression acheteuse'] = scale(ratio, 0.4, 0.72, 10) if buys+sells >= 12 else 0
        if buys+sells < 12: unknown.append('Échantillon transactions trop faible')
        elif ratio > 0.6: positives.append('Pression acheteuse > 60 %')
    if 'pression acheteuse' not in pieces: pieces['pression acheteuse'] = 0

    # Positive momentum is interesting, but euphoria is not rewarded blindly.
    if m5 is None:
        pieces['momentum'] = 0; unknown.append('Variation 5 minutes indisponible')
    elif -8 <= m5 <= 20:
        pieces['momentum'] = scale(m5, -8, 9, 9)
        if m5 >= 2: positives.append('Momentum positif et modéré')
    elif 20 < m5 <= 35: pieces['momentum'] = scale(35-m5, 0, 15, 9)
    else: pieces['momentum'] = 0
    if m5 is not None and m5 > 70: reasons.append('Pump > 70 % en 5 minutes : possible FOMO')
    if m5 is not None and m5 < -40: reasons.append('Chute > 40 % en 5 minutes')

    # Token-pair age from DEX, not mint age; labeled as such in UI.
    if age is None:
        pieces['jeunesse de la paire'] = 0; unknown.append('Âge de la paire inconnu')
    elif 1 <= age <= 120: pieces['jeunesse de la paire'] = 5
    elif 120 < age <= 360: pieces['jeunesse de la paire'] = scale(360-age, 0, 240, 5)
    else: pieces['jeunesse de la paire'] = 0

    pieces['sécurité autorités'] = 0
    for key, title in [('mint_active','Autorité mint active'), ('freeze_active','Autorité freeze active')]:
        value = safety.get(key)
        if value is None: unknown.append(title + ' : inconnu')
        elif value: reasons.append(title)
        else: pieces['sécurité autorités'] += 5
    if safety.get('rugged') is True: reasons.append('Rug identifié par le fournisseur')
    levels = set(safety.get('risk_levels') or [])
    if levels & {'danger','critical','high','very high','severe','extreme'}: reasons.append('Risque élevé relevé par RugCheck')
    if top10 is None: unknown.append('Concentration top 10 inconnue'); pieces['distribution'] = 0
    else:
        pieces['distribution'] = scale(55-top10, 0, 35, 10)
        if top10 > 55: reasons.append('Top 10 > 55 % (pouvant inclure pools/contrats)')
    if rug_score is None: unknown.append('Score RugCheck indisponible'); pieces['rugcheck'] = 0
    else:
        pieces['rugcheck'] = scale(75-rug_score, 0, 75, 5)
        if rug_score >= 75: reasons.append('Score de risque RugCheck élevé')

    # Discovery is NOT endorsement. Paid promotions are explicitly zero.
    discovery = min(10, (6 if 'gecko_new_pools' in sources else 0)
                    + (3 if 'gecko_trending_pools' in sources else 0)
                    + (1 if 'dex_profiles' in sources else 0))
    if wallets: discovery = min(10, discovery + 2)  # observed balance increases, not proven buying.
    pieces['découverte'] = discovery
    if not sources and not wallets: unknown.append('Origine découverte inconnue')
    if sources == {'dex_boosts_paid'}: reasons.append('Détecté seulement via boost payant')

    pieces['correspondance Gecko'] = 0
    px = number(pair.get('priceUsd'))
    other = number(gecko.get('price'))
    same_pool = bool(gecko and gecko.get('pair_address') == pair.get('pairAddress'))
    if px and other and same_pool:
        gap = abs(px-other) / ((px+other)/2)*100
        if gap <= 5:
            pieces['correspondance Gecko'] = 8
            positives.append('Prix confirmé sur le même pool')
        else: reasons.append('Écart de prix Dex/Gecko > 5 %')
    else: unknown.append('Prix du même pool non confirmé par Gecko')
    pieces['acheteurs distincts'] = 0
    distinct = number(gecko.get('buyers_h1'))
    if distinct is None: unknown.append('Acheteurs distincts non vérifiés')
    elif distinct >= 15: pieces['acheteurs distincts'] = 2
    else: unknown.append('Moins de 15 acheteurs distincts (1 h)')

    total = round(max(0, min(100, sum(pieces.values()))), 1)
    # Proof is distinct from score: missing data MUST be obvious even when rank is high.
    required = (liquidity is not None, volume is not None, buys is not None and sells is not None,
                m5 is not None, age is not None, safety.get('mint_active') is not None,
                safety.get('freeze_active') is not None, top10 is not None,
                rug_score is not None, same_pool and other is not None)
    coverage = round(sum(required) / len(required) * 100)
    if reasons: status = 'risque'
    elif coverage < 70: status = 'incomplet'
    elif total >= 65 and liquidity and liquidity >= 10_000: status = 'a_etudier'
    else: status = 'surveillance'
    return {'score': total, 'coverage': coverage, 'status': status,
            'pieces': pieces, 'positives': positives, 'risks': reasons, 'unknown': unknown,
            'age_min': round(age,1) if age is not None else None,
            'gecko_gap_pct': round(abs(px-other) / ((px+other)/2)*100,2) if px and other and same_pool else None,
            'wallet_hit_count': len(set(wallets or [])),
            'market_score':round(sum(pieces[k] for k in ('liquidité','volume/liquidité','activité','pression acheteuse','momentum')),1),
            'safety_score':round(sum(pieces[k] for k in ('sécurité autorités','distribution','rugcheck')),1)}
