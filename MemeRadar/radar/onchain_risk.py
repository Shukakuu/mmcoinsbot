"""Bounded public-RPC risk observations; no false insider attribution.

A token-account top holder list includes bonding curves and pool reserves.
This module explicitly reports RAW top-holder concentration, never 'insiders'.
Wallet referenced by a launch event is not proof of token developer identity.
"""
from __future__ import annotations
import json
import math
import threading
import time
import urllib.request
from .social import is_solana_address


def ratio_pct(numerator,denominator):
    try:
        a=int(numerator);b=int(denominator)
        if a<0 or b<=0 or a>b:return None
        return round(a*100/b,3)
    except (ValueError,TypeError):return None


def parse_risk(supply,largest,owned=None):
    """Use integer RAW amounts; never compare UI floats with different decimals."""
    total=((supply or {}).get('value') or {}).get('amount')
    accounts=(largest or {}).get('value') or []
    raw=[]
    for a in accounts[:10]:
        try:
            value=int(a['amount'])
            if value<0:raise ValueError('Negative balance')
            raw.append(value)
        except (KeyError,ValueError,TypeError):return None
    if not raw:return {'raw_top10_pct':None,'launch_wallet_pct':None,'raw_holders':0,
                        'warning':'Liste des comptes token indisponible'}
    balances=[]
    for acc in ((owned or {}).get('value') or []):
        try:
            parsed=acc['account']['data']['parsed']['info']['tokenAmount']['amount']
            balances.append(int(parsed))
        except (KeyError,ValueError,TypeError):
            owned=None;break
    return {'raw_top10_pct':ratio_pct(sum(raw),total),
            'launch_wallet_pct':ratio_pct(sum(balances),total) if owned is not None else None,
            'raw_holders':len(raw),
            'warning':'Top10 BRUT : comprend les réserves/pools. Wallet du lancement non nécessairement développeur. Non attribuable aux insiders.'}


class SolanaRiskObserver:
    def __init__(self,store,stop_event,rpc_url='https://api.mainnet-beta.solana.com',request=None):
        self.store=store;self.stop_event=stop_event;self.rpc_url=rpc_url
        self.request=request or self._http_request
        self.status={'enabled':True,'running':False,'checked':0,'errors':0,'last_error':None}

    def _http_request(self,method,params):
        body=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode()
        req=urllib.request.Request(self.rpc_url,data=body,method='POST',headers={'Content-Type':'application/json','User-Agent':'MemeRadar-readonly/8'})
        with urllib.request.urlopen(req,timeout=5) as f:data=json.load(f)
        if data.get('error'):raise RuntimeError('RPC returned an error')
        return data.get('result')

    def inspect(self,mint,launch_wallet=''):
        if not is_solana_address(mint):return None
        supply=self.request('getTokenSupply',[mint,{'commitment':'confirmed'}])
        largest=self.request('getTokenLargestAccounts',[mint,{'commitment':'confirmed'}])
        owned=None
        if is_solana_address(launch_wallet):
            owned=self.request('getTokenAccountsByOwner',[launch_wallet,{'mint':mint},{'encoding':'jsonParsed','commitment':'confirmed'}])
        return parse_risk(supply,largest,owned)

    def run_once(self,now=None):
        now=time.time() if now is None else now
        with self.store.live_db() as db:
            row=db.execute('''SELECT l.mint,l.creator FROM live_launches l LEFT JOIN live_risk_observations r USING(mint)
                        WHERE l.matched=1 AND l.first_at<=? AND l.first_at>=? AND (r.mint IS NULL OR r.checked_at<?)
                        ORDER BY COALESCE(r.checked_at,0),l.first_at DESC LIMIT 1''',(now-15,now-7200,now-300)).fetchone()
        if not row:return False
        try:
            result=self.inspect(row['mint'],row['creator'])
            if result is None:raise ValueError('Invalid mint')
            self.store.record_live_risk(row['mint'],result,now)
            self.status['checked']+=1;self.status['last_error']=None
        except Exception as exc:
            self.status['errors']+=1;self.status['last_error']=type(exc).__name__
            # Persist unavailable data as UNKNOWN, not as zero risk.
            self.store.record_live_risk(row['mint'],{'raw_top10_pct':None,'launch_wallet_pct':None,
                           'warning':'RPC indisponible : concentration et développeur non vérifiés','error':type(exc).__name__},now)
        return True

    def run(self):
        self.status['running']=True
        try:
            while not self.stop_event.is_set():
                self.run_once()
                self.stop_event.wait(18)
        finally:self.status['running']=False
