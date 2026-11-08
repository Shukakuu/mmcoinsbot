"""Read-only thematic context, never a token endorsement or market forecast.

Google Trends is broad context (not X). J7 posts without an exact mint can only
match a token *theme*, never prove a post promotes that particular token.
"""
from __future__ import annotations

from email.utils import parsedate_to_datetime
import re
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET

# Sources publiques. RockstarINTEL est un site d'actualité tiers, PAS Rockstar.
RSS_SOURCES = (
    ('FR', 'https://trends.google.com/trending/rss?geo=FR'),
    ('US', 'https://trends.google.com/trending/rss?geo=US'),
    ('GTA', 'https://rockstarintel.com/feed/'),
)

# Mots-clés explicites du thème GTA VI. On privilégie les lieux/titres distinctifs.
# Jason, Lucia et les autres prénoms ne constituent PAS seuls une correspondance.
GTA_ALIASES = ('gta 6', 'gta vi', 'grand theft auto vi', 'grand theft auto 6',
               'vice city', 'leonida', 'rockstar games', 'rockstar')
GTA_SHORT = ('gta6', 'gtavi')
GTA_TITLE_ALIASES = ('gta 6', 'grand theft auto 6', 'vice city', 'leonida')

STOP = {'coin','coins','token','tokens','meme','memecoin','crypto','sol','solana',
        'pump','fun','new','official','the','and','cat','dog','ai','bot','cash',
        'bitcoin','ethereum','usd','trump','elon','musk'}


def normal(text):
    text = unicodedata.normalize('NFKD', str(text or ''))
    text = ''.join(c for c in text if not unicodedata.combining(c)).lower()
    # GTA VI / GTA 6 are the same *topic*, NOT the same Solana contract.
    text = re.sub(r'\bgrand theft auto\s*(?:vi|6)\b', 'gta 6', text)
    text = re.sub(r'\bgta\s*(?:vi|6)\b', 'gta 6', text)
    text = re.sub(r'\bgta6\b', 'gta 6', text)
    text = re.sub(r'\bgtavi\b', 'gta 6', text)
    return ' '.join(re.findall(r'[a-z0-9]+', text))


def topic_name(name):
    parts = normal(name).split()
    while parts and parts[-1] in {'coin','token','meme','memecoin','official'}:
        parts.pop()
    while parts and parts[0] in {'the','official'}:
        parts.pop(0)
    phrase = ' '.join(parts)
    if len(phrase) < 5 or (len(parts) == 1 and parts[0] in STOP):
        return ''
    # Generic single-word names should not be linked to every casual mention.
    if len(parts) == 1 and len(parts[0]) < 6:
        return ''
    return phrase[:75]


def in_text(phrase, text):
    if not phrase:
        return False
    # Avoid raw substring aliases such as AI in RAIN, and only whole phrases.
    return bool(re.search(r'(?<![a-z0-9])'+re.escape(phrase)+r'(?![a-z0-9])',normal(text)))


def parse_trends_rss(raw, geo, now=None):
    now = time.time() if now is None else now
    if len(raw) > 300_000:
        raise ValueError('RSS Google Trends trop volumineux')
    root = ET.fromstring(raw)
    out = []
    for item in root.findall('.//item')[:100]:
        title = (item.findtext('title') or '').strip()[:150]
        if not title:
            continue
        stamp = now
        published = item.findtext('pubDate')
        if published:
            try:
                stamp = parsedate_to_datetime(published).timestamp()
            except (TypeError, ValueError, OverflowError):
                continue
        if now-86400 <= stamp <= now+300:
            out.append({'title':title,'geo':geo,'published_at':stamp,'received_at':now,
                        'source':'rockstarintel_rss' if geo=='GTA' else 'google_trends_rss'})
    return out



def gta_theme_match(token_name, story, author=''):
    """Conservative story-to-token relation, NEVER a contract endorsement.

    Rockstar's official account may trigger analysis but is never treated as
    proof a similarly named memecoin is official. Isolated first names, GTA
    Online and generic words do not create a match.
    """
    token=normal(token_name)
    news=normal(story)
    if not token or not news:
        return False
    token_is_arc=any(in_text(a,token) for a in GTA_TITLE_ALIASES)
    story_is_arc=any(in_text(a,news) for a in GTA_TITLE_ALIASES)
    # 'rockstar' alone does not mean a GTA VI news item.
    if token_is_arc and story_is_arc:
        return True
    # Strong source: Rockstar explicitly mentions GTA VI; character/project
    # names then become contextual search keys, not verified CA references.
    if str(author).lower().lstrip('@') == 'rockstargames' and story_is_arc:
        return token_is_arc or any(in_text(n,token) for n in ('lucia', 'jason', 'dacity'))
    return False


