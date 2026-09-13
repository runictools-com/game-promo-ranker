"""Read Catarse's public server-rendered campaign data; no private API needed."""
import json
import re
import unicodedata
from urllib.parse import urlparse
from datetime import timedelta, timezone

from bs4 import BeautifulSoup

BASE = "https://www.catarse.com.br/"


def records_from_html(html):
    """Decode Next Flight JSON and length-prefixed UTF-8 text without executing JS."""
    chunks = []
    for script in BeautifulSoup(html, "html.parser").select("script"):
        match = re.fullmatch(r"self\.__next_f\.push\((\[.*\])\);?", script.text.strip(), re.S)
        if match:
            value = json.loads(match[1])
            if len(value) == 2 and value[0] == 1 and isinstance(value[1], str):
                chunks.append(value[1])
    data = "".join(chunks).encode("utf-8")
    records, pos = {}, 0
    while pos < len(data):
        match = re.match(rb"([0-9a-f]+):", data[pos:])
        if not match:
            raise ValueError("Unrecognized Catarse page data")
        key = match[1].decode()
        pos += match.end()
        text = re.match(rb"T([0-9a-f]+),", data[pos:])
        if text:
            pos += text.end()
            size = int(text[1], 16)
            if pos + size > len(data):
                raise ValueError("Truncated Catarse text")
            records[key] = data[pos:pos + size].decode("utf-8")
            pos += size
        else:
            end = data.find(b"\n", pos)
            end = len(data) if end < 0 else end
            value = data[pos:end]
            if value[:1] in (b"[", b"{", b'"'):
                records[key] = json.loads(value)
            pos = end + 1
        while data[pos:pos + 1] == b"\n":
            pos += 1
    if not records:
        raise ValueError("Missing Catarse campaign data")
    return records


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFD", value.casefold()) if not unicodedata.combining(c))


def boardgame_evidence(project, story):
    """Require evidence from this campaign, never from creator bios or other projects."""
    title = normalized(project.get("title", ""))
    summary = normalized(project.get("summary", ""))
    if re.search(r"\brpg\b|late\s*pledge|pre[- ]?venda|\bsleeves?\b|\binserts?\b|\bplaymats?\b|\btaro\b|\btarot\b", title):
        return None
    if re.search(r"jogo (?:digital|eletronico)|videogame|jogo (?:para|de) pc|beat.?em.?up", title + " " + summary):
        return None
    soup = BeautifulSoup(story, "html.parser")
    for link in soup.select("a[href]"):
        url = urlparse(link["href"])
        if ((url.hostname in {"ludopedia.com.br", "www.ludopedia.com.br"} and url.path.startswith("/jogo/"))
                or (url.hostname in {"boardgamegeek.com", "www.boardgamegeek.com"} and url.path.startswith("/boardgame/"))):
            return link["href"]
    text = title + " " + summary + " " + normalized(soup.get_text(" ", strip=True))
    match = re.search(r"\b(?:board\s*games?|jogos? de tabuleiro|jogos? de cartas|card\s*games?)\b", text)
    return match[0] if match else None


def collect_catarse(html, now, fetch, qualify, image_url):
    listing = records_from_html(html)
    candidates = {}
    for record in listing.values():
        for item in objects(record):
            slug = item.get("slug", "")
            if (item.get("status") == "Launch" and item.get("categoryId") == 2
                    and re.fullmatch(r"[a-zA-Z0-9_-]+", slug) and "goalAmount" in item):
                candidates[slug] = item
    rows = []
    for slug, item in candidates.items():
        # Skip visibly unfunded campaigns before fetching details. Qualification
        # below uses fresh detail data, including unique contributors, not followers.
        if item.get("fundsCollected", 0) < item.get("goalAmount", 1):
            continue
        if re.search(r"\brpg\b|late\s*pledge", normalized(item.get("title", ""))):
            continue
        url = BASE + slug
        records = records_from_html(fetch(url))
        project = {}
        for record in records.values():
            for detail in objects(record):
                if detail.get("slug") == slug and "goalAmount" in detail:
                    project.update(detail)
        story = project.get("story", "")
        if isinstance(story, str) and story.startswith("$"):
            story = records.get(story[1:], "")
        if not isinstance(story, str):
            story = ""
        evidence = boardgame_evidence(project, story)
        if not evidence or project.get("isAdultContent") or project.get("status") != "Launch":
            continue
        pledged, goal = project.get("fundsCollected"), project.get("goalAmount")
        if any(type(v) is not int or v < 0 for v in (pledged, goal)):
            continue
        row = dict(id="catarse-" + slug, name=project.get("title", ""), url=url, source="Catarse",
                   source_url=url, kind="boardgame", region="BR", currency="BRL",
                   pledged=pledged / 100, goal=goal / 100, backers=project.get("contributorsCount", 0),
                   start_date=project.get("startDate"), end_date=project.get("endDate"), status="live",
                   description=project.get("summary", ""), tags=["boardgame"],
                   image=image_url(project.get("thumbnail", ""), url), image_source_url=url,
                   boardgame_evidence=evidence, verified_at=now.isoformat(), shipping_br="unknown")
        qualified = qualify(row, now=now, today=now.astimezone(timezone(timedelta(hours=-3))).date())
        if qualified:
            rows.append(qualified)
    return rows
