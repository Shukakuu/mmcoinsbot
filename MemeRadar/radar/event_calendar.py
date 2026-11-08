"""Future dates explicitly reported in headlines; never official verification."""
from datetime import datetime, timezone
import re


def date_hints(title, now):
    if not re.search(r'launch|release|scheduled|premiere|conference|sortie|lancement|prévu|prévue|conférence', title, re.I):
        return []
    today = datetime.fromtimestamp(now, timezone.utc).date()
    dates = []
    for value in re.findall(r'\b20\d{2}-\d{2}-\d{2}\b', title):
        try:
            day = datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            continue
        if 0 <= (day-today).days <= 366 and value not in dates:
            dates.append(value)
    return dates


def upcoming(events, now):
    result = []
    for event in events:
        for date in date_hints(event['title'], now):
            result.append({'date': date, 'title': event['title'], 'url': event['url'],
                           'source': event['source'], 'event_id': event['id'],
                           'verified': False, 'note': 'Date annoncée dans le titre, à confirmer auprès de l’organisateur.'})
    return sorted(result, key=lambda x: x['date'])[:30]