def theme_matches(token_name, story, author=''):
    """List of possible narratives; permits future arcs without altering price gates."""
    return ['GTA VI'] if gta_theme_match(token_name,story,author) else []

def contextual_matches(name, posts, trends, now=None):
    """Return context only. A thematic match never identifies an endorsed mint."""
    now = time.time() if now is None else now
    phrase = topic_name(name)
    if not phrase and not gta_theme_match(name,'GTA VI', 'RockstarGames'):
        return []
    matches = []
    for post in posts:
        if post.get('deleted') or post.get('is_backlog') or post.get('is_repost') or post.get('is_reply'):
            continue
        created = post.get('created_at') or 0
        if now-created > 1200 or created > now+90:
            continue
        if (in_text(phrase,post.get('text')) or
                gta_theme_match(name,post.get('text'),post.get('author'))):
            matches.append({'source':'j7_thematic','label':('@'+str(post.get('author') or '?'))[:40],
                            'headline':str(post.get('text') or '')[:170],
                            'ts':created,'direct_contract':False,
                            'note':'Mention thématique, sans preuve de lien avec ce mint.',
                            'arcs':theme_matches(name,post.get('text'),post.get('author'))})
    for trend in trends:
        published = trend.get('published_at') or 0
        if now-published > 21600 or published > now+300:
            continue
        if (in_text(phrase,trend.get('title')) or
                gta_theme_match(name,trend.get('title'))):
            matches.append({'source':'rockstarintel_rss' if trend.get('geo')=='GTA' else 'google_trends_rss','label':('RockstarINTEL (tiers)' if trend.get('geo')=='GTA' else 'Google Trends '+str(trend.get('geo') or '')),
                            'headline':str(trend.get('title') or '')[:170],
                            'ts':published,'direct_contract':False,
                            'note':'Correspondance de sujet, non confirmation du contrat.',
                            'arcs':theme_matches(name,trend.get('title'))})
    # Favor recent posts, limit noisy duplications of the same story/source.
    matches.sort(key=lambda x:x['ts'],reverse=True)
    return matches[:5]


class TrendsMonitor:
    """Periodic, bounded, independent RSS fetch. Never blocks the scanner worker."""
    def __init__(self,store,stop_event,fetch=None):
        self.store=store
        self.stop_event=stop_event
        self.fetch=fetch or self._fetch
        self.status={'enabled':True,'last_success':None,'error':None,'items':0}

    @staticmethod
    def _fetch(url):
        req=urllib.request.Request(url,headers={'User-Agent':'MemeRadar/7.0 (read-only news headlines)'})
        with urllib.request.urlopen(req,timeout=6) as response:
            return response.read(300_001)

    def update(self):
        items=[]; errors=[]
        now=time.time()
        for geo,url in RSS_SOURCES:
            if self.stop_event.is_set():break
            try:
                new_items=parse_trends_rss(self.fetch(url),geo,now)
                if geo=='GTA':
                    new_items=[x for x in new_items if any(in_text(a,x['title']) for a in GTA_TITLE_ALIASES)]
                items.extend(new_items)
            except Exception as exc:
                errors.append(f'{geo}: {type(exc).__name__}')
        if items:
            self.store.save_trends(items)
            # Check already-known tokens when a NEW topic appears, not only
            # tokens created after a trend. This is a research trigger, not a CA endorsement.
            for trend in items[:60]:
                for mint in self.store.find_theme_mints(trend['title'],limit=4):
                    import hashlib
                    stamp=hashlib.sha256((trend['geo']+trend['title']).encode()).hexdigest()[:16]
                    if self.store.record_event('theme_trend:'+stamp+':'+mint,'theme_trend',
                                               {'mint':mint,'geo':trend['geo'],'exact_contract':False}):
                        self.store.enqueue(mint,'trend_thematic')
            self.status.update(last_success=now,items=len(items),error='; '.join(errors) or None)
        else:
            self.status['error']='; '.join(errors) or 'RSS sans sujets récents'
        return len(items)

    def run(self):
        # Small delay so opening the app is never held up by an RSS provider.
        if self.stop_event.wait(3):return
        while not self.stop_event.is_set():
            self.update()
            self.stop_event.wait(600)
