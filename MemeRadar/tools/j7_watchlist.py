#!/usr/bin/env python3
"""Check important J7 X accounts, optionally join ONLY the already-free pool.

Never purchases slots, never registers new custom accounts, never trades.
Only an explicitly typed confirmation sends a POST.
"""
import getpass
import json
import os
import sys
import urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from radar.j7_accounts import fetch_coverage, ENDPOINT


def add_free_only(token, coverage, *, opener=None):
    handles=[row['handle'] for row in coverage.get('accounts', [])
             if row.get('status')=='available_free']
    if not handles:
        return {'added':0,'message':'Aucun compte prioritaire libre à ajouter.'}
    req=urllib.request.Request('https://core.j7tracker.io/api/accounts/available',
        data=json.dumps({'handles':handles}).encode('utf-8'),method='POST',headers={
        'Authorization':'Bearer '+token,'Content-Type':'application/json',
        'User-Agent':'MemeRadar/7.0'})
    with (opener or urllib.request.urlopen)(req,timeout=10) as response:
        result=json.loads(response.read(100_001))
    if not isinstance(result,dict) or result.get('ok') is not True:
        raise ValueError('J7 a refusé la demande.')
    return {'added':int(result.get('added', 1 if len(handles)==1 else 0)),
            'requested':handles,'message':'Vérifier la couverture après reconnexion.'}


def main():
    token=os.getenv('J7_FEED_TOKEN','').strip() or getpass.getpass('Jeton J7 (non affiché et non enregistré) : ').strip()
    try:
        report=fetch_coverage(token)
        print('\nCOMPTES PRIORITAIRES / J7 (lecture seule)')
        labels={'tracked':'suivi','masked':'masqué','available_free':'disponible gratuitement','not_tracked':'absent (éventuel créneau J7)'}
        for row in report['accounts']:
            print(f"@{row['handle']:18} {labels.get(row['status'],row['status'])}")
        available=[r['handle'] for r in report['accounts'] if r['status']=='available_free']
        if available:
            print('\nDisponibles dans le pool gratuit : '+', '.join('@'+x for x in available))
            choice=input("Saisir AJOUTER pour les ajouter à TA liste J7 (gratuit, aucun créneau acheté), sinon Entrée : ").strip()
            if choice=='AJOUTER':
                outcome=add_free_only(token,report)
                print('Demande envoyée :',outcome['requested'])
            else:
                print('Aucun changement de compte.')
        else:
            print('\nAucun compte prioritaire dans le pool gratuit. Les absents sont à gérer dans J7.')
    except Exception as exc:
        print('Erreur J7 :',type(exc).__name__,'(vérifier jeton, droits et réseau)')
        raise SystemExit(1)

if __name__=='__main__':main()
