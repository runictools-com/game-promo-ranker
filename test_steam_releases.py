import unittest
from unittest.mock import Mock
from datetime import datetime, timezone

import steam_releases as s

NOW = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)


def row(appid=1, raw="12 Sep, 2026", tags="[19]", descriptors="[]", key=None):
    return f'''<a class="search_result_row" data-ds-appid="{appid}" data-ds-itemkey="{key or f'App_{appid}'}"
    data-ds-tagids='{tags}' data-ds-content-descriptors='{descriptors}' href="https://store.steampowered.com/app/{appid}/game/">
    <span class="title">Game {appid}</span><div class="search_released">{raw}</div><div class="search_capsule"><img src="https://cdn.example/img.jpg"></div></a>'''


class ReleasesTests(unittest.TestCase):
    def transport(self, codes, headers=None):
        clock = [0.0]
        calls = []
        sleeps = []
        responses = []
        for code in codes:
            response = Mock(status_code=code, headers=headers or {})
            response.json.return_value = {"ok": True}
            if code >= 400:
                response.raise_for_status.side_effect = s.requests.HTTPError(str(code))
            responses.append(response)
        def request(*args, **kwargs):
            calls.append(clock[0])
            return responses.pop(0)
        def sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds
        return s.SteamTransport(request=request, sleep=sleep, monotonic=lambda: clock[0], utc=lambda: NOW), calls, sleeps

    def test_transport_throttles_all_threads_without_real_sleep(self):
        transport, calls, _ = self.transport([200] * 4)
        with s.ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(transport.get_json, [s.TAG_URL, s.SEARCH, s.SEARCH, s.SEARCH]))
        self.assertEqual(calls, [0, 3, 6, 9])

    def test_retry_after_and_fallback_share_cooldown(self):
        transport, calls, _ = self.transport([429, 503, 200])
        transport.get_json(s.SEARCH)
        self.assertEqual(calls, [0, 30, 90])
        transport, calls, sleeps = self.transport([429, 200], {"Retry-After": "120"})
        transport.get_json(s.SEARCH)
        self.assertEqual(calls, [0, 120])
        self.assertTrue(all(delay <= 60 for delay in sleeps))

    def test_retry_limit_and_following_thread_cooldown(self):
        transport, calls, _ = self.transport([429, 429, 429, 200], {"Retry-After": "5"})
        with self.assertRaises(s.requests.HTTPError):
            transport.get_json(s.SEARCH)
        transport.get_json(s.TAG_URL)
        self.assertEqual(calls, [0, 5, 10, 15])

    def test_partial_and_unavailable_exit_nonzero(self):
        self.assertEqual(s.exit_code(dict(status="ok", tag_status="ok")), 0)
        for status in ("partial", "unavailable"):
            self.assertEqual(s.exit_code(dict(status=status, tag_status="ok")), 1)

    def test_precision_never_fabricates_day(self):
        for raw, precision, period in [("Q4 2026", "quarter", "2026-Q4"), ("September 2026", "month", "2026-09"),
                                       ("2027", "year", "2027"), ("Coming soon", "unknown", None)]:
            value = s.parse_release_date(raw)
            self.assertIsNone(value["release_date"])
            self.assertEqual(value["date_precision"], precision)
            self.assertEqual(value["release_period"], period)
        self.assertEqual(s.parse_release_date("12 Sep, 2026")["release_date"], "2026-09-12")
        self.assertEqual(s.parse_release_date("Sep 12, 2026")["release_date"], "2026-09-12")
        self.assertIsNone(s.parse_release_date("31 Feb, 2026")["release_date"])

    def test_filter_excludes_explicit_not_mature(self):
        html = row(1, tags="[9130]") + row(2, descriptors="[3]") + row(3, tags="[5611]", descriptors="[1,2,5]") + row(4, key="Sub_4")
        rows = s.parse_rows(html, "scheduled", {"5611": "Mature"}, NOW)
        self.assertEqual([r["appid"] for r in rows], [3])
        self.assertEqual(rows[0]["tags"], ["Mature"])

    def test_upcoming_has_no_reviews_gate_and_released_requires_past_day(self):
        self.assertEqual(len(s.parse_rows(row(raw="Q4 2026"), "scheduled", now=NOW)), 1)
        self.assertEqual(s.parse_rows(row(raw="Q4 2026"), "released", now=NOW), [])
        self.assertEqual(s.parse_rows(row(raw="13 Sep, 2026"), "released", now=NOW), [])

    def test_source_failure_preserves_previous_record_unfreshened(self):
        prior = dict(releases=[dict(appid=1, name="Prior", source_id="scheduled", status="scheduled", tags=["Puzzle"],
                                    release_date="2026-10-01", date_precision="day", verified_at="2026-09-10")])
        def failed(url, params):
            raise s.requests.ConnectionError("offline")
        result = s.collect(prior, NOW, failed)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["releases"][0]["stale"])
        self.assertEqual(result["releases"][0]["verified_at"], "2026-09-10")

    def test_pagination_limit_and_dedupe_prefer_released(self):
        calls = []
        def fetch(url, params):
            if url == s.TAG_URL:
                return [{"tagid": 19, "name": "Action"}]
            calls.append(params)
            return dict(success=1, results_html=row(), total_count=2000)
        result = s.collect(now=NOW, fetch_json=fetch, max_pages=99, page_size=1)
        self.assertEqual(len(calls), 18)
        self.assertTrue(all(x["cc"] == "br" and x["category1"] == 998 for x in calls))
        self.assertEqual(len(result["releases"]), 1)
        self.assertEqual(result["releases"][0]["status"], "released")

    def test_missing_rows_with_nonzero_total_is_failure(self):
        def fetch(url, params):
            return [] if url == s.TAG_URL else dict(success=1, results_html="<html>blocked</html>", total_count=100)
        result = s.collect(now=NOW, fetch_json=fetch)
        self.assertEqual(result["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
