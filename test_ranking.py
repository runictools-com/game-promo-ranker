import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bs4 import BeautifulSoup
import steam_sale_ranker as r


def row(tags="[]", descriptors="[]", href="https://store.steampowered.com/app/42/", reviews=500, price="R$ 10,00"):
    html = f'''<a class="search_result_row" href="{href}" data-ds-appid="42" data-ds-discount="50" data-ds-tagids='{tags}' data-ds-content-descriptors='{descriptors}'>
    <span class="title">Game</span><div class="discount_final_price">{price}</div>
    <span class="search_review_summary" data-tooltip-html="95% of {reviews} user reviews are positive."></span></a>'''
    return BeautifulSoup(html, "html.parser").a


class RankingTests(unittest.TestCase):
    def test_quality_and_confidence(self):
        self.assertEqual(r.calc_score(100, 10, 90), 0)
        self.assertGreater(r.calc_score(95, 500, 70), r.calc_score(75, 100000, 90))
        self.assertGreater(r.calc_score(95, 5000, 70), r.calc_score(95, 100, 70))
        self.assertLess(r.calc_score(95, 100000, 70)-r.calc_score(95, 10000, 70), .1)
        self.assertGreater(r.calc_score(95, 500, 80), r.calc_score(95, 500, 20))

    def test_filter_explicit_but_keep_mature_and_niche(self):
        self.assertIsNone(r._parse_row(row(tags="[9130]")))
        self.assertIsNone(r._parse_row(row(descriptors="[3]")))
        self.assertIsNotNone(r._parse_row(row(tags="[6650,12095]", descriptors="[1,2,5]", reviews=100)))
        self.assertIsNone(r._parse_row(row(reviews=99)))

    def test_no_bundle_prices_or_foreign_currency(self):
        self.assertIsNone(r._parse_row(row(href="https://store.steampowered.com/sub/42/")))
        self.assertIsNone(r._parse_row(row(price="$ 10.00")))
        self.assertEqual(r._parse_brl("R$ 1.299,99"), 1299.99)
        self.assertEqual(r._parse_brl("R$9.99"), 9.99)

    def test_empty_filtered_page_does_not_end_pagination(self):
        with patch.object(r, "fetch_page", side_effect=[([], 100), ([{"appid": "42"}], 100)]) as fetch, patch.object(r.time, "sleep"):
            games, _ = r._fetch_strategy("", 2, "test")
        self.assertEqual(len(games), 1)
        self.assertEqual(fetch.call_count, 2)

    def test_historical_low_never_inferred_from_usd(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/"lows.json")
            Path(path).write_text(json.dumps({"42": {"src": "cs", "low_brl": 1, "stores": [{"price_brl": 1}]}}))
            game = {"appid": "42", "sale_price": "R$ 10,00"}
            r.apply_low_cache([game], path)
            self.assertEqual(game["low_price_brl"], "R$ 10,00")
            self.assertFalse(game["historical_low"])
            self.assertFalse(game["observed_low"])
            self.assertEqual(game["stores"], [])
            game["sale_price"] = "R$ 8,00"
            r.apply_low_cache([game], path)
            self.assertTrue(game["observed_low"])
            self.assertFalse(game["historical_low"])

    def test_price_history_effect_neutral_until_two_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/"lows.json")
            game = {"appid": "42", "sale_price": "R$ 20,00", "pct_positive": 95,
                    "total_reviews": 1000, "discount": 50}
            r.apply_low_cache([game], path)
            self.assertIsNone(game["score_components"]["observed_price_proximity"])
            base = game["score"]
            ent = json.loads(Path(path).read_text())
            ent["42"]["observed_dates"] = ["2020-01-01"]
            ent["42"]["low_brl"] = 10
            Path(path).write_text(json.dumps(ent))
            r.apply_low_cache([game], path)
            self.assertEqual(game["score_components"]["observed_price_proximity"], .5)
            self.assertLess(game["score"], base)
            self.assertEqual(game["quality_score"], round(10*r.quality_lower_bound(95,1000),3))

    def test_failure_aborts_collection(self):
        with patch.object(r, "fetch_page", side_effect=r.requests.Timeout("timeout")):
            with self.assertRaises(RuntimeError):
                r._fetch_strategy("", 1, "test")

    def test_legacy_meta_cannot_pollute_real_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/"meta.json")
            Path(path).write_text(json.dumps({"42": {"genres": ["Old"], "tags": ["Fake"]}}))
            game = {"appid": "42", "tags": ["Roguelike"]}
            r.apply_meta_cache([game], path)
            self.assertEqual(game["tags"], ["Roguelike"])
            self.assertEqual(game["metadata_status"], "missing")

    def test_bounds(self):
        self.assertEqual(r.quality_lower_bound(0,0), 0)
        for pct in (0,40,70,95,100):
            for n in (99,100,1000,1000000):
                for discount in (-10,0,50,100,110):
                    self.assertTrue(0 <= r.calc_score(pct,n,discount) <= 10)
        self.assertFalse(r._meta_fresh({"schema_version":2,"updated":"2020-01-01T00:00:00+00:00"}))
        self.assertFalse(r._meta_fresh({"schema_version":2,"updated":"2026-09-12T00:00:00"}))

    def test_public_payload_exposes_filter_and_score_contract(self):
        r.TAG_NAMES["21"] = "Adventure"
        game = r._parse_row(row(tags="[21]"))
        payload = r.build_json_payload({game["block"]: [game]}, 1)
        saved = payload["blocks"][0]["games"][0]
        self.assertEqual(saved["tags"], ["Adventure"])
        self.assertEqual(saved["score_version"], 2)
        self.assertEqual(saved["currency"], "BRL")
        self.assertIn("categories", saved)

if __name__ == "__main__":
    unittest.main()
