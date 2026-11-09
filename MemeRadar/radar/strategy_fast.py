"""FAST: minute-scale market observations, independently testable."""
from .strategy_common import market_reasons, momentum_reasons

PROFILE = ('minutes', 'FAST · Minutes', 120, 10000, 0, 180)


def evaluate(coin, links, now):
    return market_reasons(coin, now, *PROFILE[2:]) + momentum_reasons(coin, minutes=True)
