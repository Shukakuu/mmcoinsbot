"""One decision path for scanner, API and all three manual-only strategies."""
import time
from .security_gate import risk_gate, enforce_gate
from . import strategy_fast, strategy_trend, strategy_growth

STRATEGIES = (strategy_fast, strategy_trend, strategy_growth)
PROFILES = tuple(module.PROFILE for module in STRATEGIES)


def assess(coin, links=(), now=None):
    now = time.time() if now is None else now
    gate = risk_gate(coin, now)
    results = []
    for module in STRATEGIES:
        key, label, freshness, minimum, _, _ = module.PROFILE
        reasons = module.evaluate(coin, links, now)
        state = ('blocked' if gate['state']=='blocked' else
                 'unverified' if gate['state']=='unverified' else 'watch' if reasons else 'review')
        results.append({'key':key, 'label':label, 'state':state, 'reasons':reasons,
                        'max_quote_age_s':freshness, 'minimum_liquidity_usd':minimum})
    return {'risk':gate, 'strategies':results}


def apply_decision(coin, links=(), now=None):
    now = time.time() if now is None else now
    decision = assess(coin, links, now)
    enforce_gate(coin, now)
    coin['strategy_decisions'] = decision['strategies']
    coin['eligible'] = any(x['state']=='review' for x in decision['strategies'])
    if decision['risk']['state']=='reviewable':
        coin['status'] = 'a_etudier' if coin['eligible'] else 'surveillance'
    coin['world_context'] = list(links)[:12]
    coin['world_event_count'] = len(links)
    coin['decision_evaluated_at'] = now
    coin['decision_method'] = 'v2_strategies_manual_only'
    return coin
