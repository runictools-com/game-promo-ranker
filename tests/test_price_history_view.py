from datetime import datetime, timezone
import unittest
from price_history_view import attach_low


class HistoryViewTests(unittest.TestCase):
    def test_first_record_shows_minimum_without_claiming_new_record(self):
        record=dict(low_cents=1000,currency='BRL',country='BR',first_seen='2026-09-13T02:00:00Z',
                    low_at='2026-09-13T02:00:00Z',last_checked='2026-09-13T02:00:00Z',last_price_cents=1000,
                    observation_dates=['2026-09-12'],new_low_at=None)
        game=attach_low({},'42',{'games':{'42':record}},datetime(2026,9,13,3,tzinfo=timezone.utc))
        self.assertEqual(game['price_low']['price_cents'],1000)
        self.assertFalse(game['price_low']['new_low'])
        self.assertEqual(game['price_low']['observation_days'],1)

    def test_old_minimum_survives_stale_current_price(self):
        record=dict(low_cents=0,currency='BRL',country='BR',first_seen='2026-01-01T00:00:00Z',
                    last_checked='2026-01-01T00:00:00Z',last_price_cents=0,new_low_at='2026-01-01T00:00:00Z')
        game=attach_low({},'42',{'games':{'42':record}},datetime(2026,9,13,3,tzinfo=timezone.utc))
        self.assertEqual(game['price_low']['price_cents'],0)
        self.assertFalse(game['price_low']['at_low'])
        self.assertFalse(game['price_low']['new_low'])

    def test_no_foreign_or_missing_minimum(self):
        self.assertIsNone(attach_low({},'42',{'games':{'42':{'low_cents':100,'currency':'USD','country':'US'}}})['price_low'])
