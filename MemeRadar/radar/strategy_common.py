"""Shared numeric and market observation checks; no trade execution."""
import math


def market_reasons(coin, now, freshness, minimum, low, high):
    reasons = []
    quote = numeric(coin.get('market_quote_at'))
    age = numeric(coin.get('age_min'))
    if age is not None and quote is not None:
        age += max(0, now-quote)/60
    price = numeric(coin.get('price_usd'))
    liquidity = numeric(coin.get('liquidity_usd'))
    if quote is None or not 0 <= now-quote <= freshness or price is None or price <= 0:
        reasons.append('Cotation absente ou périmée')
    if age is None or not low <= age <= high:
        reasons.append('Âge hors fenêtre ou inconnu')
    if liquidity is None or liquidity < minimum:
        reasons.append(f'Liquidité requise : {minimum:,} $'.replace(',', ' '))
    return reasons


def momentum_reasons(coin, minutes=False):
    reasons = []
    change = numeric(coin.get('change_m5_pct' if minutes else 'change_h1_pct'))
    if change is None or not 0 < change <= (40 if minutes else 60):
        reasons.append('Momentum positif modéré non confirmé')
    buys = numeric(coin.get('pressure_buys_m5' if minutes else 'buys_h1'))
    sells = numeric(coin.get('pressure_sells_m5' if minutes else 'sells_h1'))
    if buys is None or sells is None or buys < 10 or buys <= sells:
        reasons.append('Pression acheteuse non confirmée')
    return reasons


def recent_links(links, now, seconds):
    return [x for x in links if numeric(x.get('published_at')) is not None
            and 0 <= now-float(x['published_at']) <= seconds]


def numeric(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None

