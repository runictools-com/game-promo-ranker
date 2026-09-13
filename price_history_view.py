"""Read-only presentation of the persisted Steam BR minimum."""
from datetime import datetime, timezone, timedelta


def attach_low(game, appid, history, now=None):
    now = now or datetime.now(timezone.utc)
    records = history.get('games', {}) if isinstance(history, dict) else {}
    record = records.get(str(appid), {}) if isinstance(records, dict) else {}
    record = record if isinstance(record, dict) else {}
    external = history.get('historical', {}).get(str(appid), {}) if isinstance(history, dict) else {}
    historical = (isinstance(external, dict) and type(external.get('low_cents')) is int
                  and external['low_cents'] >= 0 and external.get('currency') == 'BRL'
                  and external.get('country') == 'BR' and external.get('shop_id') == 61)
    if historical:
        record = dict(record)
        if type(record.get('low_cents')) is not int or external['low_cents'] <= record['low_cents']:
            record.update(low_cents=external['low_cents'], low_at=external['low_at'], currency='BRL', country='BR')
    cents = record.get('low_cents')
    game['price_low'] = None
    if type(cents) is not int or cents < 0 or record.get('currency') != 'BRL' or record.get('country') != 'BR':
        return game
    def recent(value):
        try:
            stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return stamp.tzinfo is not None and timedelta(0) <= now-stamp <= timedelta(hours=36)
        except (AttributeError, TypeError, ValueError):
            return False
    game['price_low'] = dict(price_cents=cents, currency='BRL', store='Steam Brasil',
        historical=historical, source_url=external.get('source_url') if historical else None,
        source=external.get('source') if historical else 'GamePromo',
        history_checked_at=external.get('checked_at') if historical else None,
        first_seen=record.get('first_seen'), low_at=record.get('low_at'),
        last_checked=record.get('last_checked'), observation_days=len(record.get('observation_dates') or []),
        at_low=recent(record.get('last_checked')) and record.get('last_price_cents') == cents,
        new_low=recent(record.get('new_low_at')) and recent(record.get('last_checked')) and record.get('last_price_cents') == cents)
    return game
