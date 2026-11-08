"""Read-only public API adapters. No key or trade is needed."""
from __future__ import annotations
import json, time, urllib.error, urllib.request
from .source_scanner import (
    DEX, WSOL, TRUSTED_QUOTES, SourceError, candidate, dex_discovery,
    gecko_discovery, gecko_pool_quotes, rugcheck, fetch, number)


def discoveries():
    # Organic Gecko discovery and Dex paid/profile discovery deliberately tagged separately.
    dex, w1 = dex_discovery()
    gecko, w2 = gecko_discovery()
    for mint, sources in gecko.items(): dex.setdefault(mint,set()).update(sources)
    return dex, w1+w2


def dex_pairs_batch(mints):
    out = {}
    for i in range(0, len(mints), 30):
        batch = mints[i:i+30]
        try:
            rows = fetch(f"{DEX}/tokens/v1/solana/{','.join(batch)}")
            if not isinstance(rows, list): raise SourceError('Format DexScreener inattendu')
            for p in rows:
                if not isinstance(p, dict) or p.get('chainId') != 'solana': continue
                mint = (p.get('baseToken') or {}).get('address')
                quote = (p.get('quoteToken') or {}).get('address')
                if mint not in batch or quote not in TRUSTED_QUOTES: continue
                if not (number(p.get('priceUsd')) or 0) > 0: continue
                if not candidate(p.get('pairAddress')): continue
                current = out.get(mint)
                if current is None or (number((p.get('liquidity') or {}).get('usd')) or 0) > (number((current.get('liquidity') or {}).get('usd')) or 0):
                    out[mint] = p
        except SourceError as exc:
            raise SourceError('Dex batch: ' + str(exc)) from exc
    return out


def quote_same_pools(pairs):
    try: return gecko_pool_quotes(pairs), []
    except (SourceError, KeyError, ValueError) as exc:
        return {}, [f"Gecko confirmation prix: {exc}"]


def rug_report(mint):
    return rugcheck(mint)


class PublicWalletMonitor:
    """Optional public Solana balance-increase observations, NOT authenticated swaps.

    getSignaturesForAddress + getTransaction are only RPC methods this component uses.
    This avoids false claims that an increase necessarily means a purchased token.
    """
    def __init__(self, store, wallets_path, rpc_url='https://api.mainnet-beta.solana.com'):
        self.store, self.wallets_path = store, wallets_path
        self.rpc_url = rpc_url

    def wallets(self):
        try:
            lines = open(self.wallets_path,encoding='utf-8').read().splitlines()
        except FileNotFoundError: return []
        found=[]
        for line in lines:
            w=line.split('#',1)[0].strip()
            if candidate(w) and w not in found: found.append(w)
        return found[:5]

    def rpc(self, method, params):
        if method not in ('getSignaturesForAddress','getTransaction'):
            raise ValueError('Méthode RPC non autorisée')
        payload = json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode()
        req=urllib.request.Request(self.rpc_url,data=payload,
            headers={'Content-Type':'application/json','User-Agent':'MemeRadar/0.1'},method='POST')
        with urllib.request.urlopen(req,timeout=9) as response:
            data=json.load(response)
        if data.get('error'): raise SourceError('RPC error: '+str(data['error'])[:140])
        return data.get('result')

    @staticmethod
    def gained_mints(tx, wallet):
        meta = (tx or {}).get('meta') or {}
        balances={}
        for label, sign in [('preTokenBalances',-1),('postTokenBalances',1)]:
            for item in meta.get(label) or []:
                mint=item.get('mint')
                if item.get('owner') != wallet or not candidate(mint): continue
                raw=((item.get('uiTokenAmount') or {}).get('amount'))
                try: amount=int(raw or '0')
                except (ValueError,TypeError): continue
                decimals=(item.get('uiTokenAmount') or {}).get('decimals') or 0
                # Sum across token accounts with decimal normalization.
                balances[mint]=balances.get(mint,0)+sign*(amount/10**min(int(decimals),18))
        return [mint for mint, change in balances.items() if change>1e-10]

    def scan(self):
        seen, warnings = set(), []
        for wallet in self.wallets():
            try:
                signatures=self.rpc('getSignaturesForAddress',[wallet,{'limit':5}]) or []
                if not signatures: continue
                cursor=self.store.cursor(wallet)
                latest=signatures[0]['signature']
                fresh=[]
                for sig in signatures:
                    if sig.get('signature')==cursor: break
                    if sig.get('err') is None and sig.get('signature'): fresh.append(sig)
                for sig in reversed(fresh[:3]):
                    # Fresh increases only; RPC history is not processed as a new real-time event.
                    if not sig.get('blockTime') or time.time() - sig['blockTime']>900: continue
                    tx=self.rpc('getTransaction',[sig['signature'],{'encoding':'jsonParsed','maxSupportedTransactionVersion':0}])
                    for mint in self.gained_mints(tx,wallet):
                        self.store.save_wallet_event(mint,wallet,sig['signature'],sig['blockTime'])
                        seen.add(mint)
                self.store.set_cursor(wallet,latest)
            except (SourceError, KeyError, OSError, ValueError, urllib.error.URLError) as exc:
                warnings.append(f"Wallet {wallet[:6]}…: {type(exc).__name__}: {str(exc)[:110]}")
        return seen, warnings
