"""Solana memecoin *read-only* screener, multi-source crosscheck and timed observation.

No wallet, trade, transaction, simulated investment, position or private key support.
The ranking is heuristic, never a probability of gains or a prediction.
"""
from __future__ import annotations

import csv
import datetime as dt
from email.utils import parsedate_to_datetime
import json
import math
import re
import sqlite3
import time
import threading
import urllib.error
import urllib.request
from collections import Counter
from statistics import median
from urllib.parse import quote

DEX = "https://api.dexscreener.com"
GECKO = "https://api.geckoterminal.com/api/v2"
RUG = "https://api.rugcheck.xyz/v1/tokens"
WSOL = "So11111111111111111111111111111111111111112"
NON_MEMES = {WSOL, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
             "Es9vMFrzaCERjx75sM5jFf8jGQdLrDhvEE7wxocTPD"}                # USDT
BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
# Paramètres prudents pour la collecte de données ; ils ne sont PAS calibrés
# statistiquement et ne prédisent pas les variations futures.
MAX_PRICE_GAP_PCT = 5.0
FOLLOWUP_GRACE_S = 300  # +2h / +3h à maximum 5 minutes de retard
SAMPLE_INTERVAL_S = 600  # 1 observation toutes les 10 minutes, pendant 3 h
MIN_DISTINCT_BUYERS_H1 = 15  # filtrage exploratoire : ne garantit pas des wallets independants
MAX_BUYS_PER_BUYER_H1 = 12  # limite les signaux potentiellement artificiels
# Hypothèses conservatrices (à calibrer avec des observations réelles).
MAX_5MIN_PUMP_PCT = 25.0
MAX_H1_PUMP_PCT = 100.0
TRUSTED_QUOTES = {WSOL, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                  "Es9vMFrzaCERjx75sM5jFf8jGQdLrDhvEE7wxocTPD"}


class SourceError(Exception):
    pass


# Cadences par fournisseur, cache des découvertes Gecko et protection HTTP 429.
# Les autres fournisseurs et l'interface continuent de tourner pendant une panne Gecko.
_PACE_LOCK = threading.Lock()
_NEXT_ALLOWED = {}
_PAUSED_UNTIL = {}
_RATE_STRIKES = {}
_GECKO_CACHE = {}  # cache uniquement les endpoints de découverte (pas les prix de pools)


def _bucket(url):
    if url.startswith(GECKO + "/"):
        return "gecko", 9.0  # marge de sécurité : <= environ 6,7 appels/minute
    if url.startswith(DEX + "/"):
        if any(x in url for x in ("/token-profiles/", "/token-boosts/", "/ads/", "/community-takeovers/")):
            return "dex_metadata", 1.1
        return "dex_market", 0.25
    if url.startswith(RUG + "/"):
        return "rugcheck", 1.2
    return "other", 1.0


def _gecko_cache_ttl(url):
    if not url.startswith(GECKO + "/"):
        return 0
    if "/new_pools" in url:
        return 75.0  # nouveaux pools plus fréquents que les tendances
    if "/trending_pools" in url:
        return 180.0
    return 0.0  # ne jamais servir une ancienne cotation comme prix actuel


def _wait_for_slot(url):
    key, gap = _bucket(url)
    with _PACE_LOCK:
        now = time.monotonic()
        paused = _PAUSED_UNTIL.get(key, 0.0) - now
        if paused > 0:
            raise SourceError(f"{key} temporairement limité (HTTP 429) : reprise dans {math.ceil(paused)} s")
        delay = max(0.0, _NEXT_ALLOWED.get(key, now) - now)
        _NEXT_ALLOWED[key] = now + delay + gap
    if delay:
        time.sleep(delay)
    # En cas de scan concurrent, respecter un 429 arrivé pendant l'attente.
    with _PACE_LOCK:
        paused = _PAUSED_UNTIL.get(key, 0.0) - time.monotonic()
    if paused > 0:
        raise SourceError(f"{key} temporairement limité (HTTP 429) : reprise dans {math.ceil(paused)} s")


