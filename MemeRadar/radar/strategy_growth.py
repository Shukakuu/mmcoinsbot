"""GROWTH: persistent topics and observed multi-day liquidity/distribution."""
from .strategy_common import market_reasons, momentum_reasons, numeric, recent_links
from .narrative_graph import source_voice

PROFILE = ('days', 'GROWTH · Jours', 300, 50000, 1440, 43200)


def evaluate(coin, links, now):
    reasons = market_reasons(coin, now, *PROFILE[2:]) + momentum_reasons(coin)
    links = recent_links(links, now, 7*86400)
    if not links:
        reasons.append('Aucun événement récent associé')
    sources = {source_voice(x.get('source', '')) for x in links if x.get('source')}
    dates = [float(x['published_at']) for x in links]
    if len(sources) < 2 or not dates or max(dates)-min(dates) < 86400:
        reasons.append('Narratif non confirmé sur 24 h et deux sources')
    # Deduplicate hours and reject future/corrupt samples before measuring duration.
    samples = {}
    for sample in coin.get('strategy_history', []):
        stamp = numeric(sample.get('observed_at'))
        if stamp is not None and 0 <= now-stamp <= 7*86400:
            samples.setdefault(int(stamp//3600), sample)
    samples = sorted(samples.values(), key=lambda s:s['observed_at'])
    if len(samples) < 12 or samples[-1]['observed_at']-samples[0]['observed_at'] < 86400:
        reasons.append('Historique insuffisant : 12 relevés sur au moins 24 h')
        return reasons
    old = samples[0]
    old_liquidity, liquidity = numeric(old.get('liquidity')), numeric(coin.get('liquidity_usd'))
    old_top = numeric(old.get('top10'))
    current_top = numeric((coin.get('safety_summary') or {}).get('top10_pct'))
    if old_liquidity is None or liquidity is None or liquidity < old_liquidity:
        reasons.append('Liquidité non maintenue sur la période')
    if old_top is None or current_top is None or current_top > old_top:
        reasons.append('Diversification des détenteurs non confirmée')
    prices = [numeric(s.get('price')) for s in samples]
    prices = [p for p in prices if p is not None and p > 0]
    price = numeric(coin.get('price_usd'))
    if not prices or price is None or price < max(prices)*0.7:
        reasons.append('Correction supérieure à 30 % ou prix historique inconnu')
    return reasons
