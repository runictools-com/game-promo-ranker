import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
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
        self.assertGreater(r.calc_score(95, 100000, 70)-r.calc_score(95, 10000, 70), .5)
        self.assertLess(r.calc_score(95, 1000000, 70)-r.calc_score(95, 100000, 70), .1)
        self.assertGreater(r.calc_score(95, 500, 80), r.calc_score(95, 500, 20))

    def test_balances_volume_positive_reviews_and_discount(self):
        self.assertGreater(r.calc_score(96, 60000, 80), r.calc_score(100, 100, 90))
        self.assertGreater(r.calc_score(98, 6000, 90), r.calc_score(85, 100000, 50))
        self.assertGreater(r.calc_score(95, 30000, 80), r.calc_score(95, 30000, 30))
        self.assertGreater(r.calc_score(95, 30000, 80), r.calc_score(70, 30000, 80))
        game = dict(pct_positive=95, total_reviews=30000, discount=80)
        r.update_score_details(game)
        self.assertEqual(game['score'], r.calc_score(95, 30000, 80))
        self.assertEqual(game['score_version'], 3)

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

    def test_search_transient_retry_honors_retry_after(self):
        limited = Mock(status_code=429, headers={"Retry-After":"9"})
        unavailable = Mock(status_code=503, headers={})
        success = Mock(status_code=200)
        with patch.object(r.requests,"get",side_effect=[limited,unavailable,success]) as get, patch.object(r.time,"sleep") as sleep, patch.object(r,"_search_last_call",None):
            self.assertIs(r._search_get({}), success)
        self.assertEqual(get.call_count,3)
        self.assertIn(unittest.mock.call(9.0),sleep.call_args_list)
        self.assertIn(unittest.mock.call(60.0),sleep.call_args_list)

    def test_search_retry_is_bounded(self):
        response = Mock(status_code=429, headers={"Retry-After":"9999"})
        response.raise_for_status.side_effect = r.requests.HTTPError("429",response=response)
        self.assertEqual(r._retry_delay(response,0),120)
        with patch.object(r.requests,"get",return_value=response) as get, patch.object(r.time,"sleep"), patch.object(r,"_search_last_call",None):
            with self.assertRaises(r.requests.HTTPError):
                r._search_get({})
        self.assertEqual(get.call_count,3)

    def test_search_calls_share_three_second_spacing(self):
        with patch.object(r.requests,"get",return_value=Mock(status_code=200)), patch.object(r.time,"sleep") as sleep, patch.object(r.time,"monotonic",return_value=100), patch.object(r,"_search_last_call",None):
            r._search_get({"sort_by":"Reviews_DESC"})
            r._search_get({"sort_by":"Discount_DESC"})
        sleep.assert_called_once_with(3.0)

    def test_retry_after_http_date_and_fallback(self):
        from datetime import datetime,timezone
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                return cls(2026,9,13,12,tzinfo=timezone.utc)
        with patch.object(r,"datetime",Clock):
            self.assertEqual(r._retry_delay(Mock(headers={"Retry-After":"Sun, 13 Sep 2026 12:01:00 GMT"}),0),60)
        self.assertEqual(r._retry_delay(Mock(headers={"Retry-After":"garbage"}),0),30)
        self.assertEqual(r._retry_delay(Mock(headers={"Retry-After":"NaN"}),1),60)

    def test_public_payload_exposes_filter_and_score_contract(self):
        r.TAG_NAMES["21"] = "Adventure"
        game = r._parse_row(row(tags="[21]"))
        payload = r.build_json_payload({game["block"]: [game]}, 1)
        saved = payload["blocks"][0]["games"][0]
        self.assertEqual(saved["tags"], ["Adventure"])
        self.assertEqual(saved["score_version"], 3)
        self.assertEqual(saved["currency"], "BRL")
        self.assertIn("categories", saved)

if __name__ == "__main__":
    unittest.main()
