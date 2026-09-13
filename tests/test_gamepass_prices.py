import unittest
from datetime import datetime,timezone
from unittest.mock import Mock,patch
import requests
import gamepass_prices as p
NOW=datetime(2026,9,13,12,tzinfo=timezone.utc)

def row(title,appid="42",price="R$ 79,90"):
    return f'<a class="search_result_row" href="https://store.steampowered.com/app/{appid}/"><span class="title">{title}</span><div class="discount_final_price">{price}</div></a>'

class PriceTests(unittest.TestCase):
    def test_exact_editions_platform_typography(self):
        self.assertEqual(p.normalize_title("DOOM® (Windows)"),p.normalize_title("Doom"))
        self.assertNotEqual(p.normalize_title("Doom Deluxe Edition"),p.normalize_title("Doom"))
        self.assertIsNone(p.parse_search(row("Doom Deluxe Edition"),"Doom",NOW))
        self.assertEqual(p.parse_search(row("Doom"),"Doom (PC)",NOW)["price_cents"],7990)
    def test_ambiguous_and_currency(self):
        self.assertIsNone(p.parse_search(row("Doom")+row("Doom","43"),"Doom",NOW))
        self.assertIsNone(p.parse_search(row("Doom",price="$79.90"),"Doom",NOW))
        self.assertEqual(p.parse_search(row("Doom",price="Gratuito"),"Doom",NOW)["price_cents"],0)
    def test_subscription_correct_plan(self):
        self.assertIsNone(p.parse_subscription("PC Game Pass Ultimate R$99,99/mês",NOW))
        html="PC Game Pass – 1 Meses de PC Game Pass Microsoft Corporation R$59,99/mês XBOX Game Pass Ultimate R$76,90/mês"
        self.assertEqual(p.parse_subscription(html,NOW)["monthly_cents"],5999)
    def test_membership_failure_preserves_timestamps(self):
        client=Mock(blocked=True);client.get.side_effect=requests.Timeout()
        prior={"membership_checked_at":"old","prices":{"x":{"checked_at":"old"}},"active_ids":["x"]}
        data=p.collect({},prior,now=NOW,client=client)
        self.assertEqual(data["membership_checked_at"],"old")
        self.assertEqual(data["prices"],prior["prices"])
        self.assertEqual(data["subscription"]["checked_at"],p.FALLBACK_SUBSCRIPTION["checked_at"])
    def test_reuse_keeps_source_timestamp(self):
        checked="2026-09-13T00:00:00+00:00"
        g={"generated_at":checked,"blocks":[{"games":[{"name":"Doom","appid":"42","currency":"BRL","country":"BR","sale_price":"R$ 0,00"}]}]}
        self.assertEqual(p.reuse_index(g,NOW)["doom"]["checked_at"],checked)
        g["generated_at"]="2020-01-01T00:00:00+00:00"
        self.assertEqual(p.reuse_index(g,NOW),{})
    def test_rate_limit_stops_after_three(self):
        response=Mock(status_code=429,headers={"Retry-After":"0"})
        response.raise_for_status.side_effect=requests.HTTPError()
        c=p.PacedClient()
        with patch.object(p.requests,"get",return_value=response) as get,patch.object(p.time,"sleep"):
            with self.assertRaises(requests.HTTPError):c.get("https://example.com")
            self.assertTrue(c.blocked)
            self.assertEqual(get.call_count,3)
            with self.assertRaises(requests.RequestException):c.get("https://example.com")
            self.assertEqual(get.call_count,3)

    def test_changed_edition_removes_old_price(self):
        client=Mock(blocked=False)
        client.get.side_effect=[Mock(json=lambda:[{"id":"x"}]),Mock(text="no price"),Mock(json=lambda:{"results_html":""})]
        prior={"prices":{"x":{"title":"Doom Deluxe","price_cents":5000,"currency":"BRL","checked_at":NOW.isoformat()}}}
        output=p.collect({"catalog":[{"id":"x","title":"Doom"}]},prior,now=NOW,client=client)
        self.assertNotIn("x",output["prices"])
        self.assertEqual(client.get.call_args.args[1]["infinite"],1)

    def test_subscription_failure_does_not_block_steam_default(self):
        membership=Mock(blocked=False)
        membership.get.side_effect=[Mock(json=lambda:[{"id":"x"}]),Mock(json=lambda:{"results_html":row("Doom")})]
        subscription=Mock(blocked=True)
        subscription.get.side_effect=requests.HTTPError()
        with patch.object(p,"PacedClient",side_effect=[membership,subscription]):
            output=p.collect({"catalog":[{"id":"x","title":"Doom"}]},now=NOW)
        self.assertEqual(output["prices"]["x"]["price_cents"],7990)

    def test_platform_preview_markers_only(self):
        self.assertEqual(p.normalize_title("A Plague Tale: Requiem - Windows"),p.normalize_title("A Plague Tale: Requiem"))
        self.assertEqual(p.normalize_title("9 Kings (Prévia do Jogo)"),p.normalize_title("9 Kings"))
        self.assertEqual(p.normalize_title("9 Kings (Game Preview)"),p.normalize_title("9 Kings"))
        self.assertEqual(p.search_title("Windows of Tomorrow"),"Windows of Tomorrow")
        self.assertNotEqual(p.normalize_title("Doom Ultimate Edition - Windows"),p.normalize_title("Doom"))
