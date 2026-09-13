"""Compare confirmed PC Game Pass membership with fresh Steam BR prices."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

VERIFIED_SUBSCRIPTION = dict(name='PC Game Pass', monthly_cents=5999, currency='BRL',
    source_url='https://www.xbox.com/pt-BR/games/store/game-pass/CFQ7TTC0KGQ8',
    checked_at='2026-09-13T02:10:00+00:00')


def fresh(value, now, hours):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp.tzinfo is not None and timedelta(0) <= now-stamp <= timedelta(hours=hours)
    except (ValueError, TypeError, AttributeError):
        return False


def enrich_gamepass(payload, comparison, now=None):
    now = now or datetime.now(timezone.utc)
    result = deepcopy(payload)
    subscription = deepcopy(comparison.get('subscription') or VERIFIED_SUBSCRIPTION)
    amount = subscription.get('monthly_cents')
    subscription['stale'] = not (type(amount) is int and amount > 0 and subscription.get('currency') == 'BRL'
                                  and fresh(subscription.get('checked_at'), now, 30*24))
    result['subscription'] = subscription
    active = set(comparison.get('active_ids') or [])
    membership_fresh = bool(active) and fresh(comparison.get('membership_checked_at'), now, 36)
    result['membership_checked_at'] = comparison.get('membership_checked_at')
    result['membership_stale'] = not membership_fresh
    result['metadata_stale'] = not fresh(payload.get('generated_at'), now, 36)
    result['comparison_coverage'] = comparison.get('coverage') or {}
    if membership_fresh:
        result['catalog'] = [g for g in result.get('catalog', []) if g.get('id') in active]
    if result['metadata_stale']:
        result['added'], result['removed'] = [], []
    priced = highlighted = 0
    for section in ('catalog', 'added', 'removed'):
        for game in result.get(section, []):
            price = (comparison.get('prices') or {}).get(game.get('id')) or {}
            cents = price.get('price_cents')
            valid_price = (type(cents) is int and cents >= 0 and price.get('currency') == 'BRL'
                           and fresh(price.get('checked_at'), now, 36)
                           and str(price.get('appid', '')).isdigit())
            game['steam'] = deepcopy(price) if valid_price else None
            game['above_subscription'] = bool(valid_price and membership_fresh and section != 'removed'
                and game.get('id') in active and not subscription['stale'] and cents > amount)
            game['difference_cents'] = cents-amount if game['above_subscription'] else None
            if section == 'catalog':
                priced += int(valid_price)
                highlighted += int(game['above_subscription'])
    result['total'] = len(result.get('catalog', []))
    result['priced_count'], result['highlighted_count'] = priced, highlighted
    result['unresolved_membership_count'] = len(active - {g.get('id') for g in result.get('catalog', [])}) if membership_fresh else None
    return result
