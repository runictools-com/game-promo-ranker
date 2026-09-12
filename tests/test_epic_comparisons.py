import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import epic_deals as epic


class EpicComparisonTests(unittest.TestCase):
    def test_editions_are_not_interchangeable(self):
        self.assertNotEqual(epic._norm_title('Game Deluxe Edition'), epic._norm_title('Game'))
        self.assertNotEqual(epic._norm_title('Game Remastered'), epic._norm_title('Game'))
        self.assertEqual(epic._norm_title('GAME™: One'), epic._norm_title('Game One'))

    def test_non_brl_offers_are_rejected(self):
        offer = {'title': 'Game', 'price': {'totalPrice': {
            'discountPrice': 2000, 'originalPrice': 10000, 'currencyCode': 'USD'}}}
        self.assertEqual(epic.build_entries([offer]), [])
        offer['price']['totalPrice']['currencyCode'] = 'BRL'
        self.assertEqual(epic.build_entries([offer])[0]['sale_brl'], 20)

    def test_stale_unknown_currency_and_bundle_not_compared(self):
        now = datetime.now(timezone.utc)
        game = {'name': 'Game', 'sale_price': 'R$ 20,00', 'currency': 'BRL',
                'url': 'https://store.steampowered.com/app/1/'}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'games.json'
            def index(at, item):
                path.write_text(json.dumps({'generated_at': at.isoformat(),
                    'blocks': [{'games': [item]}]}), encoding='utf-8')
                return epic.load_steam_index(path)
            self.assertIn('game', index(now, game))
            self.assertEqual(index(now - timedelta(days=2), game), {})
            self.assertEqual(index(now, {**game, 'currency': 'USD'}), {})
            self.assertEqual(index(now, {**game, 'url': 'https://store.steampowered.com/sub/1/'}), {})


if __name__ == '__main__':
    unittest.main()
