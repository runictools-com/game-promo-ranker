import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import app as api
import discovery as d
import steam_sale_ranker as ranking

class TemporalReviewTests(unittest.TestCase):
    def test_normalize_state(self):
        self.assertEqual(d.normalize_state("São Paulo"), "SP")
        self.assertEqual(d.normalize_state("BR-SP"), "SP")
        self.assertEqual(d.normalize_state("Mato Grosso do Sul"), "MS")

    def test_collector_keeps_event_until_brazil_midnight(self):
        now = datetime(2026,10,13,1,tzinfo=timezone.utc)
        raw = {"@type":"Event","name":"Boardgame SP","startDate":"2026-10-12","endDate":"2026-10-12",
            "location":{"name":"Local","address":{"addressCountry":"BR","addressLocality":"São Paulo","addressRegion":"BR-SP"}},
            "url":"https://example.com/"}
        rows = d.parse_event_jsonld('<script type="application/ld+json">'+json.dumps(raw)+'</script>', 'https://example.com/', now)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "SP")
        self.assertEqual(d.brazil_date(now).isoformat(), "2026-10-12")

    def test_api_date_deadlines_use_local_day(self):
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026,10,13,3,30,tzinfo=timezone.utc)
        data = {"valid_until":"2026-10-14T00:00:00Z", "campaigns":[],"indie_games":[],
            "events":[{"state":uf,"end_date":"2026-10-12","valid_until":"2026-10-14"} for uf in ["SP","AM","AC"]]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"discovery.json"
            path.write_text(json.dumps(data))
            with patch.object(api, "DISCOVERY_FILE", str(path)), patch.object(api,"datetime",Clock):
                response = api.app.test_client().get("/api/discovery")
        self.assertEqual([e["state"] for e in response.json["events"]],["AM","AC"])

    def test_empty_steam_collection_is_failure(self):
        with patch.object(ranking.sys,"argv",["ranker"]), patch.object(ranking,"collect_all",return_value=[]):
            with self.assertRaises(SystemExit) as caught:
                ranking.main()
        self.assertEqual(caught.exception.code,1)

if __name__ == "__main__":
    unittest.main()
