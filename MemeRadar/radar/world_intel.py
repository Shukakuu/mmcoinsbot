"""Public world-intelligence service and token evidence API.

Uses the existing V2 SQLite layout instead of replacing it with incompatible
CREATE TABLE declarations from the conversation's two alternative prototypes.
"""
import time
from .world_watch import WorldMonitor, parse_feed, parse_date, social_events, link_events, emerging
from .event_calendar import date_hints, upcoming


def date_hint(title, now):
    dates = date_hints(title, now)
    return dates[0] if dates else None


future_date = date_hint


def events_for_store(store, now):
    return store.world_events(now) + social_events(store.recent_social(500), now)


def context_for_token(store, mint, name, symbol='', now=None):
    now = time.time() if now is None else now
    return link_events({'mint':mint, 'name':name, 'symbol':symbol}, events_for_store(store, now))[:12]


class WorldIntel(WorldMonitor):
    def __init__(self, store, stop_event, sources=None, fetch=None, search=None):
        if isinstance(sources, dict):
            sources = tuple(sources.items())
        super().__init__(store, stop_event, fetch=fetch, search=search, sources=sources)

    def report(self, now=None):
        now = time.time() if now is None else now
        events = sorted(events_for_store(self.store, now), key=lambda e:e['published_at'], reverse=True)
        links = []
        for coin in self.store.list_coins():
            links.extend(dict(item, mint=coin['mint']) for item in link_events(coin, events))
        return {'status':dict(self.status), 'stories':events[:50], 'topics':emerging(events, now),
                'upcoming':upcoming(events, now), 'token_links':links[:100], 'manual_only':True,
                'note':'Associations de sujet, jamais une preuve d’affiliation ou de sécurité.'}
