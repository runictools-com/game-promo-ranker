import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime,timezone
import price_history_store as p

T1="2026-09-12T12:00:00+00:00"
T2="2026-09-13T12:00:00+00:00"
T0="2026-09-11T12:00:00+00:00"

class HistoryTests(unittest.TestCase):
    def empty(self):return {"schema_version":1,"games":{}}
    def test_first_equal_higher_lower_and_idempotence(self):
        h=self.empty();e=p.observe(h,"42",1000,T1)
        self.assertIsNone(e["new_low_at"])
        p.observe(h,"42",1000,T1)
        self.assertEqual(len(e["observation_dates"]),1)
        p.observe(h,"42",2000,T2)
        self.assertEqual(e["low_cents"],1000)
        self.assertEqual(e["low_at"],T1)
        p.observe(h,"42",500,"2026-09-14T12:00:00+00:00")
        self.assertEqual(e["low_cents"],500)
        self.assertEqual(e["new_low_at"],e["low_at"])
    def test_out_of_order_preserves_latest(self):
        h=self.empty();e=p.observe(h,"42",1000,T2)
        p.observe(h,"42",500,T0)
        self.assertEqual(e["low_cents"],500)
        self.assertEqual(e["last_checked"],T2)
        self.assertEqual(e["last_price_cents"],1000)
        self.assertEqual(e["first_seen"],T0)
    def test_zero_and_validation(self):
        h=self.empty();self.assertEqual(p.observe(h,"42",0,T1)["low_cents"],0)
        for value in [-1,True,1.5,"100"]:
            with self.assertRaises(p.HistoryError):p.observe(h,"42",value,T1)
        with self.assertRaises(p.HistoryError):p.observe(h,"42",1,"2026-09-13T12:00:00")
    def test_corruption_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"h.json";path.write_text("broken")
            with self.assertRaises(p.HistoryError):p.read_history(path)
            with self.assertRaises(p.HistoryError):p.write_history(path,self.empty())
            self.assertEqual(path.read_text(),"broken")
    def test_legacy_only_brl_no_false_low_date(self):
        h=self.empty();p.migrate_legacy(h,{"42":{"src":"obs","currency":"BRL","country":"BR","low_brl":"12.34","first_seen":T1,"updated":T2,"observed_dates":["2026-09-12"]},"43":{"src":"cs","currency":"USD","low_brl":1}})
        self.assertEqual(h["games"]["42"]["low_cents"],1234)
        self.assertIsNone(h["games"]["42"]["low_at"])
        self.assertNotIn("43",h["games"])
        p.migrate_legacy(h,{"42":{"src":"obs","currency":"BRL","country":"BR","low_brl":99,"first_seen":T1,"updated":T2}})
        self.assertEqual(h["games"]["42"]["low_cents"],1234)
    def test_seed_preserves_timestamps_and_filters_stale_currency(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            data={"generated_at":T2,"blocks":[{"games":[{"appid":"42","currency":"BRL","country":"BR","sale_price":"R$ 1.299,99"},{"appid":"43","currency":"USD","country":"US","sale_price":"R$ 1,00"}]}]}
            (folder/"games.json").write_text(json.dumps(data))
            (folder/"gamepass_prices.json").write_text(json.dumps({"prices":{"a":{"appid":"44","currency":"BRL","price_cents":0,"checked_at":T2},"b":{"appid":"45","currency":"BRL","price_cents":1,"checked_at":"2020-01-01T00:00:00Z"}}}))
            h=p.seed_from_snapshots(folder,self.empty(),datetime(2026,9,13,13,tzinfo=timezone.utc))
            self.assertEqual(set(h["games"]),{"42","44"})
            self.assertEqual(h["games"]["42"]["low_cents"],129999)
            self.assertEqual(h["games"]["44"]["last_checked"],T2)
            p.write_history(folder/"h.json",h)
            self.assertEqual(p.read_history(folder/"h.json"),h)

    def test_observe_validates_only_target_write_validates_all(self):
        h=self.empty();p.observe(h,"42",1000,T1)
        h["games"]["43"]={"broken":True}
        p.observe(h,"42",900,T2)
        self.assertEqual(h["games"]["42"]["low_cents"],900)
        with self.assertRaises(p.HistoryError):p.observe(h,"43",900,T2)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"history.json"
            with self.assertRaises(p.HistoryError):p.write_history(path,h)
            self.assertFalse(path.exists())
