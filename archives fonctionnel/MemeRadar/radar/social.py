"""Read-only J7Tracker feed integration using its documented Socket.IO v4 feed.

Does not scrape pages, automate accounts, trade, or authenticate without the user's
own J7_FEED_TOKEN. A large-account mention is NOT a forecast of a price increase.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import threading
import time
from typing import Any

ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
ALPHA = set(ALPHABET)
# Addresses in free text must have token boundaries, not just arbitrary substrings.
SOLANA_ADDRESS_RE = re.compile(r'(?<![A-Za-z0-9])([1-9A-HJ-NP-Za-km-z]{32,44})(?![A-Za-z0-9])')
TICKER_RE = re.compile(r'(?<![A-Za-z0-9])\$([A-Za-z][A-Za-z0-9]{1,11})(?![A-Za-z0-9])')
STOP_TICKERS = {'SOL', 'BTC', 'ETH', 'USDC', 'USDT', 'USD', 'EUR', 'BNB'}
MAX_BODY = 600
# Only known post-owned text/structured metadata: do not mine quote/reply bodies,
# author biographies or arbitrary response objects for endorsements.
POST_TEXT_FIELDS = ('text', 'fullText', 'noteText')
RICH_TEXT_FIELDS = ('title', 'description', 'text', 'url')


def is_solana_address(s: str) -> bool:
    if not isinstance(s, str) or not 32 <= len(s) <= 44 or any(c not in ALPHA for c in s):
        return False
    n = 0
    for c in s:
        n = n * 58 + ALPHABET.index(c)
    # Leading 1s are zero-valued base58 bytes.
    length = len(n.to_bytes((n.bit_length()+7)//8, 'big')) + len(s) - len(s.lstrip('1'))
    return length == 32


def extract_mints(tweet: dict) -> list[str]:
    """Strict Solana CA extraction from the post's *own* text and rich card.

    J7 may enrich a tweet with card, article and components in later updates.
    We never infer a CA from a ticker, and never treat quoted/replied-to text
    as an endorsement by the author of the outer tweet.
    """
    if not isinstance(tweet,dict): return []
    possible=[]
    chain=str(tweet.get('chain') or '').lower()
    if chain in ('', 'sol', 'solana'):
        direct=tweet.get('contractAddress')
        if isinstance(direct,str): possible.append(direct)
        extra=tweet.get('extraContractAddresses')
        if isinstance(extra,list): possible.extend(x for x in extra[:8] if isinstance(x,str))
    chunks=[]
    for key in POST_TEXT_FIELDS:
        if isinstance(tweet.get(key),str): chunks.append(tweet[key][:8000])
    for field in ('preferredTradingUrl',):
        if isinstance(tweet.get(field),str): chunks.append(tweet[field][:2000])
    for key in ('card','article'):
        item=tweet.get(key)
        if isinstance(item,dict):
            chunks.extend(str(item[k])[:4000] for k in RICH_TEXT_FIELDS if isinstance(item.get(k),str))
    comps=tweet.get('components')
    if isinstance(comps,list):
        for item in comps[:20]:
            if isinstance(item,dict) and item.get('type')=='text' and isinstance(item.get('text'),str):
                chunks.append(item['text'][:4000])
    # Also capture Solana CA in supported launchpad links, since it is present
    # literally in the URL. Never expand shortened links in the hot path.
    for chunk in chunks:
        possible.extend(SOLANA_ADDRESS_RE.findall(chunk))
    return list(dict.fromkeys(x for x in possible if is_solana_address(x)))[:5]


def parse_time(value: Any, default: float | None = None) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)/1000 if value > 1e11 else float(value)
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        except ValueError:
            pass
    return time.time() if default is None else default


def normalize_post(data: dict, backlog=False) -> dict | None:
    if not isinstance(data, dict):
        return None
    post_id = str(data.get('id') or '')
    author = data.get('author') or {}
    handle = str(author.get('handle') or '').lstrip('@')
    if not re.fullmatch(r'[A-Za-z0-9_]{1,25}', handle) or not re.fullmatch(r'\d{8,25}', post_id):
        return None  # never build arbitrary external URLs or accept social/webhook IDs
    now = time.time()
    created = parse_time(data.get('createdAt'), now)
    # No future-dated alerts or expired messages.
    if created > now + 90:
        created = now
    text = str(data.get('text') or '')[:MAX_BODY]
    if not text.strip() and not extract_mints(data):
        return None
    raw_followers = author.get('followersCount')
    followers = max(0, min(10_000_000_000, int(raw_followers))) if isinstance(raw_followers,(int,float)) and not isinstance(raw_followers,bool) else None
    tickers = list(dict.fromkeys(x.upper() for x in TICKER_RE.findall(text) if x.upper() not in STOP_TICKERS))[:8]
    is_repost = bool(data.get('isRetweet') or data.get('type') == 'RETWEET')
    is_reply = bool(data.get('isReply') or data.get('type') == 'REPLY')
    mints = extract_mints(data)
    # J7 author flags are provided by its upstream providers. Not independently audited.
    upstream_verified = author.get('verified') if isinstance(author.get('verified'),bool) else None
    upstream_badge = str(author.get('badge') or '')[:40] or None
    upstream_type = str(author.get('verifiedType') or '')[:40] or None
    parody = author.get('parody') if isinstance(author.get('parody'),bool) else None
    tier = ('important' if followers is not None and followers >= 100_000 else
            'suivi' if followers is not None and followers >= 50_000 else 'standard')
    return dict(id=post_id, created_at=created, received_at=now, author=handle,
                author_id=str(author.get('id') or ''), followers=followers,
                j7_verified=upstream_verified,j7_badge=upstream_badge,
                j7_verified_type=upstream_type,j7_parody=parody,
                text=text, url=f'https://x.com/{handle}/status/{post_id}',
                mints=mints, tickers=tickers, tier=tier,
                is_repost=is_repost, is_reply=is_reply, is_backlog=bool(backlog), deleted=False)


class J7Feed:
    def __init__(self, store, on_new_mint=None, token=None, host='https://nyc.j7tracker.io', verifier=None):
        self.store = store
        self.on_new_mint = on_new_mint
        self.verifier = verifier
        self.token = token if token is not None else os.getenv('J7_FEED_TOKEN','').strip()
        self.host = host
        self.stop_event = threading.Event()
        self._lock = threading.RLock()
        self._socket = None
        self._pending_meta = {}  # parent tweet id -> (mints, expiry), metadata may precede tweet
        self.status = {'state':'inactive' if not self.token else 'starting',
                       'enabled':bool(self.token),'connected':False,
                       'last_event':None,'received':0,'new_mints':0,'upstream_connected':None,'error':None}

    def report(self):
        with self._lock:
            return dict(self.status)

    def _state(self, **changes):
        with self._lock:
            self.status.update(changes)

    def ingest(self, payload: dict, *, backlog=False) -> dict | None:
        # J7 can send very sparse tweet_update events. Reuse identity and
        # original flags from the existing post, without fabricating them.
        if isinstance(payload,dict) and re.fullmatch(r'\d{8,25}',str(payload.get('id') or '')):
            old=self.store.get_social_post(str(payload['id']))
            if old:
                if not isinstance(payload.get('author'),dict) or not payload['author'].get('handle'):
                    payload={**payload,'author':{'handle':old['author'],'id':old.get('author_id'),
                                       'followersCount':old.get('followers'),
                                       'verified':old.get('j7_verified'),
                                       'badge':old.get('j7_badge'),
                                       'verifiedType':old.get('j7_verified_type'),
                                       'parody':old.get('j7_parody')}}
                if not payload.get('createdAt'):
                    payload={**payload,'createdAt':old['created_at']}
                if 'isRetweet' not in payload:
                    payload={**payload,'isRetweet':old.get('is_repost',False)}
                if 'isReply' not in payload:
                    payload={**payload,'isReply':old.get('is_reply',False)}
        # token_meta sometimes arrives before the first tweet; merge that CA
        # only with its exact parent ID once a real tweet is received.
        if isinstance(payload,dict):
            parent_id=str(payload.get('id') or '')
            with self._lock:
                now=time.time()
                self._pending_meta={k:v for k,v in self._pending_meta.items() if v[1]>now}
                pending=self._pending_meta.pop(parent_id,None)
            if pending:
                payload={**payload,'extraContractAddresses':list(payload.get('extraContractAddresses') or [])+pending[0]}
        post = normalize_post(payload, backlog=backlog)
        if post is None:
            return None
        is_new, new_mints = self.store.save_social(post)
        if self.verifier and not backlog:
            self.verifier.submit(self.store.get_social_post(post['id']))
        if str(self.status.get('error') or '').startswith(('Événement ignoré','Mise à jour ignorée','Événement J7 ignoré')):
            self._state(error=None)
        self._state(last_event=time.time(),received=self.status['received'] + int(is_new),
                    new_mints=self.status['new_mints']+len(new_mints))
        if (not backlog and not self.store.social_is_backlog(post['id'])
                and not post['is_repost'] and not post['is_reply'] and time.time()-post['created_at']<=900):
            for mint in new_mints:self.store.enqueue(mint)
        # Re-evaluate merged author metadata: followers may arrive after the CA.
        saved = next((p for p in self.store.social_for_mint(post['mints'][0],200)
                      if p['id']==post['id']),post) if post['mints'] else post
        eligible=(not backlog and not self.store.social_is_backlog(post['id'])
                  and not saved['is_repost'] and not saved['is_reply']
                  and time.time()-saved['created_at']<=180
                  and saved.get('followers') is not None and saved['followers']>=50_000)
        if eligible:
            for mint in saved['mints']:
                if self.store.claim_notification(post['id'],mint):
                    self.store.enqueue(mint)
                    if self.on_new_mint:self.on_new_mint(mint)
        return post

    def ingest_event(self,kind,data):
        """Exact-address discovery only. A follow/profile edit is not endorsement."""
        if not isinstance(data,dict):return
        import hashlib
        event_id=str(data.get('id') or hashlib.sha256(
            (kind+str(data)).encode()).hexdigest())
        # Store bounded metadata, not session credentials or raw payloads.
        mints=[]
        if kind=='follow_scan':
            scan=(data.get('scan') or {}).get('contracts') or {}
            if scan.get('ok'):
                for row in scan.get('rows') or []:
                    if row.get('chain','').lower() in ('sol','solana') and not row.get('isDeleted'):
                        ca=row.get('ca')
                        if is_solana_address(ca):mints.append(ca)
        elif kind=='token_meta':
            meta=data.get('tokenMeta') or {}
            ca=data.get('mint') or meta.get('mint')
            if meta.get('chain','solana').lower() in ('sol','solana') and is_solana_address(ca):mints.append(ca)
        elif kind=='profile_update':
            user=data.get('user') or {}
            before=data.get('before') or {}
            # Only newly added literal addresses, never guess from a project name.
            def addresses(obj):
                return set(extract_mints({'text':' '.join(str(obj.get(k) or '') for k in ('description','bio','url','website'))}))
            mints=list(addresses(user)-addresses(before))
        elif kind=='profile_pinned_update':
            for post in data.get('pinned') or []:
                if isinstance(post,dict):mints.extend(extract_mints(post))
        elif kind=='following_update':
            pass  # Kept as context; follow_scan can supply an exact contract later.
        else:return
        # One tweet can receive several token_meta events, with the same
        # parent id but different mints. Dedupe each mint independently.
        if kind=='token_meta':
            event_id+=':'+','.join(sorted(mints))
        if not self.store.record_event(kind+':'+event_id,kind,{'mints':mints[:5]}):return
        self._state(last_event=time.time())
        if kind=='token_meta' and mints:
            # Attach the enriched mint to a matching post, even if metadata
            # arrives after it. If metadata is first, buffer it briefly.
            parent=str(data.get('id') or '')
            if re.fullmatch(r'\d{8,25}',parent):
                for mint in list(dict.fromkeys(mints))[:5]:
                    linked=self.store.attach_social_mint(parent,mint)
                    if linked:
                        self._state(new_mints=self.report()['new_mints']+1)
                        if self.verifier:self.verifier.submit(self.store.get_social_post(parent))
                    elif linked is None:
                        with self._lock:
                            now=time.time()
                            self._pending_meta={k:v for k,v in self._pending_meta.items() if v[1]>now}
                            old=self._pending_meta.get(parent,([],0))[0]
                            self._pending_meta[parent]=(list(dict.fromkeys(old+[mint]))[:5],now+180)
                            if len(self._pending_meta)>150:
                                self._pending_meta.pop(next(iter(self._pending_meta)))
        for mint in list(dict.fromkeys(mints))[:5]:
            self.store.enqueue(mint,'j7_'+kind)
            if self.on_new_mint:self.on_new_mint(mint)

    def stop(self):
        self.stop_event.set()
        if self._socket is not None:
            try:self._socket.disconnect()
            except Exception:pass

    def run(self):
        if not self.token:
            self._state(state='inactive',error='J7_FEED_TOKEN non configuré')
            return
        try:
            import socketio
        except ImportError:
            self._state(state='missing_library',error='Installer python-socketio[client] (voir README)')
            return
        while not self.stop_event.is_set():
            client = socketio.Client(reconnection=True, reconnection_attempts=4,
                                     reconnection_delay=2, reconnection_delay_max=20, logger=False)
            self._socket = client
            @client.event
            def connect():
                self._state(state='connected',connected=True,error=None)
                client.emit('user_connected',self.token)
            @client.event
            def disconnect():
                self._state(state='disconnected',connected=False)
            for kind in ('token_meta','following_update','follow_scan','profile_update','profile_pinned_update'):
                def handler(data,event_kind=kind):
                    try:self.ingest_event(event_kind,data)
                    except Exception as exc:self._state(error='Événement J7 ignoré : '+type(exc).__name__)
                client.on(kind,handler)
            @client.on('status')
            def upstream(item):
                if isinstance(item,dict) and isinstance(item.get('connected'),bool):
                    self._state(upstream_connected=item['connected'])
            @client.on('initialTweets')
            def initial(items):
                if isinstance(items,list):
                    for item in items[:100]:
                        try:self.ingest(item,backlog=True)
                        except Exception:pass
            @client.on('tweet')
            def tweet(item):
                try:self.ingest(item)
                except Exception as e:self._state(error='Événement ignoré : '+type(e).__name__+(' (base occupée)' if 'locked' in str(e).lower() else ''))
            @client.on('tweet_update')
            def update(item):
                try:self.ingest(item)
                except Exception as e:self._state(error='Mise à jour ignorée : '+type(e).__name__+(' (base occupée)' if 'locked' in str(e).lower() else ''))
            @client.on('external_message')
            def external(item):
                # Non-X feeds also exist in J7, but without a verified X
                # identity we keep them out of the influencer tweet feed.
                # These events must never be silently counted as X tweets.
                if isinstance(item,dict) and item.get('isWebhook'):
                    self._state(last_event=time.time())
            @client.on('tweet_deleted')
            def deleted(item):
                if isinstance(item,dict) and item.get('id'):
                    self.store.mark_social_deleted(str(item['id']))
            @client.on('auth_error')
            def auth_error(item):
                error = str(item.get('error') if isinstance(item,dict) else item)
                self._state(state='auth_error',connected=False,error=error[:150])
                client.disconnect()
            @client.event
            def connect_error(error):
                self._state(state='error',connected=False,error=str(error)[:150])
            try:
                self._state(state='connecting',connected=False)
                client.connect(self.host,transports=['websocket'],auth={'token':self.token},wait_timeout=12)
                client.wait()
            except Exception as exc:
                self._state(state='error',connected=False,error=(type(exc).__name__+': '+str(exc))[:160])
            finally:
                try:client.disconnect()
                except Exception:pass
            if self.stop_event.is_set(): break
            # Avoid repeatedly sending an expired token.
            if self.report()['state']=='auth_error' or 'Invalid token' in str(self.report()['error']):break
            self.stop_event.wait(30)
