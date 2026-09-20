import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app


class HealthTests(unittest.TestCase):
    def payloads(self, folder, age_hours=0):
        now = datetime.now(timezone.utc)
        stamp = datetime.fromtimestamp(now.timestamp() - age_hours * 3600, timezone.utc).isoformat()
        games = folder / "games.json"
        history = folder / "steam_price_history.json"
        games.write_text(json.dumps({"generated_at": stamp, "coverage": {"complete_catalog": True},
                                     "blocks": [{"games": [{"appid": 42}]}]}), encoding="utf-8")
        history.write_text(json.dumps({"games": {"42": {}}, "historical": {"42": {}},
                                       "last_run": {"status": "ok", "finished_at": stamp}}), encoding="utf-8")
        return games, history

    def test_fresh_complete_snapshots_are_healthy(self):
        with tempfile.TemporaryDirectory() as temp:
            games, history = self.payloads(Path(temp))
            with patch.object(app, "DATA_FILE", str(games)), patch.dict("os.environ", {"STEAM_HISTORY_FILE": str(history)}):
                response = app.app.test_client().get("/healthz")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["ok"])

    def test_stale_snapshots_make_healthcheck_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            games, history = self.payloads(Path(temp), age_hours=72)
            with patch.object(app, "DATA_FILE", str(games)), patch.dict("os.environ", {"STEAM_HISTORY_FILE": str(history)}):
                response = app.app.test_client().get("/healthz")
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.get_json()["catalog_fresh"])
            self.assertFalse(response.get_json()["history_fresh"])


if __name__ == "__main__":
    unittest.main()
