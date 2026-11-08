"""Dynamic lexical topic graph, deliberately not presented as semantic AI."""
import re
from .narrative_intelligence import extract_phrases, clean_phrase
from .narratives import normal


def discover_terms(text):
    terms = extract_phrases(text)
    # Mixed-case names (SpaceX, DeepMind, etc.) need not be preconfigured.
    for word in re.findall(r'\b[A-Z][a-z]+(?:[A-Z][A-Za-z]*)+\b', str(text)[:1200]):
        term = clean_phrase(word)
        if term and term not in {x['term'] for x in terms}:
            terms.append({'term': term, 'evidence': 'mixed_case_entity'})
    return terms[:15]


def topic_graph(events):
    groups = {}
    for event in events:
        for term in event['terms']:
            key = normal(term['term'])
            group = groups.setdefault(key, {'term': term['term'], 'events': [], 'sources': set(), 'related': {}})
            group['events'].append(event['id'])
            group['sources'].add(event['source'])
            for other in event['terms']:
                if normal(other['term']) != key:
                    group['related'][other['term']] = group['related'].get(other['term'], 0)+1
    out = []
    for group in groups.values():
        if len(group['events']) < 2:
            continue
        group['sources'] = sorted(group['sources'])
        group['related'] = sorted(group['related'], key=group['related'].get, reverse=True)[:5]
        group['event_count'] = len(set(group['events']))
        group['events'] = group['events'][:12]
        out.append(group)
    return sorted(out, key=lambda x: x['event_count'], reverse=True)[:20]
