"""Explainable, price/wallet observation patterns inspired by the original bots.

Only uses snapshots actually collected by this application; never reconstructs
missing historic highs. Signals are descriptive, not trading recommendations.
"""
from __future__ import annotations
from .source_scanner import number


def detect_patterns(pair, history, wallets, now):
    """Return independently observed setups; zero signals is a valid result."""
    pair = pair or {}
    hist = [(number(x.get('ts')), number(x.get('price'))) for x in history]
    hist = sorted([(t, p) for t, p in hist if t is not None and p is not None and p > 0])
    if len(hist) > 90:
        hist = hist[-90:]
    values = (pair.get('txns') or {}).get('h1') or {}
    buy, sell = number(values.get('buys')), number(values.get('sells'))
    m5 = number((pair.get('priceChange') or {}).get('m5'))
    age_ms = number(pair.get('pairCreatedAt'))
    age = max(0.0, (now - age_ms / 1000) / 60) if age_ms is not None else None
    liq = number((pair.get('liquidity') or {}).get('usd'))
    vol = number((pair.get('volume') or {}).get('h1'))
    found = []

    # R1W5/R1W6 principle, not transplanted market-cap thresholds: require
    # demonstrable early activity AND moderate positive movement.
    if (age is not None and 0 <= age <= 20 and liq is not None and liq >= 5000
            and buy is not None and sell is not None and buy+sell >= 20
            and buy/(buy+sell) >= .60 and m5 is not None and 2 <= m5 <= 25):
        found.append({'key':'early','label':'Départ précoce',
                      'why':'Paire ≤ 20 min, ≥ 20 transactions/1 h, achats ≥ 60 %, hausse 5 min entre 2 et 25 %.'})

    if (liq is not None and liq >= 10000
            and vol is not None and vol >= 15000 and buy is not None and sell is not None
            and buy+sell >= 50 and buy/(buy+sell) >= .65
            and m5 is not None and 3 <= m5 <= 25):
        found.append({'key':'momentum','label':'Impulsion acheteuse',
                      'why':'Volume 1 h ≥ 15 k$, ≥ 50 transactions, achats ≥ 65 % et hausse 5 min de 3 à 25 %.'})

    # R1W4 idea: record a real observed peak, an ensuing drawdown and a rebound.
    # It is NOT an all-time-high, only the sampled window since this bot started.
    if len(hist) >= 4 and hist[-1][0] - hist[0][0] >= 600:
        best = None
        peak = hist[0][1]
        peak_t = hist[0][0]
        for t,p in hist[1:-1]:
            if p > peak:
                peak,peak_t=p,t
            elif p <= peak*.85 and t > peak_t:
                ratio=1-p/peak
                if best is None or ratio > best[0]: best=(ratio,p,t,peak)
        current = hist[-1][1]
        if best and hist[-1][0] > best[2] and best[1]*1.05 <= current <= best[3]*.98:
            found.append({'key':'rebound','label':'Reprise après correction',
                          'why':'Depuis les relevés locaux : recul ≥ 15 % après un sommet puis rebond ≥ 5 %, sans retrouver ce sommet.'})

    # RPC events mark increased token holdings, not necessarily a market swap.
    if len(set(wallets or [])) >= 2:
        found.append({'key':'wallets','label':'Convergence de wallets publics',
                      'why':'Au moins deux adresses suivies ont augmenté leur solde de ce token sur les 15 dernières minutes ; ce ne sont pas des achats certifiés.'})
    elif len(set(wallets or [])) == 1:
        found.append({'key':'wallet','label':'Mouvement de wallet suivi',
                      'why':'Un wallet public surveillé a vu son solde augmenter (pas nécessairement un achat).'} )
    return found
