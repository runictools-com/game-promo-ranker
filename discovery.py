"""Public discovery collectors. Missing evidence never becomes a recommendation.

Run daily: python discovery.py --json data/discovery.json
Campaign qualification is traction, NOT a prediction of delivery or game quality.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import json
import math
import hashlib
from pathlib import Path
import re
import tempfile
import os
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests

SOURCES = [
    {"id": "meeplestarter", "name": "MeepleStarter", "url": "https://meeplestarter.com.br/", "kind": "boardgame", "mode": "automatic", "region": "BR"},
    {"id": "gamefound", "name": "Gamefound", "url": "https://gamefound.com/en/projects/search", "kind": "boardgame", "mode": "automatic", "region": "international"},
    {"id": "kickstarter", "name": "Kickstarter • videogames", "url": "https://www.kickstarter.com/discover/advanced?category_id=35&state=live&sort=magic", "kind": "indie", "mode": "automatic", "region": "international"},
    {"id": "catarse", "name": "Catarse • jogos", "url": "https://www.catarse.me/explore?ref=ctrse_header&filter=games", "kind": "boardgame", "mode": "directory", "region": "BR"},
]

EVENT_SOURCES = [
    {"name": "Geek Connection • calendário nacional", "url": "https://geekconnection.net/Calendario/", "tags": ["anime", "games", "boardgame", "tcg"]},
    {"name": "Play! Pokémon • calendário oficial", "url": "https://championships.pokemon.com/en-us/events?region=latinamerica&status=upcoming", "tags": ["tcg", "games"]},
    {"name": "Diversão Offline", "url": "https://diversaooffline.com.br/", "tags": ["boardgame", "rpg"]},
    {"name": "Wizards • lojas e eventos", "url": "https://locator.wizards.com/", "tags": ["tcg"]},
]

# Explicitly dated editorial facts; a successful HTTP request does not renew them.
EVENTS = [
    {"id": "pokemon-laic-2027", "name": "Pokémon LAIC • temporada 2027", "start_date": "2026-11-20", "end_date": "2026-11-22", "city": "São Paulo", "state": "SP", "venue": "Centro de Convenções • Distrito Anhembi", "tags": ["tcg", "games", "pokemon"], "url": "https://championships.pokemon.com/en-us/events/internationals/2027/sao-paulo", "source_url": "https://championships.pokemon.com/en-us/events/internationals/2027/sao-paulo", "note": "O nome da temporada é 2027; o evento acontece em novembro de 2026."},
    {"id": "bgs-2026", "name": "Brasil Game Show 2026", "start_date": "2026-10-09", "end_date": "2026-10-12", "city": "São Paulo", "state": "SP", "venue": "Distrito Anhembi", "tags": ["games", "indie"], "url": "https://www.brasilgameshow.com.br/", "source_url": "https://www.brasilgameshow.com.br/", "note": "Confira no ingresso as regras de acesso do dia 9."},
    {"id": "animextreme-2026", "name": "Animextreme 34", "start_date": "2026-10-17", "end_date": "2026-10-18", "city": "Porto Alegre", "state": "RS", "venue": "Centro de Eventos FIERGS", "tags": ["anime", "games", "cosplay"], "url": "https://animextreme.com.br/", "source_url": "https://linktr.ee/animextreme", "note": "Datas do site principal e perfil oficial; página de expositores apresenta divergência."},
    {"id": "ccxp-2026", "name": "CCXP 2026", "start_date": "2026-12-03", "end_date": "2026-12-06", "city": "São Paulo", "state": "SP", "venue": "São Paulo Expo", "tags": ["anime", "games", "cultura-pop"], "url": "https://ccxp.com.br/", "source_url": "https://ccxp.com.br/", "note": "Programação e ingressos sujeitos a alteração pelo organizador."},
    {"id": "anime-friends-2027", "name": "Anime Friends 2027", "start_date": "2027-07-01", "end_date": "2027-07-04", "city": "São Paulo", "state": "SP", "venue": "Distrito Anhembi", "tags": ["anime", "games", "cosplay"], "url": "https://animefriends.com.br/af26-sp/informacoes/", "source_url": "https://animefriends.com.br/af26-sp/informacoes/", "note": "Próxima edição anunciada no rodapé oficial; conteúdo central ainda descreve 2026."},
    {"id": "doff-2027", "name": "Diversão Offline 2027", "start_date": "2027-07-09", "end_date": "2027-07-11", "city": "São Paulo", "state": "SP", "venue": "Expo Center Norte • Pavilhão Azul", "tags": ["boardgame", "rpg", "tcg"], "url": "https://diversaooffline.com.br/", "source_url": "https://poltronanerd.com.br/eventos/diversao-offline-confirma-data-da-12a-edicao-212441/", "note": "Anúncio da organização reproduzido pela imprensa; confirmar antes de comprar viagem."},
]
for _event in EVENTS:
    _event.update(verified_at="2026-09-12", valid_until="2026-10-12", country="BR", collection="curated")


BRAZIL_TZ = timezone(timedelta(hours=-3))


def brazil_date(now):
    return now.astimezone(BRAZIL_TZ).date()


def normalize_state(value):
    import unicodedata
    name = "".join(c for c in unicodedata.normalize("NFD", str(value or "")) if not unicodedata.combining(c)).strip().upper()
    if name.startswith("BR-"):
        name = name[3:]
    states = dict(zip(
        ["ACRE", "ALAGOAS", "AMAPA", "AMAZONAS", "BAHIA", "CEARA", "DISTRITO FEDERAL", "ESPIRITO SANTO", "GOIAS", "MARANHAO", "MATO GROSSO", "MATO GROSSO DO SUL", "MINAS GERAIS", "PARA", "PARAIBA", "PARANA", "PERNAMBUCO", "PIAUI", "RIO DE JANEIRO", "RIO GRANDE DO NORTE", "RIO GRANDE DO SUL", "RONDONIA", "RORAIMA", "SANTA CATARINA", "SAO PAULO", "SERGIPE", "TOCANTINS"],
        "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()))
    return states.get(name, name if name in states.values() else "")


def utcnow():
    return datetime.now(timezone.utc)


def parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def money_br(text):
    return float(re.sub(r"[^\d,.]", "", text).replace(".", "").replace(",", ".") or 0)


def qualify_campaign(item, today=None, now=None):
    """Reject expired, small-crowd and missing-proof campaigns.

    Symbolic goals are not rejected outright; their score contribution saturates.
    """
    today = today or brazil_date(utcnow())
    now = now or (datetime.combine(today, datetime.min.time(), timezone.utc))
    if "T" in str(item.get("end_date", "")):
        try:
            deadline = datetime.fromisoformat(item["end_date"].replace("Z", "+00:00"))
            if deadline.tzinfo is None or deadline <= now:
                return None
        except ValueError:
            return None
    end = parse_date(item.get("end_date"))
    start = parse_date(item.get("start_date"))
    try:
        backers, pledged, goal = int(item.get("backers", 0)), float(item.get("pledged", 0)), float(item.get("goal", 0))
    except (TypeError, ValueError):
        return None
    minimum = 100 if item.get("region") == "BR" else 300
    if (not end or end < today or not start or start > today
            or item.get("status") != "live" or backers < minimum
            or goal <= 0 or pledged < goal or not all(map(math.isfinite, (pledged, goal)))):
        return None
    # Backer breadth dominates; oversubscription saturates at 5x, so a fake
    # R$1 goal cannot overpower thousands of actual supporters.
    breadth = min(1, math.log1p(backers) / math.log1p(10000))
    funding = min(1, math.log1p(pledged / goal) / math.log(6))
    result = dict(item)
    result.update(funded_pct=round(100 * pledged / goal, 1), score=round(100 * (.8 * breadth + .2 * funding), 1),
                  days_left=(end - today).days, qualification=f"Meta atingida e {backers:,} apoios (mínimo {minimum}).",
                  shipping_br=item.get("shipping_br", "unknown"),
                  brazil_note="Frete, impostos, idioma e disponibilidade para o Brasil precisam ser conferidos na campanha.")
    return result


def parse_meeplestarter(html, now=None):
    now = now or utcnow()
    soup = BeautifulSoup(html, "html.parser")
    if not soup.select(".projeto-infos"):
        raise ValueError("MeepleStarter: catálogo público ausente")
    items = {}
    for card in soup.select(".projeto-infos"):
        title = card.select_one("a.projeto-titulo")
        raised, goal, backers = (card.select_one(x) for x in (".projeto-valor", ".projeto-meta", ".projeto-apoios"))
        text = card.get_text(" ", strip=True)
        dates = re.findall(r"\b(\d{2}/\d{2}/\d{4})\b", text)
        if not all((title, raised, goal, backers)) or len(dates) != 2 or "ENCERRADA" in text:
            continue
        url = urljoin(SOURCES[0]["url"], title.get("href", ""))
        if urlparse(url).hostname != "meeplestarter.com.br":
            continue
        name = title.get_text(" ", strip=True)
        # Preorders / late pledges are not current crowdfunding campaigns.
        if re.search(r"late pledge|pré-venda|pre-venda", name, re.I):
            continue
        description = card.select_one(".projeto-resumo")
        desc = description.get_text(" ", strip=True) if description else ""
        if re.search(r"\bRPG\b", name + " " + desc) and not re.search(r"tabuleiro|card game", desc, re.I):
            kind = "rpg"
        else:
            kind = "boardgame"
        item = dict(id="meeple-" + url.rsplit("/", 1)[-1], name=name, url=url, source="MeepleStarter", source_url=url,
                    kind=kind, region="BR", currency="BRL", pledged=money_br(raised.text), goal=money_br(goal.text),
                    backers=int(re.sub(r"\D", "", backers.text)), start_date=datetime.strptime(dates[0], "%d/%m/%Y").date().isoformat(),
                    end_date=datetime.strptime(dates[1], "%d/%m/%Y").date().isoformat(), status="live", description=desc,
                    tags=[kind], verified_at=now.isoformat(), valid_until=(now + timedelta(hours=30)).isoformat())
        qualified = qualify_campaign(item, brazil_date(now), now)
        if qualified:
            items[url] = qualified
    return list(items.values())


def is_gamefound_accessory(raw):
    """Require concrete accessory evidence, not merely miniatures/fantasy tags."""
    name = raw.get("name", "")
    description = raw.get("shortDescription", "")
    text = name + " " + description
    tags = {tag.get("name", "").casefold() for tag in raw.get("projectTags", [])}
    accessory_words = r"\b(?:map tiles|battle ?maps|terrain (?:tiles|sets|pieces)|stl files|dice towers?|dice trays?|card sleeves|storage inserts)\b"
    playable_game = re.search(r"\b(?:board game|boardgame|card game|miniatures game|skirmish game|expansion|reprint)\b", text, re.I)
    # A game containing terrain or bonus STL files remains a game. Marketing
    # metadata like player counts alone does not establish gameplay.
    if playable_game:
        return False
    if re.search(accessory_words, text, re.I):
        return True
    return bool(tags & {"terrain building", "accessories", "stl"}) and bool(
        re.search(r"\b(?:terrain|accessor(?:y|ies)|stl|magnetic tiles)\b", text, re.I))


def parse_gamefound(html, now=None):
    now = now or utcnow()
    soup = BeautifulSoup(html, "html.parser")
    script = next((s.get_text() for s in soup.find_all("script") if '"pagedItems"' in s.get_text() and '"props"' in s.get_text()), None)
    if script is None:
        raise ValueError("Gamefound: catálogo estruturado ausente")
    payload = json.JSONDecoder().raw_decode(script[script.index('{"props"'):])[0]
    items = []
    for raw in payload["props"]["result"]["projects"]["pagedItems"]:
        if raw.get("phaseLabel") != "Crowdfunding" or is_gamefound_accessory(raw):
            continue
        item = dict(id=f"gamefound-{raw['projectID']}", name=raw["name"], source="Gamefound", source_url=raw["url"],
                    url=raw["url"], kind="boardgame", region="international", currency=None, currency_symbol=raw.get("currencySymbol"),
                    currency_note="Símbolo original da plataforma; moeda ISO não informada, sem conversão para reais.",
                    pledged=raw.get("fundsGathered"), goal=raw.get("campaignGoal"), backers=raw.get("backersCount"),
                    start_date=raw.get("campaignStart"), end_date=raw.get("campaignEnd"), status="live",
                    description=raw.get("shortDescription", ""), image=raw.get("imageUrl", ""),
                    tags=[x["name"] for x in raw.get("projectTags", []) if x.get("isVisible")],
                    verified_at=now.isoformat(), valid_until=(now + timedelta(hours=30)).isoformat())
        qualified = qualify_campaign(item, brazil_date(now), now)
        if qualified:
            items.append(qualified)
    return items


def parse_kickstarter(html, now=None):
    now = now or utcnow()
    soup = BeautifulSoup(html, "html.parser")
    nodes = soup.select("[data-project]")
    if not nodes:
        raise ValueError("Kickstarter: catálogo público indisponível")
    items = []
    for node in nodes:
        raw = json.loads(node["data-project"])
        if raw.get("state") != "live":
            continue
        url = raw["urls"]["web"]["project"]
        item = dict(id=f"kickstarter-{raw['id']}", name=raw["name"], source="Kickstarter", source_url=url, url=url,
                    kind="indie", region="international", currency=raw.get("currency"), pledged=raw.get("pledged"),
                    goal=raw.get("goal"), backers=raw.get("backers_count"), status="live",
                    start_date=datetime.fromtimestamp(raw["launched_at"], timezone.utc).isoformat(),
                    end_date=datetime.fromtimestamp(raw["deadline"], timezone.utc).isoformat(),
                    description=raw.get("blurb", ""), image=(raw.get("photo") or {}).get("full", ""), tags=["indie"],
                    verified_at=now.isoformat(), valid_until=(now + timedelta(hours=30)).isoformat())
        qualified = qualify_campaign(item, brazil_date(now), now)
        if qualified:
            items.append(qualified)
    return items


def parse_itch(html, now=None):
    """Separate available indie games, not crowdfunding and not Steam reviews."""
    now = now or utcnow()
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".game_cell")
    if not cards:
        raise ValueError("itch.io: catálogo ausente")
    rows = []
    for card in cards:
        title = card.select_one(".game_title a")
        rating = card.select_one(".game_rating[data-tooltip]")
        if not title or not rating:
            continue
        if re.search(r"18\+|NSFW|porn|erotic|hentai|sexual|adult.only", card.get_text(" ", strip=True), re.I):
            continue
        match = re.search(r"([\d.]+) average rating from ([\d,]+) total ratings", rating["data-tooltip"])
        if not match:
            continue
        average, count = float(match[1]), int(match[2].replace(",", ""))
        if count < 300 or not 4.5 <= average <= 5:
            continue
        genre, image, desc = (card.select_one(s) for s in (".game_genre", "img", ".game_text"))
        url = title.get("href", "")
        if urlparse(url).scheme != "https" or not (urlparse(url).hostname or "").endswith(".itch.io"):
            continue
        rows.append(dict(id="itch-" + card.get("data-game_id", ""), name=title.get_text(" ", strip=True),
                         url=url, source="itch.io", source_url="https://itch.io/games/top-rated", kind="indie",
                         collection="available_games", rating=average, reviews=count,
                         score=round(20 * (average * count + 4.0 * 50) / (count + 50), 1),
                         description=desc.get_text(" ", strip=True) if desc else "",
                         image=(image.get("data-lazy_src") or image.get("src", "")) if image else "",
                         tags=[genre.get_text(" ", strip=True)] if genre else ["indie"],
                         verified_at=now.isoformat(), valid_until=(now + timedelta(hours=30)).isoformat(),
                         note="Jogo disponível; não é financiamento coletivo. Avaliações do itch.io; preço, idioma e plataforma na página do autor."))
    return sorted(rows, key=lambda x: (x["score"], x["reviews"]), reverse=True)


def parse_event_jsonld(html, source_url, now=None):
    now = now or utcnow()
    def walk(node):
        if isinstance(node, list):
            for child in node:
                yield from walk(child)
        elif isinstance(node, dict):
            types = node.get("@type", [])
            if types == "Event" or isinstance(types, list) and "Event" in types:
                yield node
            for value in node.values():
                if isinstance(value, (list, dict)):
                    yield from walk(value)
    rows = []
    for script in BeautifulSoup(html, "html.parser").find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.get_text())
        except ValueError:
            continue
        for raw in walk(payload):
            start, end = parse_date(raw.get("startDate")), parse_date(raw.get("endDate") or raw.get("startDate"))
            if not start or not end or end < brazil_date(now) or "Cancelled" in raw.get("eventStatus", ""):
                continue
            location = raw.get("location") or {}
            if not isinstance(location, dict):
                continue
            address = location.get("address") or {}
            if not isinstance(address, dict):
                address = {}
            place = location.get("name", "")
            country = address.get("addressCountry", "")
            if isinstance(country, dict):
                country = country.get("name", "")
            if country.upper() not in ("BR", "BRASIL", "BRAZIL") and not re.search(r",\s*(Brazil|Brasil)\b", place, re.I):
                continue
            city = address.get("addressLocality", "")
            state = normalize_state(address.get("addressRegion", ""))
            if not city:
                parts = place.split(",")
                city = parts[-2].strip() if len(parts) >= 3 else "Não informado"
            if not state:
                state = {"São Paulo": "SP", "Fortaleza": "CE", "Porto Alegre": "RS", "Rio de Janeiro": "RJ", "Curitiba": "PR", "Belo Horizonte": "MG", "Recife": "PE", "Salvador": "BA", "Brasília": "DF"}.get(city, "")
            name = raw.get("name", "Evento")
            tags = []
            for pattern, tag in [(r"anime|sana|ccxp", "anime"), (r"game|jogo|ccxp|sana", "games"), (r"board|tabuleiro|offline", "boardgame"), (r"pokemon|pokémon|tcg|magic", "tcg")]:
                if re.search(pattern, name, re.I):
                    tags.append(tag)
            url = raw.get("sameAs") or raw.get("url") or source_url
            if not isinstance(url, str) or urlparse(url).scheme != "https":
                continue
            rows.append(dict(id="event-" + hashlib.sha256((name + start.isoformat()).encode()).hexdigest()[:12],
                             name=name, start_date=start.isoformat(), end_date=end.isoformat(), city=city, state=state,
                             country="BR", venue=place, tags=tags, url=url, source_url=source_url,
                             verified_at=now.isoformat(), valid_until=(now + timedelta(days=3)).isoformat(),
                             collection="aggregated", stale=False, days_until=(start - brazil_date(now)).days,
                             note="Data extraída de calendário público; confirme programação e ingresso na fonte oficial."))
    return rows


def collect_extras(now, fetch=None):
    def get(url):
        if fetch:
            return fetch(url)
        response = requests.get(url, timeout=(5, 15), headers={"User-Agent": "GamePromo/2.0 (+https://gamepromo.runictools.com)"})
        response.raise_for_status()
        return response.content.decode("utf-8", errors="replace")
    statuses = []
    indie, events = [], []
    for kind, url in [("indie", "https://itch.io/games/top-rated"), ("events", "https://eubrasileiro.com/events")]:
        try:
            html = get(url)
            rows = parse_itch(html, now) if kind == "indie" else parse_event_jsonld(html, url, now)
            if kind == "indie":
                indie = rows
            else:
                events = rows
            statuses.append(dict(id=kind, url=url, status="ok" if rows else "no_verified_items", count=len(rows), checked_at=now.isoformat()))
        except (requests.RequestException, ValueError, TypeError, KeyError):
            statuses.append(dict(id=kind, url=url, status="unavailable", count=0, checked_at=now.isoformat()))
    return indie, events, statuses


def get_events(today=None, state=None, tag=None, city=None):
    today = today or brazil_date(utcnow())
    rows = []
    for event in EVENTS:
        if parse_date(event["end_date"]) < today:
            continue
        if state and event["state"] != state.upper():
            continue
        if tag and tag not in event["tags"]:
            continue
        if city and city.casefold() not in event["city"].casefold():
            continue
        rows.append(dict(event, stale=parse_date(event["valid_until"]) < today,
                         days_until=(parse_date(event["start_date"]) - today).days))
    return sorted(rows, key=lambda x: x["start_date"])


def collect(now=None, fetch=None):
    now = now or utcnow()
    parsers = {"meeplestarter": parse_meeplestarter, "gamefound": parse_gamefound, "kickstarter": parse_kickstarter}
    def source_result(source):
        status = dict(source, checked_at=now.isoformat())
        if source["mode"] != "automatic":
            return [], dict(status, status="directory", note="Link para explorar; campanhas não coletadas automaticamente.")
        try:
            if fetch:
                html = fetch(source["url"])
            else:
                response = requests.get(source["url"], timeout=(5, 15), headers={"User-Agent": "GamePromo/2.0 (+https://gamepromo.runictools.com)"})
                response.raise_for_status()
                html = response.content.decode("utf-8", errors="replace")
            rows = parsers[source["id"]](html, now)
            return rows, dict(status, status="ok", count=len(rows), note="Amostra do catálogo público; não cobre todas as campanhas da plataforma.")
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            return [], dict(status, status="unavailable", count=0, note="Coleta indisponível; consulte a fonte. Nenhuma campanha foi inferida.", error=type(exc).__name__)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(source_result, SOURCES))
    campaigns = sorted((r for rows, _ in results for r in rows), key=lambda x: x["score"], reverse=True)
    indie, automatic_events, extra_statuses = collect_extras(now, fetch)
    events = get_events(brazil_date(now))
    for event in automatic_events:
        # Renew only when independently parsed dates, city and name match.
        # Keep the editorial timestamp separate from the fresh calendar proof.
        existing = next((x for x in events if x["start_date"] == event["start_date"] and x["city"] == event["city"] and
                         (x["name"].casefold() in event["name"].casefold() or event["name"].split()[0].casefold() in x["name"].casefold())), None)
        if existing:
            existing.update(calendar_checked_at=now.isoformat(), calendar_source_url=event["source_url"])
            if existing["end_date"] == event["end_date"]:
                existing.update(editorial_verified_at=existing["verified_at"], verified_at=now.isoformat(),
                                valid_until=event["valid_until"], stale=False, collection="curated+calendar")
        else:
            events.append(event)
    return dict(updated_at=now.isoformat(), valid_until=(now + timedelta(hours=30)).isoformat(), campaigns=campaigns,
                sources=[s for _, s in results], indie_games=indie, extra_sources=extra_statuses,
                events=sorted(events, key=lambda x: x["start_date"]), event_sources=EVENT_SOURCES,
                methodology="Só campanhas abertas, financiadas e com pelo menos 100 apoios BR ou 300 internacionais. Nota: 80% amplitude de apoiadores, 20% financiamento com saturação; não é avaliação do jogo nem garantia de entrega.",
                indie_methodology="Primeira página de mais bem avaliados do itch.io, pelo menos 300 avaliações e média 4,5/5. Média ajustada com 50 votos prévios de 4/5. Não são avaliações Steam nem campanhas; preço não coletado. Conteúdo adulto explícito no catálogo é excluído; classificação completa pode não estar disponível.",
                coverage="MeepleStarter e Gamefound: amostra automática. Kickstarter: tentativa pública, pode bloquear coleta. Catarse: diretório. Indies: primeira página itch.io. Eventos: calendário Eu, BR em JSON-LD e curadoria datada; cobertura parcial do Brasil.")


def save(payload, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--json", default="data/discovery.json")
    args = cli.parse_args()
    output = collect()
    save(output, args.json)
    print(json.dumps({"campaigns": len(output["campaigns"]), "events": len(output["events"]), "sources": {s["id"]: s["status"] for s in output["sources"]}}, ensure_ascii=False))
