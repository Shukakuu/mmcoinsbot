"""Common risk veto, independent from market scores and strategy horizons."""
from .strategy_common import numeric


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
    if not safety.get('rugcheck_risks_at_quote') and any(str(level).lower() in
            {'danger','critical','high','very high','severe','extreme'}
            for level in safety.get('rugcheck_risk_levels') or []):
        blocked.append('Alerte fournisseur sévère sans détails résolus')
    for risk in safety.get('rugcheck_risks_at_quote') or []:
        if str(risk.get('level', '')).lower() in {'danger', 'critical', 'high', 'very high', 'severe', 'extreme'}:
            blocked.append('Alerte fournisseur : ' + str(risk.get('name') or 'risque grave'))
    top = numeric(safety.get('top10_pct'))
    if top is None or not 0 <= top <= 100:
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
    if lp is None or not 0 <= lp <= 100:
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


def enforce_gate(coin, now):
    """Apply the same veto to legacy views/eligibility and new strategies."""
    gate = risk_gate(coin, now)
    coin['security_gate'] = gate
    coin['eligible'] = bool(coin.get('eligible') and gate['state'] == 'reviewable')
    if gate['state'] == 'blocked':
        coin['status'] = 'risque'
        coin['risks'] = list(dict.fromkeys(list(coin.get('risks') or []) + gate['blockers']))
    elif gate['state'] == 'unverified' and coin.get('status') == 'a_etudier':
        # Preserve watch/incomplete discovery states while revoking eligibility.
        coin['status'] = 'incomplet'
    return coin
