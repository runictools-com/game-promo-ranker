import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from verify_release import verify
from refresh_daily import JOBS


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


class ReleaseContractTests(unittest.TestCase):
    def write(self, folder, name, value):
        (folder / name).write_text(json.dumps(value), encoding="utf-8")

    def test_established_frontend_features_are_present(self):
        self.assertEqual(verify(ROOT), [])
        self.assertIn("COPY Dockerfile.gen ./", (ROOT / "Dockerfile.gen").read_text(encoding="utf-8"))

    def test_core_history_refresh_precedes_auxiliary_sources(self):
        scripts = [row[0] for row in JOBS]
        self.assertEqual(scripts[:3], ["steam_sale_ranker.py", "steam_history_daily.py",
                                       "steam_historical_import.py"])
        self.assertLess(scripts.index("steam_history_daily.py"), scripts.index("gamepass_prices.py"))

    def test_fresh_complete_v4_catalog_and_history_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.write(folder, "games.json", {
                "generated_at": NOW.isoformat(),
                "coverage": {"complete_catalog": True},
                "blocks": [{"games": [{"appid": 42, "score_version": 4}]}],
            })
            self.write(folder, "steam_price_history.json", {
                "games": {"42": {"low_cents": 100}},
                "historical": {"42": {"low_cents": 100}},
                "last_run": {"status": "ok", "finished_at": NOW.isoformat()},
            })
            self.assertEqual(verify(ROOT, folder, True, NOW), [])

    def test_stale_snapshots_and_old_ranking_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.write(folder, "games.json", {
                "generated_at": "2026-09-15T00:00:00Z",
                "coverage": {"complete_catalog": True},
                "blocks": [{"games": [{"appid": 42, "score_version": 3}]}],
            })
            self.write(folder, "steam_price_history.json", {
                "games": {"42": {}}, "historical": {"42": {}},
                "last_run": {"status": "ok", "finished_at": "2026-09-15T00:00:00Z"},
            })
            issues = verify(ROOT, folder, True, NOW)
            self.assertIn("Steam catalog is older than 36 hours", issues)
            self.assertIn("daily Steam price verification is stale or incomplete", issues)
            self.assertIn("Steam catalog contains a ranking version older than v4", issues)


if __name__ == "__main__":
    unittest.main()
