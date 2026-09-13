import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import discovery as d


class DiscoveryImageTests(unittest.TestCase):
    def test_meeple_image_comes_from_own_campaign_card(self):
        html = '''<div class="cartao-projeto"><a class="projeto-thumb"><img src="/uploads/game.webp"></a>
        <div class="projeto-infos"><a class="projeto-titulo" href="/game">Game</a>
        <p class="projeto-valor">R$ 26.000,00</p><p class="projeto-meta">R$ 20.000,00</p>
        <p class="projeto-apoios">150 apoios</p>08/09/2026 30/10/2026</div></div>'''
        result = d.parse_meeplestarter(html, datetime(2026, 9, 12, 12, tzinfo=timezone.utc))
        self.assertEqual(result[0]["image"], "https://meeplestarter.com.br/uploads/game.webp")

    def test_official_metadata_and_unknown_host(self):
        fetch = Mock(return_value='<meta property="og:image" content="/poster.jpg">')
        self.assertEqual(d.event_preview_image("https://ccxp.com.br/", fetch), "https://ccxp.com.br/poster.jpg")
        fetch.reset_mock()
        self.assertEqual(d.event_preview_image("https://attacker.example/", fetch), "")
        fetch.assert_not_called()

    def test_redirect_cannot_leave_official_allowlist(self):
        response = Mock(status_code=302, headers={"Location": "https://attacker.example/"})
        with patch.object(d.requests, "get", return_value=response) as get:
            self.assertEqual(d.event_preview_image("https://ccxp.com.br/"), "")
            self.assertEqual(get.call_count, 1)
            self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_metadata_fetch_does_not_renew_event_facts(self):
        event = dict(url="https://ccxp.com.br/", verified_at="2026-09-12", stale=True)
        result = d.enrich_event_images([event], lambda _: '<meta property="og:image" content="https://cdn.example/image.jpg">')[0]
        self.assertEqual(result["verified_at"], event["verified_at"])
        self.assertTrue(result["stale"])
        self.assertEqual(result["image_kind"], "official_preview")

    def test_pokemon_preview_matches_current_edition(self):
        page = '<script>{"image_s":"/static-assets/images/2027-sao-paulo-2048.webp"}</script>'
        self.assertTrue(d.event_preview_image("https://championships.pokemon.com/en-us/events/internationals/2027/sao-paulo", lambda _: page).endswith("2027-sao-paulo-2048.webp"))
        self.assertEqual(d.event_preview_image("https://championships.pokemon.com/en-us/events/internationals/2028/sao-paulo", lambda _: page), "")

    def test_image_url_validation_and_schema_variants(self):
        for url in ("https://127.0.0.1/a", "https://localhost/a", "http://site.example/a", "data:image/png;base64,a", "https://site.example:8080/a"):
            self.assertEqual(d.public_image_url(url), "")
        self.assertEqual(d.public_image_url([{"contentUrl": "https://cdn.example/a.jpg"}]), "https://cdn.example/a.jpg")


if __name__ == "__main__":
    unittest.main()
