import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

import requests
import steam_history_daily as daily
from price_history_store import observe, read_history, write_history

NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


def priced(cents=1000):
    return {"success": True, "data": {"price_overview": {"currency": "BRL", "final": cents}}}


class DailyHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.path = self.folder / "steam_price_history.json"

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self, name, value):
        (self.folder / name).write_text(json.dumps(value), encoding="utf8")

    def test_missing_price_is_not_zero(self):
        for item in ({}, {"success": False}, {"success": True, "data": []}, priced(None), priced(True), priced(-1), priced("0")):
            self.assertIsNone(daily.brl_price(item))
        wrong = priced(0)
        wrong["data"]["price_overview"]["currency"] = "USD"
        self.assertIsNone(daily.brl_price(wrong))
        self.assertEqual(daily.brl_price(priced(0)), 0)

    def test_tracks_union_including_old_offsale_and_upcoming(self):
        history = read_history(self.path)
        observe(history, 1, 500, "2026-09-01T12:00:00+00:00")
        history["attempts"] = {"5": {"status": "awaiting_price", "last_attempt": None}}
        write_history(self.path, history)
        self.snapshot("games.json", {"blocks": [{"games": [{"appid": 2}]}]})
        self.snapshot("gamepass_prices.json", {"prices": {"abc": {"appid": 3}}})
        self.snapshot("releases.json", {"releases": [{"appid": 4}]})
        calls = []
        def fetch(ids):
            calls.extend(ids)
            return {appid: priced(2000) for appid in ids}
        result = daily.run(self.folder, fetch_batch=fetch, now=NOW, batch_size=2)
        self.assertEqual(calls, ["1", "2", "3", "4", "5"])
        self.assertEqual(result["games"]["1"]["low_cents"], 500)
        self.assertEqual(result["games"]["1"]["last_price_cents"], 2000)
        self.assertEqual(result["last_run"]["observed_count"], 5)

    def test_unavailable_prices_keep_old_min_and_unknown_pending(self):
        history = read_history(self.path)
        observe(history, 1, 499, "2026-09-01T12:00:00+00:00")
        write_history(self.path, history)
        self.snapshot("releases.json", {"releases": [{"appid": 2}]})
        result = daily.run(self.folder, fetch_batch=lambda ids: {x: {"success": False} for x in ids}, now=NOW)
        self.assertEqual(result["last_run"]["status"], "ok")
        self.assertEqual(result["last_run"]["unavailable_count"], 2)
        self.assertEqual(result["games"]["1"]["low_cents"], 499)
        self.assertEqual(result["games"]["1"]["last_checked"], "2026-09-01T12:00:00+00:00")
        self.assertNotIn("2", result["games"])
        self.assertEqual(result["attempts"]["2"]["status"], "awaiting_price")
        self.assertEqual(result["coverage"]["stale_prices"], 1)

    def test_source_failure_stops_batches_and_saves_progress(self):
        self.snapshot("releases.json", {"releases": [{"appid": x} for x in range(1, 5)]})
        calls = []
        def fetch(ids):
            calls.append(ids)
            if len(calls) == 2:
                # First batch must already be on disk before second request.
                self.assertIn("1", read_history(self.path)["games"])
                raise requests.HTTPError("429")
            return {x: priced(100) for x in ids}
        result = daily.run(self.folder, fetch_batch=fetch, now=NOW, batch_size=1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["last_run"]["status"], "partial")
        self.assertEqual(result["last_run"]["unattempted_count"], 2)
        self.assertEqual(result["attempts"]["2"]["status"], "source_error")
        self.assertEqual(read_history(self.path)["games"]["1"]["low_cents"], 100)

    def test_seed_only_never_calls_network(self):
        self.snapshot("releases.json", {"releases": [{"appid": 42}]})
        with patch.object(daily.SteamTransport, "get_json", side_effect=AssertionError("network forbidden")):
            result = daily.run(self.folder, seed_only=True, now=NOW)
        self.assertEqual(result["last_run"]["status"], "seeded")
        self.assertIn("42", result["attempts"])
        self.assertNotIn("42", result["games"])

    def test_real_transport_contract_batches_fifty_brazil_prices_only(self):
        self.snapshot("releases.json", {"releases": [{"appid": x} for x in range(1, 52)]})
        calls = []
        def fetch(url, params):
            calls.append((url, params))
            return {x: priced(100) for x in params["appids"].split(",")}
        with patch.object(daily.SteamTransport, "get_json", side_effect=fetch):
            result = daily.run(self.folder, now=NOW)
        self.assertEqual([len(params["appids"].split(",")) for _, params in calls], [50, 1])
        self.assertTrue(all(url == daily.STEAM_APPDETAILS and params["cc"] == "br" and params["filters"] == "price_overview" for url, params in calls))
        self.assertEqual(result["last_run"]["observed_count"], 51)

    def test_corrupt_history_is_preserved_and_cli_fails(self):
        self.path.write_text("broken history", encoding="utf8")
        with patch.object(daily.SteamTransport, "get_json", side_effect=AssertionError("network forbidden")):
            self.assertEqual(daily.main(["--data-dir", str(self.folder), "--seed-only"]), 1)
        self.assertEqual(self.path.read_text(encoding="utf8"), "broken history")

    def test_cli_partial_exit_one(self):
        with patch.object(daily, "run", return_value={"last_run": {"status": "partial"}}):
            self.assertEqual(daily.main(["--data-dir", str(self.folder)]), 1)


if __name__ == "__main__":
    unittest.main()
