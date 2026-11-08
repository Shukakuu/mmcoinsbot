"""An informational, early observation is NOT an investment recommendation.

Do not wait for all vendors to populate new markets before observing them.
Never promote a known rug or unsafe mint authority. Safety unknown stays unknown.
"""
from .source_scanner import number


def observe_early(pair, safety, report, now):
    if report.get('risks') or (safety or {}).get('rugged') is True:
        return None
    if (safety or {}).get('mint_active') is True or (safety or {}).get('freeze_active') is True:
        return None
    created=number((pair or {}).get('pairCreatedAt'))
    age=(now-created/1000)/60 if created is not None else None
    if age is None or not 0<=age<=30:
        return None
    px=number(pair.get('priceUsd'))
    v5=number((pair.get('volume') or {}).get('m5'))
    tx=(pair.get('txns') or {}).get('m5') or {}
    buys,sells=number(tx.get('buys')),number(tx.get('sells'))
    change=number((pair.get('priceChange') or {}).get('m5'))
    if (px is None or px<=0 or v5 is None or v5<80 or buys is None or sells is None
            or buys<4 or (buys+sells)>0 and buys/(buys+sells)<.55
            or change is None or not -15<=change<=25):
        return None
    return {'age_min':round(age,2),'buys_m5':buys,'sells_m5':sells,
            'volume_m5':v5,'change_m5':change,
            'safety_verified': (safety or {}).get('mint_active') is False and
                               (safety or {}).get('freeze_active') is False and
                               (safety or {}).get('rugcheck_risk_score') is not None,
            'description':'Début d’activité : sécurité et possibilité de revente à vérifier.'}
