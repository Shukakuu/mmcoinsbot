"""Explainable observation strategies. No orders, position sizing or profit claims."""
from __future__ import annotations
import math
import time


def numeric(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def risk_gate(coin, now):
    safety = coin.get('safety_summary') or {}
    blocked = list(coin.get('risks') or [])
    missing = []
    for key, label in [('mint_active', 'Autorité mint'), ('freeze_active', 'Autorité freeze')]:
        if safety.get(key) is True:
            blocked.append(label + ' active')
        elif safety.get(key) is not False:
            missing.append(label + ' inconnue')
    if safety.get('rugged') is True:
        blocked.append('Rug signalé')
    for risk in safety.get('rugcheck_risks_at_quote') or []:
        if str(risk.get('level', '')).lower() in {'danger', 'critical', 'high', 'very high', 'severe', 'extreme'}:
            blocked.append('Alerte fournisseur : ' + str(risk.get('name') or 'risque grave'))
    top = numeric(safety.get('top10_pct'))
    if top is None:
        missing.append('Concentration des détenteurs inconnue')
    elif top > 55:
        blocked.append('Concentration top 10 > 55 %')
    if safety.get('top10_method') != 'excluded_verified_protocol_accounts':
        missing.append('Concentration hors réserves de protocoles non vérifiée')
    onchain = coin.get('onchain_risk') or {}
    launch_share = numeric(onchain.get('launch_wallet_pct'))
    if launch_share is not None and launch_share > 20:
        blocked.append('Wallet du lancement détient plus de 20 % de la supply')
    lp = numeric(safety.get('lp_locked_pct'))
    if lp is None:
        missing.append('Protection de liquidité non vérifiée pour ce pool')
    elif lp < 90:
        blocked.append('Moins de 90 % de liquidité verrouillée/brûlée déclarée')
    if numeric(safety.get('rugcheck_score')) is None:
        missing.append('Rapport RugCheck absent')
    checked = numeric(coin.get('safety_checked_at'))
    if checked is None or not 0 <= now - checked <= 900:
        missing.append('Contrôles de risque absents ou périmés (> 15 min)')
    if coin.get('status') == 'risque' and not blocked:
        blocked.append('Risque détecté par le scanner')
    return {'state': 'blocked' if blocked else 'unverified' if missing else 'reviewable',
            'blockers': list(dict.fromkeys(blocked)), 'unknown': missing,
            'note': 'Filtre prudent, jamais une garantie anti-rug ni une preuve de revente.'}


PROFILES = (
    ('minutes', 'FAST · Minutes', 120, 10000, 0, 180),
    ('hours', 'TREND · Heures', 300, 25000, 30, 2880),
    ('days', 'GROWTH · Jours', 300, 50000, 1440, 43200),
)


def assess(coin, links=(), now=None):
    now = time.time() if now is None else now
    gate = risk_gate(coin, now)
    quote = numeric(coin.get('market_quote_at'))
    age = numeric(coin.get('age_min'))
    # age_min was calculated at quote time, not at dashboard refresh time.
    if age is not None and quote is not None:
        age += max(0, now - quote) / 60
    liquidity = numeric(coin.get('liquidity_usd'))
    price = numeric(coin.get('price_usd'))
    results = []
    for key, label, freshness, minimum, low, high in PROFILES:
        reasons = []
        if quote is None or not 0 <= now - quote <= freshness or price is None or price <= 0:
            reasons.append('Cotation absente ou périmée')
        if age is None or not low <= age <= high:
            reasons.append('Âge hors fenêtre ou inconnu')
        if liquidity is None or liquidity < minimum:
            reasons.append(f'Liquidité requise : {minimum:,} $'.replace(',', ' '))
        change = numeric(coin.get('change_m5_pct' if key == 'minutes' else 'change_h1_pct'))
        if change is None or not 0 < change <= (40 if key == 'minutes' else 60):
            reasons.append('Momentum positif modéré non confirmé')
        buys = numeric(coin.get('pressure_buys_m5' if key == 'minutes' else 'buys_h1'))
        sells = numeric(coin.get('pressure_sells_m5' if key == 'minutes' else 'sells_h1'))
        if buys is None or sells is None or buys < 10 or buys <= sells:
            reasons.append('Pression acheteuse non confirmée')
        recent_links = [x for x in links if numeric(x.get('published_at')) is not None and
                        0 <= now-x['published_at'] <= (21600 if key=='hours' else 7*86400)]
        if key in ('hours', 'days') and not recent_links:
            reasons.append('Aucun événement récent associé')
        if key == 'days':
            sources = {x.get('source') for x in recent_links if x.get('source')}
            dates = [x['published_at'] for x in recent_links]
            if len(sources) < 2 or not dates or max(dates) - min(dates) < 86400:
                reasons.append('Narratif non confirmé sur 24 h et deux sources')
            samples = [s for s in coin.get('strategy_history', []) if 0 <= now-s['observed_at'] <= 7*86400]
            if len(samples) < 12 or samples[-1]['observed_at']-samples[0]['observed_at'] < 86400:
                reasons.append('Historique insuffisant : 12 relevés sur au moins 24 h')
            else:
                old = samples[0]
                old_liquidity = numeric(old.get('liquidity'))
                old_top = numeric(old.get('top10'))
                current_top = numeric((coin.get('safety_summary') or {}).get('top10_pct'))
                if old_liquidity is None or liquidity is None or liquidity < old_liquidity:
                    reasons.append('Liquidité non maintenue sur la période')
                if old_top is None or current_top is None or current_top > old_top:
                    reasons.append('Diversification des détenteurs non confirmée')
                prices = [numeric(s.get('price')) for s in samples]
                prices = [p for p in prices if p is not None and p > 0]
                if not prices or price is None or price < max(prices)*0.7:
                    reasons.append('Correction supérieure à 30 % ou prix historique inconnu')
        state = ('blocked' if gate['state'] == 'blocked' else
                 'unverified' if gate['state'] == 'unverified' else
                 'watch' if reasons else 'review')
        results.append({'key': key, 'label': label, 'state': state,
                        'reasons': reasons, 'max_quote_age_s': freshness,
                        'minimum_liquidity_usd': minimum})
    return {'risk': gate, 'strategies': results}


def enforce_gate(coin, now):
    """Apply the same veto to legacy views/eligibility and new strategies."""
    gate = risk_gate(coin, now)
    coin['security_gate'] = gate
    coin['eligible'] = bool(coin.get('eligible') and gate['state'] == 'reviewable')
    if gate['state'] == 'blocked':
        coin['status'] = 'risque'
        coin['risks'] = list(dict.fromkeys(list(coin.get('risks') or []) + gate['blockers']))
    elif gate['state'] == 'unverified' and coin.get('status') == 'a_etudier':
        coin['status'] = 'incomplet'
    return coin