def _retry_after_seconds(headers):
    raw = headers.get('Retry-After', '') if headers else ''
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        pass
    if raw:
        try:
            date = parsedate_to_datetime(raw)
            return max(1.0, (date - dt.datetime.now(dt.timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            pass
    return None


def _mark_limited(url, headers=None):
    key, _ = _bucket(url)
    with _PACE_LOCK:
        strikes = min(4, _RATE_STRIKES.get(key, 0) + 1)
        _RATE_STRIKES[key] = strikes
        fallback = 120 * (2 ** (strikes - 1)) if key == 'gecko' else 30
        pause = max(fallback, _retry_after_seconds(headers) or 0)
        pause = min(900, pause)
        _PAUSED_UNTIL[key] = max(_PAUSED_UNTIL.get(key, 0.0), time.monotonic() + pause)
    return pause


def fetch(url, timeout=13, retries=1):
    """Requêtes publiques avec cache découverte et disjoncteur HTTP 429.

    Le cache ne concerne JAMAIS les cotations, afin de ne pas certifier de faux prix.
    Après un 429 Gecko, la fonction signale immédiatement sa pause : aucun retry en
    rafale et aucune mise en attente des autres flux du radar.
    """
    ttl = _gecko_cache_ttl(url)
    if ttl:
        with _PACE_LOCK:
            item = _GECKO_CACHE.get(url)
            if item and time.monotonic() < item[0]:
                return item[1]
    for attempt in range(retries + 1):
        _wait_for_slot(url)
        try:
            req = urllib.request.Request(url, headers={
                'Accept': ('application/json;version=20230203' if url.startswith(GECKO + '/')
                           else 'application/json'),
                'User-Agent': 'MemeRadar/0.4'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.load(resp)
            if ttl:
                with _PACE_LOCK:
                    if len(_GECKO_CACHE) > 30:
                        _GECKO_CACHE.clear()
                    _GECKO_CACHE[url] = (time.monotonic() + ttl, payload)
            if url.startswith(GECKO + '/'):
                with _PACE_LOCK:
                    _RATE_STRIKES['gecko'] = 0
            return payload
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                pause = _mark_limited(url, exc.headers)
                raise SourceError(f"{_bucket(url)[0]} HTTP 429 : en pause {math.ceil(pause)} s (les autres sources continuent)") from exc
            if attempt < retries:
                time.sleep(1.2)
            else:
                code = f" HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError) else ''
                raise SourceError(f"{url.split('?')[0]}: {type(exc).__name__}{code}") from exc

def gecko_pause_seconds():
    with _PACE_LOCK:
        return max(0,math.ceil(_PAUSED_UNTIL.get('gecko',0)-time.monotonic()))


def number(v):
    if isinstance(v,bool):return None
    try:
        v = float(v)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError, OverflowError):
        return None


def candidate(mint):
    return isinstance(mint, str) and bool(BASE58.fullmatch(mint)) and mint not in NON_MEMES


def dex_discovery(get=fetch):
    found = {}
    warnings = []
    for name, url in (("dex_profiles", f"{DEX}/token-profiles/latest/v1"),
                      ("dex_boosts_paid", f"{DEX}/token-boosts/latest/v1")):
        try:
            rows = get(url)
            if not isinstance(rows, list):
                raise SourceError("réponse Dex invalide")
            for item in rows:
                if not isinstance(item, dict) or item.get("chainId") != "solana":
                    continue
                mint = item.get("tokenAddress")
                if candidate(mint) and mint not in NON_MEMES:
                    found.setdefault(mint, set()).add(name)
        except (SourceError, TypeError, ValueError) as e:
            warnings.append(f"{name}: {e}")
    return found, warnings


def gecko_discovery(get=fetch):
    found, warnings = {}, []
    # Page 2 finds pools already pushed off the first page during busy periods.
    # Gecko calls remain subject to the existing cache and 429 circuit breaker.
    for kind, page in (("new_pools", 1), ("new_pools", 2), ("trending_pools", 1)):
        url = f"{GECKO}/networks/solana/{kind}?include=base_token,quote_token&page={page}"
        try:
            payload = get(url)
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise SourceError("réponse Gecko invalide")
            lookup = {x.get("id"): (x.get("attributes") or {}).get("address")
                      for x in payload.get("included", []) if isinstance(x, dict)}
            for pool in payload["data"]:
                if not isinstance(pool, dict):
                    continue
                rel = pool.get('relationships') or {}
                ids = [((rel.get(side) or {}).get('data') or {}).get('id') for side in ('base_token','quote_token')]
                tokens = [lookup.get(x) or (x[len('solana_'):] if isinstance(x,str) and x.startswith('solana_') else None) for x in ids]
                base, quote_mint = tokens
                # If WSOL/USDC is the base, the other token can still be the meme mint.
                mint = base if candidate(base) else (quote_mint if base in TRUSTED_QUOTES and candidate(quote_mint) else None)
                if mint:
                    found.setdefault(mint, set()).add(f"gecko_{kind}")
        except (SourceError, TypeError, ValueError) as e:
            warnings.append(f"gecko_{kind}: {e}")
    return found, warnings


def discover(get=fetch):
    a, wa = dex_discovery(get)
    b, wb = gecko_discovery(get)
    for mint, sources in b.items():
        a.setdefault(mint, set()).update(sources)
    return a, wa + wb


def dex_pair(mint, get=fetch, pair_address=None):
    payload = get(f"{DEX}/token-pairs/v1/solana/{quote(mint)}")
    pairs = payload if isinstance(payload, list) else (payload.get("pairs") if isinstance(payload, dict) else [])
    if not isinstance(pairs, list):
        return None
    # Prevent accidental token identity inversions (base vs quote).
    valid = [p for p in pairs if isinstance(p, dict) and p.get("chainId") == "solana"
             and (p.get("baseToken") or {}).get("address") == mint
             and (p.get("quoteToken") or {}).get("address") in TRUSTED_QUOTES
             and (pair_address is None or p.get('pairAddress') == pair_address)
             and number(p.get("priceUsd")) is not None and number(p.get("priceUsd")) > 0]
    return max(valid, key=lambda p: number((p.get("liquidity") or {}).get("usd")) or 0) if valid else None


def gecko_prices(mints, get=fetch):
    """Get independent USD prices for up to 20 mints in one public API request."""
    out = {}
    for start in range(0, len(mints), 20):
        group = mints[start:start + 20]
        data = get(f"{GECKO}/simple/networks/solana/token_price/{','.join(quote(m) for m in group)}")
        prices = (data or {}).get("data", {}).get("attributes", {}).get("token_prices", {})
        if isinstance(prices, dict):
            for mint in group:
                p = number(prices.get(mint) or prices.get(mint.lower()))
                if p is not None and p > 0:
                    out[mint] = p
    return out


def gecko_pool_quotes(pairs, get=fetch):
    """Vérification d'une PAIRE EXACTE GeckoTerminal (pas un prix agrégé par mint).

    Nombre d'appels borné : au plus un appel par groupe de 10 pools. Une paire
    absente ou retournée sans identité de base/quote n'est PAS certifiée.
    """
    out = {}
    valid = {}
    for mint, pair in pairs.items():
        if not isinstance(pair, dict):
            continue
        address = pair.get('pairAddress')
        base = (pair.get('baseToken') or {}).get('address')
        quote_mint = (pair.get('quoteToken') or {}).get('address')
        if candidate(address) and base == mint and quote_mint in TRUSTED_QUOTES:
            valid[address] = (mint, quote_mint)
    addresses = list(valid)
    for start in range(0, len(addresses), 10):
        group = addresses[start:start+10]
        payload = get(f"{GECKO}/networks/solana/pools/multi/{','.join(quote(a) for a in group)}")
        rows = payload.get('data', []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            raise SourceError('Gecko: liste de pools invalide')
        for row in rows:
            if not isinstance(row, dict):
                continue
            attrs = row.get('attributes') or {}
            address = attrs.get('address')
            if address not in valid:
                continue
            mint, quote_mint = valid[address]
            rel = row.get('relationships') or {}
            base_id = (((rel.get('base_token') or {}).get('data') or {}).get('id'))
            quote_id = (((rel.get('quote_token') or {}).get('data') or {}).get('id'))
            if base_id != 'solana_'+mint or quote_id != 'solana_'+quote_mint:
                continue
            px = number(attrs.get('base_token_price_usd'))
            liquidity = number(attrs.get('reserve_in_usd'))
            h1 = (attrs.get('transactions') or {}).get('h1') or {}
            unique_buyers = number(h1.get('buyers'))
            if px is not None and px > 0:
                out[mint] = {'price': px, 'liquidity_usd': liquidity,
                             'buyers_h1': unique_buyers, 'pair_address': address}
    return out


def rugcheck(mint, get=fetch):
    data = get(f"{RUG}/{quote(mint)}/report")
    if not isinstance(data, dict) or not isinstance(data.get("risks"), list):
        raise SourceError("rapport RugCheck incomplet")
    tok = data.get("token") or {}
    def authority(key):
        if key in tok:
            return tok[key] is not None and tok[key] != ""
        if key in data:
            return data[key] is not None and data[key] != ""
        return None
    holders = data.get("topHolders")
    # Contrôle du verrou LP rattaché à la PAIRE affichée, pas à une paire quelconque.
    # Des protocoles n'exposent pas le lock ici : on classera alors le lock « inconnu ».
    pool_locks = {}
    for market in data.get('markets', []) if isinstance(data.get('markets'), list) else []:
        if not isinstance(market, dict):
            continue
        lp = market.get('lp') or {}
        pct = number(lp.get('lpLockedPct')) if isinstance(lp, dict) else None
        pubkey = market.get('pubkey')
        if isinstance(pubkey, str) and pct is not None and 0 <= pct <= 100:
            pool_locks[pubkey] = pct
    risk_score = number(data.get('score_normalised'))
    top10_raw = None
    top10_clean = None
    excluded = []
    known = data.get('knownAccounts') or {}
    if not isinstance(known, dict): known = {}
    # RugCheck markets contain liquidity token-ACCOUNT addresses, not just pool pubkeys.
    # Only exclude an account when the report explicitly identifies it as a vault/curve.
    reserves = set()
    for market in data.get('markets') or []:
        if not isinstance(market, dict): continue
        for key in ('liquidityA', 'liquidityB'):
            addr = market.get(key)
            if isinstance(addr, str) and addr: reserves.add(addr)
    def is_protocol_account(h):
        for address in (h.get('address'), h.get('owner')):
            if not isinstance(address, str): continue
            if address in reserves: return 'market_reserve'
            tag = known.get(address)
            if not isinstance(tag, dict): continue
            kind = str(tag.get('type') or '').lower()
            name = str(tag.get('name') or '').lower()
            if kind in ('amm', 'locker', 'bonding_curve', 'burn', 'pool', 'vault') or (
                    any(x in name for x in ('bonding curve','liquidity pool','amm pool','token vault'))
                    and kind not in ('user', 'wallet')):
                return 'known_protocol_account'
        return None
    if isinstance(holders, list) and len(holders) >= 10:
        first = [h for h in holders[:10] if isinstance(h, dict)]
        pcts = [number(h.get('pct')) for h in first]
        if len(pcts) == 10 and all(x is not None and 0 <= x <= 100 for x in pcts):
            top10_raw = round(sum(pcts), 3) if sum(pcts) <= 100.01 else None
        cleaned = []
        for h in holders:
            if not isinstance(h, dict): continue
            pct = number(h.get('pct'))
            if pct is None or not 0<=pct<=100: continue
            reason = is_protocol_account(h)
            if reason:
                excluded.append({'address':str(h.get('address') or '')[:60], 'reason':reason,'pct':pct})
            else:
                cleaned.append(pct)
        # A top-10 of *private holders* needs 10 non-protocol entries.
        # It is a share of TOTAL token supply, not circulating supply.
        if len(cleaned)>=10:
            total = sum(cleaned[:10])
            if total <= 100.01: top10_clean = round(total,3)
    risks = [dict(x) for x in data['risks'] if isinstance(x, dict)]
    return {'mint_active': authority('mintAuthority'), 'freeze_active': authority('freezeAuthority'),
            'top10_pct': top10_clean, 'top10_raw_pct': top10_raw,
            'top10_method': 'excluded_verified_protocol_accounts' if top10_clean is not None else 'unverified',
            'holder_exclusions': excluded[:20], 'rugged': data.get('rugged'),
            'risk_levels': [str(x.get('level', '')).lower() for x in risks],
            'risk_details': [{'name':str(x.get('name') or ''), 'level':str(x.get('level') or '').lower(),
                              'description':str(x.get('description') or '')[:180]} for x in risks],
            'lp_locked_by_pool': pool_locks, 'rugcheck_risk_score': risk_score}



def assess(mint, pair, gecko_price, safety, sources, now, min_score=65):
    """Fail closed on important unknowns; scoring is an UNCALIBRATED ordinal heuristic."""
    reasons = []
    if not pair:
        return {"reasons": ["aucune_paire_compatible"], "accepted": False, "mint": mint}
    px = number(pair.get("priceUsd"))
    native = number(pair.get("priceNative"))
    liq = number((pair.get("liquidity") or {}).get("usd"))
    fdv = number(pair.get("fdv"))
    age_ms = number(pair.get("pairCreatedAt"))
    age_m = (now - age_ms / 1000) / 60 if age_ms is not None else None
    vol = number((pair.get("volume") or {}).get("h1"))
    txns = (pair.get("txns") or {}).get("h1") or {}
    buys, sells = number(txns.get("buys")), number(txns.get("sells"))
    m5 = number((pair.get("priceChange") or {}).get("m5"))
    h1 = number((pair.get("priceChange") or {}).get("h1"))
    if px is None or px <= 0 or native is None or native <= 0:
        reasons.append("prix_incomplet")
    if liq is None or liq < 50_000:
        reasons.append("liquidite_insuffisante_ou_inconnue")
    if fdv is None or not 20_000 <= fdv <= 5_000_000:
        reasons.append("fdv_hors_plage_ou_inconnue")
    if age_m is None or not 10 <= age_m <= 24 * 60:
        reasons.append("age_paire_hors_plage_ou_inconnu")
    if vol is None or vol < 10_000:
        reasons.append("volume_h1_insuffisant")
    if buys is None or sells is None or buys + sells < 20 or buys < 1.15 * max(sells, 1):
        reasons.append("pression_acheteuse_non_confirmee")
    if m5 is None or not -10 <= m5 <= MAX_5MIN_PUMP_PCT or h1 is None or not -20 <= h1 <= MAX_H1_PUMP_PCT:
        reasons.append("momentum_extreme_ou_inconnu")
    # A paid promotion is NOT discovery evidence. Require a separate organic feed.
    if sources and set(sources) <= {"dex_boosts_paid"}:
        reasons.append("boost_payant_sans_decouverte_organique")
    if gecko_price is None or px is None or px <= 0:
        diff = None
        reasons.append("prix_non_confirme_geckoterminal")
    else:
        diff = abs(px - gecko_price) / ((px + gecko_price) / 2) * 100
        if diff > MAX_PRICE_GAP_PCT:
            reasons.append("ecart_prix_sources_superieur_5pct")
    if not safety:
        reasons.append("rugcheck_inconnu")
    else:
        for key in ("mint_active", "freeze_active"):
            if safety.get(key) is None:
                reasons.append(f"inconnu_{key}")
            elif safety.get(key):
                reasons.append(f"actif_{key}")
        if safety.get("rugged") is True or any(x in ("danger", "critical", "high", "very high", "severe", "extreme")
            for x in safety.get("risk_levels", [])):
            reasons.append("risque_rug_eleve")
        if safety.get("top10_pct") is None:
            reasons.append("top10_inconnu")
        elif safety["top10_pct"] > 35:
            reasons.append("top10_concentre")
        pool_locks = safety.get('lp_locked_by_pool') or {}
        locked_pct = pool_locks.get(pair.get('pairAddress'))
        if locked_pct is None:
            reasons.append('verrou_liquidite_paire_non_verifiable')
        elif locked_pct < 90:
            reasons.append('liquidite_paire_insuffisamment_verrouillee')
        risk_score = safety.get('rugcheck_risk_score')
        if risk_score is None or not 0 <= risk_score <= 100:
            reasons.append('score_rugcheck_inconnu')
        elif risk_score > 40:
            reasons.append('score_rugcheck_trop_risque')
    score = None
    if not reasons:
        # Capped components; defined only when ALL required data exists.
        buyshare = buys / (buys + sells)
        ratio = vol / liq
        score = round(min(20, 12 * math.log10(max(liq / 20000, 1)) + 2)
                      + min(20, ratio * 14)
                      + min(20, max(0, (buyshare - .5) / .25) * 20)
                      + (10 if 30 <= age_m <= 600 else 6)
                      + (15 if 0 <= m5 <= 25 and -5 <= h1 <= 75 else 8)
                      + 10  # two independently retrieved price feeds
                      + (5 if safety["top10_pct"] <= 20 else 0)
                      - 5 * sum(x in ("warn", "warning") for x in safety.get("risk_levels", [])), 1)
        score = max(0, min(100, score))
        if score < min_score:
            reasons.append("score_sous_seuil")
    raw_symbol = str((pair.get("baseToken") or {}).get("symbol") or "?")
    safe_symbol = "".join(ch for ch in raw_symbol if ch.isprintable() and ch not in "\x1b\x7f")[:32]
    pair_address = (pair.get("pairAddress") or "")
    # Never trust an arbitrary external URL inside a token metadata response.
    safe_url = f"https://dexscreener.com/solana/{pair_address if candidate(pair_address) else mint}"
    # A narrative or a smart-wallet endorsement cannot be inferred from volume or price.
    # Keep these checks explicitly unverified for the user to inspect manually.
    discovery_kind = ("tendance_gecko" if "gecko_trending_pools" in sources
                      else "nouveau_pool_gecko" if "gecko_new_pools" in sources
                      else "profil_dex" if "dex_profiles" in sources
                      else "boost_seul" if "dex_boosts_paid" in sources
                      else "source_inconnue")
    return {"mint": mint, "pair_address": pair_address,
            "symbol": safe_symbol or "?",
            "discovery_kind": discovery_kind,
            "narrative_status": "non_verifie",
            "smart_wallet_status": "non_verifie",
            "price_usd": px, "gecko_price_usd": gecko_price, "price_gap_pct": round(diff, 2) if diff is not None else None,
            "liquidity_usd": liq, "fdv_usd": fdv, "age_min": round(age_m, 1) if age_m is not None else None,
            "volume_h1_usd": vol, "buys_h1": buys, "sells_h1": sells,
            "change_m5_pct": m5, "change_h1_pct": h1,
            "top10_pct": safety.get("top10_pct") if safety else None,
            "risk_levels": safety.get("risk_levels") if safety else None,
            "lp_locked_pct": (safety.get('lp_locked_by_pool') or {}).get(pair.get('pairAddress')) if safety else None,
            "rugcheck_risk_score": safety.get('rugcheck_risk_score') if safety else None,
            "score": score, "accepted": not reasons, "reasons": reasons,
            "sources": sorted(sources), "url": safe_url}


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=4000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS signals(
                id INTEGER PRIMARY KEY, mint TEXT NOT NULL UNIQUE, symbol TEXT NOT NULL,
                first_ts REAL NOT NULL, price_usd REAL NOT NULL, score REAL NOT NULL,
                info_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observations(
                signal_id INTEGER NOT NULL, hour INTEGER NOT NULL CHECK(hour IN (2,3)),
                planned_ts REAL NOT NULL, observed_ts REAL, price_usd REAL,
                status TEXT NOT NULL CHECK(status IN ('observed','missed','unavailable')),
                PRIMARY KEY(signal_id,hour), FOREIGN KEY(signal_id) REFERENCES signals(id));
            CREATE TABLE IF NOT EXISTS samples(
                signal_id INTEGER NOT NULL, slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 18),
                planned_ts REAL NOT NULL, observed_ts REAL, price_usd REAL, liquidity_usd REAL,
                status TEXT NOT NULL CHECK(status IN ('observed','missed','unavailable')),
                PRIMARY KEY(signal_id,slot), FOREIGN KEY(signal_id) REFERENCES signals(id));
            CREATE TABLE IF NOT EXISTS candidate_checks(
                mint TEXT PRIMARY KEY, last_checked_ts REAL NOT NULL,
                accepted INTEGER NOT NULL CHECK(accepted IN (0,1)),
                reasons_json TEXT NOT NULL);
        """)
        self.db.commit()

    def recent_checks(self, now, wait_s=600):
        """Avoid expensive repeated security checks for the same recently rejected mint.

        Rejected tokens remain eligible for a fresh evaluation after 10 minutes.
        """
        return {r[0] for r in self.db.execute(
            "SELECT mint FROM candidate_checks WHERE last_checked_ts>=?", (now - wait_s,))}

    def save_check(self, result, now):
        with self.db:
            self.db.execute("""INSERT INTO candidate_checks(mint,last_checked_ts,accepted,reasons_json)
                VALUES(?,?,?,?) ON CONFLICT(mint) DO UPDATE SET
                last_checked_ts=excluded.last_checked_ts,
                accepted=excluded.accepted,reasons_json=excluded.reasons_json""",
                (result['mint'], now, int(result['accepted']),
                 json.dumps(result.get('reasons', []),ensure_ascii=False)))

    def known(self):
        return {r[0] for r in self.db.execute("SELECT mint FROM signals")}

    def add(self, record, now):
        if record["price_usd"] is None or record["price_usd"] <= 0 or not record["accepted"]:
            raise ValueError("Signal non conforme")
        before = self.db.total_changes
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO signals(mint,symbol,first_ts,price_usd,score,info_json) "
                            "VALUES (?,?,?,?,?,?)", (record["mint"], record["symbol"], now,
                                                    record["price_usd"], record["score"],
                                                    json.dumps(record, ensure_ascii=False)))
        return self.db.total_changes > before

    def all(self):
        return list(self.db.execute("SELECT * FROM signals ORDER BY first_ts DESC"))

    def pending(self, now):
        rows = self.db.execute("""SELECT s.id,s.mint,s.first_ts,s.price_usd,s.info_json,o.status AS old_status,
                                h.hour FROM signals s CROSS JOIN
                                (SELECT 2 AS hour UNION SELECT 3) h
                                LEFT JOIN observations o ON o.signal_id=s.id AND o.hour=h.hour
                                WHERE s.first_ts + h.hour*3600<=? AND
                                (o.status IS NULL OR o.status='unavailable')""", (now,)).fetchall()
        return rows

    def save_observation(self, row, now, price, status):
        with self.db:
            self.db.execute("""INSERT INTO observations(signal_id,hour,planned_ts,observed_ts,price_usd,status)
                              VALUES(?,?,?,?,?,?) ON CONFLICT(signal_id,hour)
                              DO UPDATE SET observed_ts=excluded.observed_ts,price_usd=excluded.price_usd,
                                            status=excluded.status""", (row["id"], row["hour"],
                                            row["first_ts"] + row["hour"]*3600,
                                            now if status == "observed" else None,
                                            price if status == "observed" else None, status))

    def sample_report(self):
        return list(self.db.execute("""SELECT s.mint, s.id AS signal_id, s.price_usd AS initial_px,
            p.slot,p.status,p.price_usd,p.liquidity_usd,p.observed_ts
            FROM signals s JOIN samples p ON p.signal_id=s.id
            ORDER BY s.id,p.slot"""))

    def record_sample(self, signal_id, slot, first_ts, now, price, liquidity, status):
        with self.db:
            self.db.execute("""INSERT INTO samples(signal_id,slot,planned_ts,observed_ts,price_usd,liquidity_usd,status)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(signal_id,slot)
                DO UPDATE SET observed_ts=excluded.observed_ts,price_usd=excluded.price_usd,
                liquidity_usd=excluded.liquidity_usd,status=excluded.status""",
                (signal_id,slot,first_ts+slot*SAMPLE_INTERVAL_S,
                 now if status == 'observed' else None,
                 price if status == 'observed' else None,
                 liquidity if status == 'observed' else None,status))

    def report(self):
        return list(self.db.execute("""SELECT s.*, o2.status AS status2, o2.price_usd AS px2,
                          o2.observed_ts AS ts2, o3.status AS status3, o3.price_usd AS px3,
                          o3.observed_ts AS ts3 FROM signals s
                          LEFT JOIN observations o2 ON s.id=o2.signal_id AND o2.hour=2
                          LEFT JOIN observations o3 ON s.id=o3.signal_id AND o3.hour=3
                          ORDER BY s.first_ts DESC"""))


def time_label(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%d/%m %H:%M UTC")


def price_label(p):
    if p is None:
        return "inconnu"
    return f"${p:.10g}"


def fmt_pct(p):
    return f"{p:+.2f}%" if p is not None else "en attente"


def percent(now_price, initial_price):
    if now_price is None or initial_price is None or initial_price <= 0:
        return None
    return (now_price / initial_price - 1) * 100


def refresh_due(store, get=fetch, now=None):
    """Suivi à +2h/+3h UNIQUEMENT sur la paire initialement signalée."""
    live_clock = now is None
    now = time.time() if now is None else now
    rows = store.pending(now)
    results = Counter()
    due = [r for r in rows if now <= r["first_ts"] + r["hour"]*3600 + FOLLOWUP_GRACE_S]
    pair_map = {}
    for r in due:
        mint = r['mint']
        if mint in pair_map:
            continue
        locked_pair = json.loads(r['info_json']).get('pair_address')
        try:
            pair_map[mint] = dex_pair(mint, get=get, pair_address=locked_pair) if locked_pair else None
        except SourceError:
            pair_map[mint] = None
    try:
        gecko = gecko_pool_quotes(pair_map, get=get)
    except SourceError:
        gecko = {}
    measured_at = time.time() if live_clock else now
    for r in rows:
        planned = r["first_ts"] + r["hour"] * 3600
        p = pair_map.get(r['mint'])
        dx = number(p.get('priceUsd')) if p else None
        g = gecko.get(r['mint'])
        other = g.get('price') if g else None
        verified = dx is not None and dx > 0 and other is not None and other > 0 and (
            abs(dx-other) / ((dx+other)/2)*100 <= MAX_PRICE_GAP_PCT)
        if measured_at > planned + FOLLOWUP_GRACE_S:
            status, price = 'missed', None
        elif verified:
            status, price = 'observed', dx
        else:
            status, price = 'unavailable', None
        store.save_observation(r, measured_at, price, status)
        results[status] += 1
    return results


def scan(store, get=fetch, now=None, max_candidates=20, min_score=75):
    """Source snapshots are re-fetched AFTER slow security checks to avoid stale alert prices."""
    live_clock = now is None
    now = time.time() if now is None else now
    candidates, warnings = discover(get)
    already = store.known()
    checked_recently = store.recent_checks(now)
    pending = [(mint, sources) for mint, sources in candidates.items()
               if mint not in already and mint not in checked_recently]
    pending.sort(key=lambda x: (-len(x[1]), x[0]))
    pending = pending[:max_candidates]
    pair_map, safety_map, quote_times = {}, {}, {}
    # Première passe : vérifier qu'une paire existe avant de solliciter RugCheck.
    for mint, _ in pending:
        try:
            pair_map[mint] = dex_pair(mint, get=get)
        except SourceError as e:
            warnings.append(f"paire {mint}: {e}")
    for mint, sources in pending:
        p = pair_map.get(mint)
        if p:
            preliminary = assess(mint, p, None, None, sources, now)
            # Seuls les champs liés à la sécurité et à la confirmation Gecko
            # devraient encore manquer. Les exclusions de marché sont définitives.
            blocked = [r for r in preliminary['reasons'] if r not in
                       ('prix_non_confirme_geckoterminal', 'rugcheck_inconnu')]
            if blocked:
                continue
            try:
                safety_map[mint] = rugcheck(mint, get=get)
            except SourceError as e:
                warnings.append(f"RugCheck {mint}: {e}")
    # Nouvelle cotation juste avant de publier : l'analyse RugCheck peut prendre du temps.
    # On n'utilise jamais le prix ancien de la première passe comme prix d'alerte.
    for mint, _ in pending:
        if pair_map.get(mint):
            try:
                pair_map[mint] = dex_pair(mint, get=get)
                quote_times[mint] = time.time() if live_clock else now
            except SourceError as e:
                pair_map[mint] = None
                warnings.append(f"prix final {mint}: {e}")
    confirmed = {}
    try:
        confirmed = gecko_pool_quotes(pair_map, get=get)
    except SourceError as e:
        warnings.append(f"vérification GeckoTerminal par pool indisponible: {e}")
    reviewed = []
    for mint, sources in pending:
        t = quote_times.get(mint, now)
        proof = confirmed.get(mint) or {}
        result = assess(mint, pair_map.get(mint), proof.get('price'),
                        safety_map.get(mint), sources, t, min_score)
        result['gecko_same_pool_verified'] = bool(proof)
        result['buyers_distinct_h1'] = proof.get('buyers_h1')
        result['gecko_liquidity_usd'] = proof.get('liquidity_usd')
        if result.get('pair_address') and not proof:
            result['reasons'].append('meme_paire_gecko_non_verifiee')
        if proof:
            buyers = proof.get('buyers_h1')
            buys = result.get('buys_h1')
            if buyers is None or buyers < MIN_DISTINCT_BUYERS_H1:
                result['reasons'].append('acheteurs_distincts_insuffisants_ou_inconnus')
            elif buys is not None and buys / buyers > MAX_BUYS_PER_BUYER_H1:
                result['reasons'].append('trop_achats_par_acheteur_distinct')
            gd = proof.get('liquidity_usd')
            dd = result.get('liquidity_usd')
            if gd is None or dd is None or gd <= 0 or dd <= 0 or not 0.5 <= gd/dd <= 2:
                result['reasons'].append('ecart_liquidite_sources_important_ou_inconnu')
        if result['reasons']:
            result['accepted'] = False
        # Ne pas publier une cotation qui serait devenue ancienne pendant la vérification.
        if live_clock and time.time() - t > 65:
            result["accepted"] = False
            result["reasons"].append("prix_final_plus_vieux_que_65s")
        reviewed.append(result)
        store.save_check(result, time.time() if live_clock else t)
        if result["accepted"]:
            # La référence temporelle est l'heure de réception de la cotation Dex,
            # pas l'heure de fin d'analyse RugCheck / GeckoTerminal.
            store.add(result, t)
    return reviewed, warnings, len(candidates)


def sample_prices(store, get=fetch, now=None):
    """Mesures 10 min jusqu'à 3h, y compris les indisponibilités et créneaux manqués.

    Jamais de remplissage avec un prix ultérieur : chaque créneau est compté une fois.
    """
    live_clock = now is None
    now = time.time() if now is None else now
    active = store.db.execute("""SELECT id,mint,first_ts,info_json FROM signals
        WHERE first_ts + ? <= ?""", (SAMPLE_INTERVAL_S, now)).fetchall()
    due, results = [], Counter()
    for signal in active:
        maxslot = min(18, int((now - signal['first_ts']) // SAMPLE_INTERVAL_S))
        old = {r['slot']:r['status'] for r in store.db.execute(
            'SELECT slot,status FROM samples WHERE signal_id=?',(signal['id'],))}
        for slot in range(1, maxslot+1):
            if old.get(slot) in ('observed','missed'):
                continue
            planned = signal['first_ts']+slot*SAMPLE_INTERVAL_S
            if now > planned + FOLLOWUP_GRACE_S:
                store.record_sample(signal['id'], slot, signal['first_ts'], now, None, None, 'missed')
                results['missed'] += 1
            else:
                due.append((signal,slot))
    pair_map = {}
    for mint in dict.fromkeys(signal['mint'] for signal,_ in due):
        try:
            signal = next(s for s, _ in due if s['mint'] == mint)
            locked_pair = json.loads(signal['info_json']).get('pair_address')
            pair_map[mint] = dex_pair(mint, get=get, pair_address=locked_pair) if locked_pair else None
        except SourceError:
            pair_map[mint] = None
    try:
        gecko = gecko_pool_quotes(pair_map, get=get)
    except SourceError:
        gecko = {}
    measured_at = time.time() if live_clock else now
    for signal,slot in due:
        if measured_at > signal['first_ts'] + slot*SAMPLE_INTERVAL_S + FOLLOWUP_GRACE_S:
            store.record_sample(signal['id'],slot,signal['first_ts'],measured_at,
                                None,None,'missed')
            results['missed'] += 1
            continue
        p = pair_map.get(signal['mint'])
        px = number(p.get('priceUsd')) if p else None
        liq = number((p.get('liquidity') or {}).get('usd')) if p else None
        other = (gecko.get(signal['mint']) or {}).get('price')
        verified = (px is not None and px > 0 and liq is not None and liq >= 0
                    and other is not None and other > 0 and
                    abs(px-other)/((px+other)/2)*100 <= MAX_PRICE_GAP_PCT)
        status = 'observed' if verified else 'unavailable'
        store.record_sample(signal['id'],slot,signal['first_ts'],measured_at,
                            px if verified else None,liq if verified else None,status)
        results[status] += 1
    return results


def print_scan(results, warnings, total):
    accepted = sorted((r for r in results if r["accepted"]), key=lambda x: x["score"], reverse=True)
    print(f"Découverts : {total} | Analysés : {len(results)} | Nouveaux signaux : {len(accepted)}")
    if accepted:
        for r in accepted:
            print(f"\n  ${r['symbol']}  | SCORE {r['score']:.1f}/100 (NON calibré)")
            print(f"  Prix {price_label(r['price_usd'])} | Vérification Gecko {price_label(r['gecko_price_usd'])}"
                  f" (écart {r['price_gap_pct']}%)")
            print(f"  Liquidité ${r['liquidity_usd']:,.0f} | Volume 1 h ${r['volume_h1_usd']:,.0f} | "
                  f"Achats/Ventes 1 h {r['buys_h1']:.0f}/{r['sells_h1']:.0f}")
            print(f"  Âge {r['age_min']} min | Variation 5 min {r['change_m5_pct']}% | 1 h {r['change_h1_pct']}%")
            print(f"  Top10 {r['top10_pct']:.1f}% | LP verrouillée {r['lp_locked_pct']:.1f}% | "
                  f"RugCheck risque {r['rugcheck_risk_score']} | Alertes {r['risk_levels']}")
            print(f"  Découverte : {r['discovery_kind']} | Sources : {', '.join(r['sources'])}")
            print(f"  Acheteurs distincts 1h (Gecko): {r.get('buyers_distinct_h1')} | pool exact verifie: {r.get('gecko_same_pool_verified')}")
            print("  CONTROLES HUMAINS NON REALISES : narratif/catalyseur, réseaux sociaux, wallets/insiders.")
            print("  Ceci est un SIGNAL D'OBSERVATION, pas un conseil d'achat ni une prédiction de 2-3 h.")
            print(f"  Adresse : {r['mint']}\n  Pool : {r['pair_address']}\n  DexScreener : {r['url']}")
    else:
        print("Aucun signal satisfaisant les contrôles. C'est un résultat normal, pas une erreur.")
    reasons = Counter(reason for r in results if not r["accepted"] for reason in r["reasons"])
    if reasons:
        print("\nMotifs de rejet : " + ", ".join(f"{k}={v}" for k, v in reasons.most_common(10)))
    if warnings:
        print("\nSources indisponibles ou incomplètes :")
        for item in warnings[:12]:
            print("  ! " + item)


def print_report(store):
    rows = store.report()
    sampled = {}
    for point in store.sample_report():
        sampled.setdefault(point['mint'], []).append(point)
    print(f"Signaux : {len(rows)}. Variation du prix observé, pas gain investisseur, hors frais.")
    for r in rows:
        def show(hour):
            status, px, ts = r[f"status{hour}"], r[f"px{hour}"], r[f"ts{hour}"]
            if status == "observed":
                return f"{fmt_pct(percent(px, r['price_usd']))} ({time_label(ts)})"
            return status or "en attente"
        print(f"${r['symbol']} | {r['mint']} | Score {r['score']} | "
              f"t0 {time_label(r['first_ts'])} {price_label(r['price_usd'])} | +2h {show(2)} | +3h {show(3)}")
        points = sampled.get(r['mint'], [])
        vals = [percent(p['price_usd'],r['price_usd']) for p in points if p['status']=='observed']
        missing = sum(p['status'] != 'observed' for p in points)
        if vals:
            liqs = [p['liquidity_usd'] for p in points if p['status']=='observed'
                    and p['liquidity_usd'] is not None]
            first_liq = json.loads(r['info_json']).get('liquidity_usd')
            warning = ''
            if first_liq and liqs and min(liqs) < first_liq * .5:
                warning = ' | ALERTE : liquidité observée divisée par plus de deux'
            print(f"  Échantillons 10min: {len(vals)} valides, {missing} absents; "
                  f"plus bas OBSERVÉ {fmt_pct(min(vals))}, plus haut OBSERVÉ {fmt_pct(max(vals))}{warning}")
        elif points:
            print(f"  Échantillons 10min: 0 valides, {missing} absents / invérifiables")
    for hour in (2, 3):
        changes = [percent(r[f"px{hour}"], r["price_usd"]) for r in rows if r[f"status{hour}"] == "observed"]
        if changes:
            print(f"Bilan +{hour}h (prix bruts) : {len(changes)}/{len(rows)} signaux mesurés, "
                  f"{sum(x > 0 for x in changes)}/{len(changes)} positifs parmi les MESURÉS, "
                  f"médiane {fmt_pct(median(changes))}. "
                  f"Attention : les {len(rows)-len(changes)} autres ne sont pas des gagnants confirmés.")
        else:
            print(f"Bilan +{hour}h : aucune observation valide sur {len(rows)} signaux")


def export_csv(store, destination):
    rows = store.report()
    sampled = {}
    for point in store.sample_report():
        sampled.setdefault(point['mint'], []).append(point)
    with open(destination, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["mint", "symbol", "date_utc", "score_non_calibre", "price_t0_usd", "status_2h",
                         "price_2h_usd", "change_2h_pct", "observed_2h_utc", "status_3h", "price_3h_usd",
                         "change_3h_pct", "observed_3h_utc", "dex_url", "samples_valides",
                         "samples_absents", "variation_min_observee_pct", "variation_max_observee_pct",
                         "liquidite_initiale_usd", "liquidite_min_observee_usd"])
        for r in rows:
            info = json.loads(r["info_json"])
            points = sampled.get(r['mint'], [])
            valid = [p for p in points if p['status'] == 'observed']
            variations = [percent(p['price_usd'],r['price_usd']) for p in valid]
            liquidities = [p['liquidity_usd'] for p in valid if p['liquidity_usd'] is not None]
            writer.writerow([r["mint"], r["symbol"], time_label(r["first_ts"]), r["score"], r["price_usd"],
                             r["status2"], r["px2"], percent(r["px2"], r["price_usd"]) if r["status2"] == "observed" else "",
                             time_label(r["ts2"]) if r["ts2"] else "", r["status3"], r["px3"],
                             percent(r["px3"], r["price_usd"]) if r["status3"] == "observed" else "",
                             time_label(r["ts3"]) if r["ts3"] else "", info.get("url"),
                             len(valid), len(points)-len(valid), min(variations) if variations else "",
                             max(variations) if variations else "",info.get('liquidity_usd'),
                             min(liquidities) if liquidities else ""])
    return len(rows)
