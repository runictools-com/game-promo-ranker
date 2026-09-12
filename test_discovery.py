import json
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

import discovery as d

NOW = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)


class DiscoveryTests(unittest.TestCase):
    def campaign(self, **changes):
        item = dict(status="live", start_date="2026-09-01", end_date="2026-10-01", backers=500,
                    pledged=20000, goal=10000, region="BR")
        return dict(item, **changes)

    def test_tiny_crowd_cannot_game_symbolic_goal(self):
        self.assertIsNone(d.qualify_campaign(self.campaign(backers=10, goal=1), NOW.date()))
        tiny = d.qualify_campaign(self.campaign(backers=100, goal=1), NOW.date())
        broad = d.qualify_campaign(self.campaign(backers=3000), NOW.date())
        self.assertGreater(broad["score"], tiny["score"])

    def test_closed_unfunded_upcoming_missing_dates_rejected(self):
        for changes in [dict(end_date="2026-09-11"), dict(pledged=10), dict(start_date="2026-10-01"),
                        dict(end_date=None), dict(status="ended"), dict(pledged=float("nan")),
                        dict(region="international", backers=100)]:
            self.assertIsNone(d.qualify_campaign(self.campaign(**changes), NOW.date()))

    def test_timestamp_deadline_expires_exactly(self):
        self.assertIsNone(d.qualify_campaign(self.campaign(end_date="2026-09-12T11:59:59Z"), NOW.date(), NOW))
        self.assertIsNotNone(d.qualify_campaign(self.campaign(end_date="2026-09-12T12:00:01Z"), NOW.date(), NOW))

    def test_indies_require_review_evidence_and_exclude_explicit_adult(self):
        card = '''<div class="game_cell" data-game_id="1"><div class="game_title"><a href="https://author.itch.io/game">Game</a></div>
        <div class="game_rating" data-tooltip="4.90 average rating from 1,200 total ratings"></div><div class="game_genre">Puzzle</div></div>'''
        rows = d.parse_itch(card, NOW)
        self.assertEqual(rows[0]["reviews"], 1200)
        self.assertEqual(rows[0]["collection"], "available_games")
        self.assertNotIn("pledged", rows[0])
        self.assertEqual(d.parse_itch(card.replace("1,200", "10"), NOW), [])
        self.assertEqual(d.parse_itch(card.replace(">Game<", ">18+ NSFW Game<"), NOW), [])

    def test_event_jsonld_ignores_foreign_cancelled_and_requires_dates(self):
        item = {"@type": "Event", "name": "New Anime 2027", "startDate": "2027-01-01", "endDate": "2027-01-02",
                "url": "https://example.org/event", "location": {"name": "Expo, São Paulo, Brazil"}}
        payload = {"@graph": [item, dict(item, eventStatus="https://schema.org/EventCancelled"),
                              dict(item, location={"name": "Expo, Tokyo, Japan"}), dict(item, startDate=None)]}
        rows = d.parse_event_jsonld('<script type="application/ld+json">' + json.dumps(payload) + '</script>', "https://example.org", NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "SP")
        self.assertEqual(rows[0]["collection"], "aggregated")
        self.assertIn("anime", rows[0]["tags"])
        self.assertEqual(d.parse_event_jsonld("<html>OK</html>", "https://example.org", NOW), [])

    def test_meeple_uses_actual_backers_not_likes_and_deduplicates(self):
        card = '''<div class="projeto-infos"><div class="count-backers">99999</div>
        <a class="projeto-titulo" href="/fixture">Fixture</a><p class="projeto-resumo">Jogo de tabuleiro</p>
        <p class="projeto-valor">R$ 26.996,00</p><p class="projeto-meta">da meta de R$ 26.000,00</p>
        <p>Começou em 08/09/2026 Termina em 30/10/2026</p><p class="projeto-apoios">147 apoios</p></div>'''
        rows = d.parse_meeplestarter(card * 2, NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["backers"], 147)
        self.assertEqual(rows[0]["pledged"], 26996)
        self.assertEqual(rows[0]["shipping_br"], "unknown")
        self.assertEqual(d.parse_meeplestarter(card.replace("147 apoios", "10 apoios"), NOW), [])

    def test_gamefound_ignores_late_pledges_and_preserves_tags(self):
        raw = dict(projectID=1, name="Fixture", url="https://gamefound.com/en/projects/a/b",
                   phaseLabel="Crowdfunding", fundsGathered=50000, campaignGoal=10000, backersCount=500,
                   campaignStart="2026-09-01T00:00:00Z", campaignEnd="2026-10-01T00:00:00Z",
                   projectTags=[dict(name="Cooperative", isVisible=True)])
        def page(projects):
            return '<script>App.register("x",' + json.dumps({"props": {"result": {"projects": {"pagedItems": projects}}}}) + ');</script>'
        rows = d.parse_gamefound(page([raw, dict(raw, phaseLabel="Late pledge")]), NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tags"], ["Cooperative"])

    def test_gamefound_accessories_excluded_but_miniatures_games_preserved(self):
        terrain = dict(name="Realm Brew: Into The Depths [Production Run #2]",
                       shortDescription="Realm Brew: Magnetic Map Tiles For D&D",
                       projectTags=[dict(name="Terrain Building"), dict(name="TTRPG")],
                       projectProperties=dict(enableBoardGameProperties=True, minPlayers=1))
        self.assertTrue(d.is_gamefound_accessory(terrain))
        game = dict(name="Heroes of the Depths", shortDescription="A cooperative miniatures game with terrain tiles and STL files.",
                    projectTags=[dict(name="Terrain Building"), dict(name="Cooperative")])
        self.assertFalse(d.is_gamefound_accessory(game))
        self.assertFalse(d.is_gamefound_accessory(dict(game, name="Heroes expansion", shortDescription="Terrain tiles and new miniatures.")))
        self.assertFalse(d.is_gamefound_accessory(dict(name="Fantasy adventures", shortDescription="A tactical adventure.",
                                                      projectTags=[dict(name="Collectible Models")])) )

    def test_events_filter_expire_and_do_not_renew_editorial_date(self):
        rows = d.get_events(date(2026, 9, 12), state="sp", tag="tcg")
        self.assertTrue(rows)
        self.assertTrue(all(r["state"] == "SP" and "tcg" in r["tags"] for r in rows))
        later = d.get_events(date(2026, 12, 1))
        self.assertTrue(all(r["stale"] for r in later))
        self.assertTrue(all(r["verified_at"] == "2026-09-12" for r in later))
        self.assertFalse(any(r["id"] == "bgs-2026" for r in later))

    def test_source_failures_are_not_reported_as_empty_success(self):
        def failed(url):
            raise d.requests.ConnectionError("offline")
        result = d.collect(NOW, fetch=failed)
        self.assertEqual(result["campaigns"], [])
        self.assertTrue(all(s["status"] == "unavailable" for s in result["sources"] if s["mode"] == "automatic"))
        self.assertTrue(result["events"])

    def test_plain_http_success_does_not_renew_event_verification(self):
        later = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        result = d.collect(later, fetch=lambda url: "<html>OK</html>")
        ccxp = next(x for x in result["events"] if x["id"] == "ccxp-2026")
        self.assertEqual(ccxp["verified_at"], "2026-09-12")
        self.assertTrue(ccxp["stale"])


if __name__ == "__main__":
    unittest.main()
