"""Experimental pre-momentum pressure patterns using ONLY observations from the past.

Not a predictor or a probability. The 5m windows must NOT overlap to call a signal confirmed. An early
prewatch is explicitly preliminary, not a trading recommendation.
"""
from __future__ import annotations
from .source_scanner import number


def market_snapshot(pair, now):
    transactions = (pair.get('txns') or {}).get('m5') or {}
    return {'ts':float(now), 'pool':pair.get('pairAddress'),
            'price':number(pair.get('priceUsd')),
            'liquidity':number((pair.get('liquidity') or {}).get('usd')),
            'volume_m5':number((pair.get('volume') or {}).get('m5')),
            'buys_m5':number(transactions.get('buys')),
            'sells_m5':number(transactions.get('sells')),
            'change_m5':number((pair.get('priceChange') or {}).get('m5')),
            'change_h1':number((pair.get('priceChange') or {}).get('h1'))}


def pressure_reading(s):
    """Clear, conservative sufficient conditions for *review*, not for purchase."""
    b, v = s.get('buys_m5'), s.get('sells_m5')
    vol, liq = s.get('volume_m5'), s.get('liquidity')
    p5, p1 = s.get('change_m5'), s.get('change_h1')
    n=(b+v) if b is not None and v is not None else 0
    if not (s.get('pool') and s.get('price') and s['price']>0
            and liq is not None and liq>=12_000
            and vol is not None and vol >= 1_500
            and vol/liq >= .015
            and n >= 24 and b>=16 and b/n>=.65
            and vol/n>=10  # discard obvious dust trade bursts
            and p5 is not None and -3.0<=p5<=4.0
            and p1 is not None and p1>=-25.0):
        return False
    return True


def prebreakout(pair, previous, report, safety, now):
    """Return pending/confirmed pre-impulse evidence; never override any risk.

    A confirmed signal requires TWO actual scans of the SAME pool, separated
    by >=300s and <=12min, with coherent flat-ish prices and buying pressure.
    Because 5min windows overlap, not claimed to be independent buyers.
    """
    current=market_snapshot(pair,now)
    risk=bool(report.get('risks'))
    safety=safety or {}
    core_safe=(not risk and report.get('coverage',0)>=70
        and safety.get('mint_active') is False
        and safety.get('freeze_active') is False
        and safety.get('rugcheck_risk_score') is not None)
    if not core_safe or not pressure_reading(current):
        return {'prewatch':False,'confirmed':False,'snapshot':current}
    for old in reversed(previous or []):
        delta=now-(old.get('ts') or 0)
        if delta<300:continue
        if delta>720:break
        if old.get('pool')!=current['pool'] or not pressure_reading(old):continue
        if abs(current['price']/old['price']-1)>.06:continue
        # Both observations must be genuine, with no synthetic historical data.
        return {'prewatch':True,'confirmed':True,'snapshot':current,
            'elapsed_s':round(delta),
            'buy_share':round(current['buys_m5']/(current['buys_m5']+current['sells_m5']),3)}
    return {'prewatch':True,'confirmed':False,'snapshot':current,
        'buy_share':round(current['buys_m5']/(current['buys_m5']+current['sells_m5']),3)}
