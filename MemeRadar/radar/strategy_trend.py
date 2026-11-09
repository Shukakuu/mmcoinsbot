"""TREND: hourly demand accompanied by a recent event."""
from .strategy_common import market_reasons, momentum_reasons, recent_links

PROFILE = ('hours', 'TREND · Heures', 300, 25000, 30, 2880)


def evaluate(coin, links, now):
    reasons = market_reasons(coin, now, *PROFILE[2:]) + momentum_reasons(coin)
    if not recent_links(links, now, 21600):
        reasons.append('Aucun événement récent associé')
    return reasons
