"""J7 meme-phrase watchlist. Read-only hypotheses, NEVER token endorsements.

Extracts literal words/phrases from a post. Does not claim to reproduce J7's
proprietary yellow highlights: those are not present in the documented feed.
"""
from __future__ import annotations
import re, time
from .narratives import normal, in_text, gta_theme_match

PRIORITY = {'elonmusk','rockstargames','rockstarsupport','blknoiz06',
            'muststopmurad','cz_binance','theunipcs'}
# Common breaking-news words, crypto boilerplate and finance bait are poor token identifiers.
NOISE = {'LIVE','BREAKING','NEWS','WATCH','HERE','MORE','TODAY','TONIGHT',
         'THREAD','LATEST','JUST','NOW','NEW','OMG','LOL','WTF','THE','THIS',
         'WITH','FROM','ABOUT','THAT','TRUMP','MUSK','ELON','PUMP','BUY','SELL',
         'DOLLARS','MILLION','BILLION','CRYPTO','SOLANA','MEME','TOKEN','COIN',
         'OPEN','LINK','CLICK','WATCHING','ALERT','VIDEO','TWEET','RETWEET',
         'GOVERNMENT','EXCLUSIVE','BREAKINGNEWS','OFFICIAL','LIKE','SUBSCRIBE',
         'HTTPS','TWITTER','DO','NOT','GET','IN','ON','TO','FOR','AND','OF','YOU',
         'IS','ITS','ALL','OUR','WILL','THEY','YOUR','ARE','HAVE','WHEN','THEIR'}
KEY_ALIASES = {
    'GTA VI': ('gta 6','gta vi','gta6','gtavi','grand theft auto 6','grand theft auto vi'),
    'VICE CITY': ('vice city',),
    'LEONIDA': ('leonida',),
    'OPENAI': ('openai','open ai'),
    'DOOMSDAY': ('doomsday',),
}


def clean_phrase(word):
    word = ' '.join(str(word or '').strip().split())
    if len(word) > 45 or not (4 <= len(word)) or re.search(r'https?://|\bwww\.',word,re.I):
        return ''
    canonical = normal(word)
    if len(canonical) < 4 or len(canonical.split()) > 4:
        return ''
    pieces=canonical.split()
    if len(pieces)==1 and pieces[0].upper() in NOISE:
        return ''
    if len(pieces)==1 and len(pieces[0])<5:
        return ''
    if any(x.isdigit() and len(x)>5 for x in pieces):
        return ''
    for label, aliases in KEY_ALIASES.items():
        if canonical in [normal(a) for a in aliases]:
            return label
    return word.upper() if len(word.split())==1 else word.title()


def extract_phrases(text, *, author='', tickers=None):
    """Finite, explainable candidates. No unbounded n-grams or fuzzy coincidences.

    Return exact evidence kind: named_arc / ticker / hashtag / uppercase / quote.
    """
    raw=str(text or '')[:1200]
    # URLs and @handles are not token terms. Strip before extracting capitals.
    filtered=re.sub(r'https?://\S+|(?<!\w)@[A-Za-z0-9_]+',' ',raw)
    candidates=[]
    def add(term,kind):
        cleaned=clean_phrase(term)
        if cleaned and cleaned.casefold() not in {x['term'].casefold() for x in candidates}:
            candidates.append({'term':cleaned,'evidence':kind})
    for label, aliases in KEY_ALIASES.items():
        if any(in_text(normal(a),filtered) for a in aliases):add(label,'named_arc')
    for x in re.findall(r'(?<![\w])\$([A-Za-z][A-Za-z0-9]{2,18})(?!\w)',filtered):add(x,'ticker')
    for x in re.findall(r'(?<!\w)#([A-Za-z][A-Za-z0-9_]{3,23})',filtered):add(x,'hashtag')
    for x in re.findall(r'(?<!\w)\b[A-Z][A-Z0-9]{4,22}\b',filtered):add(x,'uppercase')
    # Capitalized distinctive nouns from a large account may inspire memes,
    # but remain low-confidence text candidates, not verified token symbols.
    for x in re.findall(r'(?<![A-Za-z0-9])[A-Z][a-z]{5,20}(?![A-Za-z0-9])',filtered):
        add(x,'proper_noun')
    for x in re.findall(r'[“\"]([^"”\n]{5,45})[”\"]',filtered):
        if 1 <= len(x.split()) <= 3 and not x.isnumeric():add(x,'quote')
    # Full names and common speech are NOT enough to invent a coin.
    return candidates[:10]


def topic_is_related(term, token_name, symbol=''):
    """Literal theme match to a name or ticker, NOT a mint identity match.

    Prevent tiny tickers colliding with ordinary text (e.g. AI, USA, GM).
    """
    phrase=normal(term)
    token=normal(token_name)
    ticker=normal(symbol)
    if not phrase or not token and not ticker:return False
    if term=='GTA VI':
        return any(in_text(x,token) for x in ('gta 6', 'grand theft auto 6')) or ticker in ('gta6','gtavi')
    # One strong token NAME or exact sufficiently specific ticker only.
    return bool((token and in_text(phrase,token)) or
                (len(phrase)>=5 and ticker and phrase==ticker))


def watch_evidence(name,symbol,events,now=None):
    now=time.time() if now is None else now
    out=[]; seen=set()
    for event in events:
        if not (now-7200 <= event.get('received_at',0) <= now+60):continue
        term=event.get('term','')
        if term in seen or not topic_is_related(term,name,symbol):continue
        seen.add(term)
        out.append({'term':term,'evidence':event.get('evidence'),
                    'source':event.get('platform'),'author':event.get('author'),
                    'received_at':event.get('received_at'),
                    'url':event.get('url'),
                    'note':'Hypothèse thématique uniquement : aucune affiliation ni hausse validée.'})
        if len(out)>=4:break
    return out
