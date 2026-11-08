"""Optional official X account verification for J7-addressed memecoin mentions.

Only the X API can provide the official verified flag here. It means the account
has a badge; it is *not* an identity, independent trader, or human-follower audit.
No bearer token: no network queries and no verified social-priority credit.
"""
import datetime as dt
import json
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


def assess_profile(data, author_id, handle, now=None):
    """Keep identity checks deterministic; audience warnings are heuristics, not bot counts."""
    now=time.time() if now is None else now
    user=data.get('data') if isinstance(data,dict) else None
    if not isinstance(user,dict) or str(user.get('id')) != str(author_id):
        raise ValueError('X user identity mismatch')
    if str(user.get('username') or '').casefold() != str(handle).casefold():
        raise ValueError('X handle mismatch')
    verified=user.get('verified')
    if not isinstance(verified,bool):
        raise ValueError('X did not return verified status')
    metrics=user.get('public_metrics') or {}
    followers=metrics.get('followers_count')
    following=metrics.get('following_count')
    tweet_count=metrics.get('tweet_count')
    created=user.get('created_at')
    age_days=None
    if isinstance(created,str):
        try:
            ts=dt.datetime.fromisoformat(created.replace('Z','+00:00')).timestamp()
            age_days=max(0,(now-ts)/86400)
        except ValueError:pass
    warnings=[]
    if isinstance(followers,int) and followers>=50_000 and age_days is not None and age_days<60:
        warnings.append('Compte récent avec de nombreux abonnés (à vérifier)')
    if isinstance(tweet_count,int) and age_days and age_days>=5 and tweet_count/age_days>300:
        warnings.append('Cadence historique de publications très élevée')
    if isinstance(followers,int) and isinstance(following,int) and followers>=50_000 and following>followers*8:
        warnings.append('Nombre d’abonnements élevé relativement aux abonnés')
    return {'verified':verified,'source':'x_official_api','followers':followers if isinstance(followers,int) else None,
            'handle':user['username'],'id':str(user['id']),'age_days':round(age_days,1) if age_days is not None else None,
            'warnings':warnings,'checked_at':now,
            'audience_audit':'not_available', 'note':'Un badge X et une audience affichée ne prouvent pas des abonnés humains.'}


def fetch_profile(author_id,handle,bearer,timeout=6):
    if not re.fullmatch(r'\d{4,25}',str(author_id)) or not re.fullmatch(r'[A-Za-z0-9_]{1,25}',handle):
        raise ValueError('X author id/handle invalid')
    url='https://api.x.com/2/users/'+urllib.parse.quote(str(author_id))+'?user.fields=created_at,public_metrics,verified'
    req=urllib.request.Request(url,headers={'Authorization':'Bearer '+bearer,'User-Agent':'MemeRadar/1.0'})
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        data=json.load(resp)
    return assess_profile(data,author_id,handle)


class XVerifier:
    """Bounded off-thread X lookups. No token: disabled. Caches profiles for 12 hours."""
    def __init__(self,store,on_verified=None,token=None,lookup=fetch_profile):
        self.store=store
        self.token=(os.getenv('X_BEARER_TOKEN','') if token is None else token).strip()
        self.on_verified=on_verified
        self.lookup=lookup
        self.jobs=queue.Queue(maxsize=100)
        self._queued=set()
        self._lock=threading.Lock()
        self.stop_event=threading.Event()
        self.last_query=0
        self.status={'enabled':bool(self.token),'checked':0,'verified':0,'errors':0,'pending':0}
    def submit(self,post):
        if not self.token or not isinstance(post,dict) or post.get('deleted') or post.get('is_backlog') or post.get('is_reply') or post.get('is_repost'):
            return False
        if not post.get('mints') or post.get('x_verified_source')=='x_official_api' or time.time()-post.get('created_at',0)>900 or (post.get('followers') or 0)<50_000 or post.get('j7_parody') is True or post.get('j7_verified') is not True:
            return False
        author_id=str(post.get('author_id') or '')
        handle=str(post.get('author') or '')
        if not re.fullmatch(r'\d{4,25}',author_id) or not re.fullmatch(r'[A-Za-z0-9_]{1,25}',handle):return False
        key=(author_id,post['id'])
        with self._lock:
            if key in self._queued:return False
            self._queued.add(key)
        try:self.jobs.put_nowait((key,handle,post['id']))
        except queue.Full:
            with self._lock:self._queued.discard(key)
            return False
        return True
    def run(self):
        while not self.stop_event.is_set():
            try:key,handle,post_id=self.jobs.get(timeout=.5)
            except queue.Empty:continue
            try:
                author_id=key[0]
                profile=self.store.cached_x_profile(author_id,ttl=43200)
                if profile is None:
                    # Strict cap: 1 X request / 15 seconds, even when J7 is busy.
                    delay=max(0,15-(time.monotonic()-self.last_query)) if self.last_query else 0
                    if delay and self.stop_event.wait(delay):continue
                    self.last_query=time.monotonic()
                    profile=self.lookup(author_id,handle,self.token)
                    self.store.cache_x_profile(author_id,profile)
                    self.status['checked']+=1
                # Recheck username because account can change handles while cached.
                if profile.get('handle','').casefold()!=handle.casefold():continue
                self.store.attach_x_profile(post_id,profile)
                if profile.get('verified') is True and not profile.get('warnings'):
                    self.status['verified']+=1
                    post=self.store.get_social_post(post_id) or {}
                    for mint in post.get('mints') or []:
                        if self.on_verified:self.on_verified(mint)
            except (OSError,ValueError,KeyError,urllib.error.URLError):
                self.status['errors']+=1
            finally:
                with self._lock:self._queued.discard(key)
                self.jobs.task_done()
    def stop(self):self.stop_event.set()
