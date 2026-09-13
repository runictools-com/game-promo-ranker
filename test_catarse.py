import json
import unittest
from datetime import datetime, timezone

from catarse import records_from_html, boardgame_evidence, collect_catarse
from discovery import qualify_campaign, public_image_url


def page(value, text=""):
    flight = "1:" + json.dumps(value, ensure_ascii=False) + "\n"
    if text:
        flight = "2:T" + format(len(text.encode()), "x") + "," + text + flight
    # Deliberately split inside a record, as the real Next page does.
    return "".join('<script>self.__next_f.push(' + json.dumps([1, part]) + ')</script>'
                   for part in (flight[:31], flight[31:]))


class CatarseTests(unittest.TestCase):
    def test_flight_utf8_length_and_chunk_boundaries(self):
        result = records_from_html(page({"story": "$2"}, "<p>Ação 🦊</p>"))
        self.assertEqual(result["2"], "<p>Ação 🦊</p>")
        self.assertEqual(result["1"], {"story": "$2"})
        with self.assertRaises(ValueError):
            records_from_html("<html>access denied</html>")

    def test_boardgame_filter_uses_campaign_evidence(self):
        self.assertTrue(boardgame_evidence({"title": "Novo jogo", "summary": "Jogo de cartas cooperativo"}, ""))
        self.assertTrue(boardgame_evidence({"title": "Kakehashi"}, '<a href="https://ludopedia.com.br/jogo/kakehashi">Jogo</a>'))
        for title in ("Heart RPG", "Sleeves para boardgame", "Jogo de tabuleiro Late Pledge", "Tarô de cartas"):
            self.assertFalse(boardgame_evidence({"title": title}, "Jogo de tabuleiro"))
        self.assertFalse(boardgame_evidence({"title": "Digital", "summary": "Jogo digital"}, "boardgame"))
        self.assertFalse(boardgame_evidence({"title": "Desconhecido", "user": {"bio": "Criamos boardgames"}}, ""))

    def test_real_contributors_cents_dates_and_duplicate_listing(self):
        now = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
        project = dict(slug="fixture", title="Jogo de tabuleiro", status="Launch", categoryId=2,
                       goalAmount=2600000, fundsCollected=4023500, contributorsCount=116, followerCount=9999,
                       startDate="2026-09-08T14:42:22Z", endDate="2026-10-18T02:59:00Z",
                       thumbnail="https://example.org/cover.png")
        def collect(changes):
            return collect_catarse(page([project, project]), now, lambda url: page(dict(project, **changes)),
                                   qualify_campaign, public_image_url)
        rows = collect({})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["backers"], 116)
        self.assertEqual(rows[0]["pledged"], 40235)
        self.assertEqual(rows[0]["goal"], 26000)
        self.assertEqual(rows[0]["image"], project["thumbnail"])
        for changes in ({"contributorsCount": 99}, {"contributorsCount": None}, {"status": "Successful"},
                        {"endDate": "2026-09-13T11:00:00Z"}, {"fundsCollected": 0}, {"isAdultContent": True}):
            self.assertEqual(collect(changes), [])


if __name__ == "__main__":
    unittest.main()
