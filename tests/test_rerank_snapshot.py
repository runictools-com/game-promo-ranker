import unittest
from rerank_snapshot import rerank


class RerankTests(unittest.TestCase):
    def test_preserves_collection_and_history(self):
        small = dict(appid='1', pct_positive=100, total_reviews=100, discount=90,
                     price_history=[{'date':'2026-09-12','price':10}], sale_price='R$10,00')
        popular = dict(appid='2', pct_positive=96, total_reviews=60000, discount=80)
        data = dict(generated_at='2026-09-12T23:00:00Z', blocks=[dict(games=[small,popular])])
        result = rerank(data)
        self.assertEqual(result['generated_at'], '2026-09-12T23:00:00Z')
        self.assertEqual(result['blocks'][0]['games'][0]['appid'], '2')
        self.assertEqual(small['price_history'], [{'date':'2026-09-12','price':10}])
        self.assertEqual(small['sale_price'], 'R$10,00')
        self.assertEqual(small['score_version'], 3)

    def test_empty_snapshot_refused(self):
        with self.assertRaises(ValueError):
            rerank({'blocks': []})
