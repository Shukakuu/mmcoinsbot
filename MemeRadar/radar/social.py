"""Read-only J7Tracker feed integration using its documented Socket.IO v4 feed.

Does not scrape pages, automate accounts, trade, or authenticate without the user's
own J7_FEED_TOKEN. A large-account mention is NOT a forecast of a price increase.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import re
import threading
import time
from typing import Any
from .j7_accounts import fetch_coverage, PRIORITY_HANDLES
from .narrative_intelligence import extract_phrases, PRIORITY
from .j7_hub import extract_flags, token_meta_info, shape_of

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
    # Some reposts have an empty outer text: use explicitly labeled original
    # source text rather than silently attributing it to the reposter.
    original_text=str(data.get('originalTweetText') or '')[:MAX_BODY]
    if not text and data.get('isRetweet') and original_text:
        text=original_text
    if not text.strip() and not extract_mints(data):
        return None
    raw_followers = author.get('followersCount')
    followers = max(0, min(10_000_000_000, int(raw_followers))) if isinstance(raw_followers,(int,float)) and not isinstance(raw_followers,bool) and math.isfinite(raw_followers) else None
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
                mints=mints, tickers=tickers, themes=extract_phrases(text,author=handle)[:8], tier=tier,
                is_repost=is_repost, is_reply=is_reply, is_backlog=bool(backlog), deleted=False,
                original_author=str((data.get('originalAuthor') or {}).get('handle') or '')[:40] if isinstance(data.get('originalAuthor'),dict) else '')


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
        self._shapes_seen = set()
        self.status = {'state':'inactive' if not self.token else 'starting',
                       'enabled':bool(self.token),'connected':False,
                       'last_event':None,'received':0,'new_mints':0,'upstream_connected':None,'error':None,
                       'account_coverage':{'state':'pending' if self.token else 'no_token'}}
        self._last_accounts_audit=0

    def report(self):
        with self._lock:
            return dict(self.status)

    def _state(self, **changes):
        with self._lock:
            self.status.update(changes)

    def _shape(self, kind, obj):
        """Remember which JSON keys J7 really sends (never values). Once per distinct shape."""
        try:
            key = (kind, tuple(shape_of(obj)))
            if key[1] and key not in self._shapes_seen and len(self._shapes_seen) < 600:
                self._shapes_seen.add(key)
                self.store.record_shape(kind, obj)
        except Exception:
            pass

    def _highlight(self, mint, via, *, post=None, platform='', name='', symbol='', flags=None):
        """Ledger entry: J7 linked this mint to a post/card. Observation only, never an approval."""
        post = post if isinstance(post, dict) else {}
        try:
            return self.store.record_highlight(
                mint, via, post_id=str(post.get('id') or ''), platform=platform or post.get('platform') or 'X',
                author=str(post.get('author') or ''), followers=post.get('followers'),
                post_at=post.get('created_at'), name=name, symbol=symbol, flags=flags)
        except Exception:
            return None

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
        self._shape('tweet', payload)
        live_post = (not backlog and not self.store.social_is_backlog(post['id'])
                     and time.time()-post['created_at'] <= 900)
        if live_post:
            self.store.enrich_highlights(post['id'], author=post['author'], followers=post.get('followers'),
                                         post_at=post['created_at'], platform='X')
            if not post['is_reply']:
                flags = dict(extract_flags(payload), is_repost=post['is_repost'])
                for mint in post['mints']:
                    self._highlight(mint, 'post_ca', post=post, flags=flags)
        if self.verifier and not backlog:
            self.verifier.submit(self.store.get_social_post(post['id']))
        if str(self.status.get('error') or '').startswith(('Événement ignoré','Mise à jour ignorée','Événement J7 ignoré')):
            self._state(error=None)
        self._state(last_event=time.time(),received=self.status['received'] + int(is_new),
                    new_mints=self.status['new_mints']+len(new_mints))
        if (not backlog and not self.store.social_is_backlog(post['id'])
                and not post['is_repost'] and not post['is_reply'] and time.time()-post['created_at']<=900):
            for mint in new_mints:self.store.enqueue(mint)
        # Literal meme-phrase watch. Reposts are context, NOT endorsements by
        # the reposting account; allow them because J7 UI highlights reposts.
        fresh=(not backlog and not self.store.social_is_backlog(post['id'])
               and time.time()-post['created_at']<=300 and not post['is_reply'])
        influential=(post['author'].lower() in PRIORITY or
                     (post.get('followers') or 0)>=100_000)
        phrases=extract_phrases(post['text'],author=post['author']) if fresh else []
        if fresh and (influential or any(p['evidence'] in ('ticker','named_arc') for p in phrases)):
            stored=self.store.record_narrative(post['id'],phrases,
                author=('repost:'+post['author'] if post['is_repost'] else post['author']),
                platform='J7/X',published_at=post['created_at'],
                received_at=time.time(),url=post['url'],excerpt=post['text'])
            if stored:
                for mint in dict.fromkeys(self.store.find_phrase_candidates(post['text'],limit=12)+self.store.find_theme_mints(post['text'],limit=6,author=post['author'])):
                    self.store.enqueue(mint,'j7_thematic')
                    if self.on_new_mint:self.on_new_mint(mint)
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
        self._shape(kind,data)
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
        if mints:
            # J7 panel highlight (token_meta) and other exact-contract events go into the
            # ledger: author, latency and later outcomes make each J7 source measurable.
            parent=str(data.get('id') or '') if kind=='token_meta' else ''
            post=self.store.get_social_post(parent) if re.fullmatch(r'\d{8,25}',parent) else None
            if not (post and (post.get('is_backlog') or self.store.social_is_backlog(parent))):
                info=token_meta_info(data) if kind=='token_meta' else {'name':'','symbol':''}
                owner=data.get('user') if isinstance(data.get('user'),dict) else {}
                fallback={'id':parent,'author':str(owner.get('handle') or owner.get('username') or owner.get('screenName') or '')}
                for mint in dict.fromkeys(mints):
                    self._highlight(mint,kind,post=post or fallback,name=info['name'],symbol=info['symbol'],
                                    flags=extract_flags(data))
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

    def record_external_shape(self, item):
        """Passive metadata-only J7 telemetry. NO trade, NO CA inference.

        Webhook formats are unverified: save shapes instead of assigning
        contract names from text or claiming `pumppairs` support.
        """
        if not isinstance(item,dict):return False
        import hashlib
        import json
        webhook=item.get('webhook') if isinstance(item.get('webhook'),dict) else {}
        embeds=webhook.get('embeds') if isinstance(webhook.get('embeds'),list) else []
        shape={
            'event_keys':sorted(str(k)[:35] for k in item)[:25],
            'is_webhook':bool(item.get('isWebhook')),
            'webhook_keys':sorted(str(k)[:35] for k in webhook)[:25],
            'embeds':min(50,len(embeds)),
            'embed_keys':[sorted(str(k)[:35] for k in e)[:15] for e in embeds[:3] if isinstance(e,dict)],
        }
        # Distinct events get distinct hashes without retaining raw payloads.
        digest=hashlib.sha256(json.dumps(item,sort_keys=True,default=str).encode()).hexdigest()[:24]
        saved=self.store.record_event('external_shape:'+digest,'external_shape',shape)
        self._state(last_event=time.time())
        return saved

    def ingest_external(self,item,*,backlog=False):
        """Official J7 external_message schema: public socials + webhook cards.

        Identifies literal tokens only; social mentions and news never validate a
        specific mint. Webhook address fields are explicit, but not safety proof.
        """
        if not isinstance(item,dict):return None
        if str(item.get('type') or '') in ('TIKTOK_VIDEO_UPDATE','YOUTUBE_IMAGE_UPDATE','YOUTUBE_DELETION'):
            return None
        self.record_external_shape(item)
        self._shape('external:'+str(item.get('platform') or '?')[:20],item)
        author=item.get('author') if isinstance(item.get('author'),dict) else {}
        source=str(item.get('platform') or 'J7 webhook' if item.get('isWebhook') else item.get('platform') or 'J7/social')[:35]
        text=str(item.get('text') or item.get('youtubeTitle') or '')[:1200]
        handle=str(author.get('handle') or author.get('name') or '')[:40]
        created=parse_time(item.get('createdAt'),time.time())
        fresh=not backlog and created<=time.time()+90 and time.time()-created<=300
        from .narrative_intelligence import extract_phrases
        if fresh and text:
            phrases=extract_phrases(text,author=handle)
            # J7 non-X is a shared feed. Only memes with explicit markers or
            # distinctive named arcs trigger investigations, not ordinary news.
            phrases=[p for p in phrases if p['evidence'] in ('named_arc','ticker','hashtag','uppercase')]
            if phrases:
                key='external:'+str(item.get('id') or __import__('hashlib').sha256(text.encode()).hexdigest()[:24])
                added=self.store.record_narrative(key,phrases,author=handle,platform=source,
                    published_at=created,received_at=time.time(),excerpt=text,
                    url=str(item.get('tiktokUrl') or item.get('youtubeUrl') or item.get('instagramUrl') or '')[:300])
                if added:
                    for mint in self.store.find_phrase_candidates(text,limit=8):
                        self.store.enqueue(mint,'j7_external_theme')
                        if self.on_new_mint:self.on_new_mint(mint)
        if fresh and not item.get('isWebhook'):
            # Exact contracts written in Truth Social / Instagram / TikTok / Binance Square / ...
            # posts were ignored before v7.2. Same strict extractor as for X; a mention is not an approval.
            owner_followers=author.get('followersCount')
            for mint in extract_mints(item):
                self._highlight(mint,'external_ca',platform=source,post={'id':str(item.get('id') or ''),'author':handle,
                    'followers':owner_followers,'created_at':created},flags=extract_flags(item))
                self.store.enqueue(mint,'j7_external_ca')
                if self.on_new_mint:self.on_new_mint(mint)
        if item.get('isWebhook') and not backlog:
            webhook=item.get('webhook') if isinstance(item.get('webhook'),dict) else {}
            # Only documented launch cards; NOT arbitrary 3rd-party embeds.
            if webhook.get('handle') in ('pumppairs','ponspairs','stonkpairs'):
                mints=[]
                for embed in (webhook.get('embeds') or [])[:10]:
                    if isinstance(embed,dict) and is_solana_address(embed.get('address')):
                        mints.append(embed['address'])
                for mint in dict.fromkeys(mints):
                    self._highlight(mint,'launch_card:'+webhook['handle'],platform=webhook['handle'],
                                    post={'id':str(item.get('id') or ''),'author':webhook['handle'],'created_at':created})
                    if self.store.launch_event(mint,'creation',source='j7_'+webhook['handle']):
                        self.store.enqueue(mint,'j7_launch')
                        if self.on_new_mint:self.on_new_mint(mint)
        return True

    def stop(self):
        self.stop_event.set()
        if self._socket is not None:
            try:self._socket.disconnect()
            except Exception:pass

    def _check_accounts(self):
        try:
            coverage=fetch_coverage(self.token)
            self._state(account_coverage={'state':'ok', **coverage})
        except Exception as exc:
            # Do not copy exception messages: HTTP errors may echo request URLs.
            self._state(account_coverage={'state':'error','error_type':type(exc).__name__})

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
                if time.monotonic()-self._last_accounts_audit>900:
                    self._last_accounts_audit=time.monotonic()
                    threading.Thread(target=self._check_accounts,daemon=True,name='j7-accounts-audit').start()
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
                        try:
                            if item.get('source')=='external' or item.get('isWebhook'):
                                self.ingest_external(item,backlog=True)
                            else:self.ingest(item,backlog=True)
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
                if isinstance(item,dict):
                    try:self.ingest_external(item)
                    except Exception as exc:
                        self._state(error='Métadonnées webhook J7: '+type(exc).__name__)
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
