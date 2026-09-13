from datetime import datetime, timezone
import tempfile
from pathlib import Path
import unittest

from steam_historical_import import import_low, run
from price_history_store import observe, read_history, write_history
from price_history_view import attach_low

NOW = datetime(2026, 9, 13, 3, tzinfo=timezone.utc)


def quote(cents=599, currency="BRL", shop=61):
    return dict(lowest=dict(shop=dict(id=shop), price=dict(amountInt=cents, currency=currency),
                           timestamp="2024-11-27T20:32:01Z"),
                urls=dict(history="https://isthereanydeal.com/game/slime-rancher/history/"))


class HistoricalImportTests(unittest.TestCase):
    def test_persistent_historical_low_and_new_steam_record(self):
        history = dict(schema_version=1, games={})
        observe(history, "433340", 1499, NOW.isoformat())
        self.assertTrue(import_low(history, "433340", quote(), NOW.isoformat()))
        self.assertEqual(history['games']['433340']['low_cents'], 599)
        self.assertEqual(len(history['games']['433340']['observation_dates']), 1)
        import_low(history, "433340", quote(999), NOW.isoformat())
        self.assertEqual(history['historical']['433340']['low_cents'], 599)
        observe(history, "433340", 499, NOW.isoformat())
        game = attach_low({}, "433340", history, NOW)
        self.assertEqual(game['price_low']['price_cents'], 499)
        self.assertTrue(game['price_low']['historical'])
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'history.json'
            write_history(p, history)
            self.assertEqual(read_history(p)['games']['433340']['low_cents'], 499)

    def test_different_shop_currency_unknown_and_zero(self):
        history = dict(schema_version=1, games={})
        for data in (quote(currency='USD'), quote(shop=6), {}, None, quote(cents=-1)):
            self.assertFalse(import_low(history, '1', data, NOW.isoformat()))
        self.assertTrue(import_low(history, '1', quote(cents=0), NOW.isoformat()))
        self.assertEqual(attach_low({}, '1', history, NOW)['price_low']['price_cents'], 0)

    def test_source_failure_preserves_committed_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'steam_price_history.json'
            history = dict(schema_version=1, games={})
            for i in range(1, 52):
                observe(history, str(i), 1000, NOW.isoformat())
            write_history(p, history)
            def fetch(batch):
                if '51' in batch:
                    raise ValueError('source unavailable')
                return {'prices': {'app/'+i: quote() for i in batch}}
            report = run(p, fetch=fetch, sleep=lambda _: None, now=NOW)
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(len(read_history(p)['historical']), 50)
            self.assertEqual(read_history(p)['games']['51']['low_cents'], 1000)
            report = run(p, fetch=lambda _: {'prices': []}, sleep=lambda _: None, now=NOW)
            self.assertEqual(report['status'], 'ok')
            self.assertEqual(report['cached_today'], 50)
            self.assertEqual(report['unavailable'], 1)


if __name__ == '__main__':
    unittest.main()
