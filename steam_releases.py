"""Steam Brazil release calendar, preserving imprecise publisher dates verbatim.

python steam_releases.py --json data/releases.json
Public Steam search only, no review threshold for unreleased games.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests

SEARCH = "https://store.steampowered.com/search/results/"
TAG_URL = "https://store.steampowered.com/tagdata/populartags/english"
MONTHS = {name: index + 1 for index, name in enumerate([
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
SOURCES = {
    "scheduled": {"filter": "comingsoon", "sort_by": "Released_ASC"},
    "popularcomingsoon": {"filter": "popularcomingsoon", "sort_by": ""},
    "released": {"filter": "newreleases", "sort_by": "Released_DESC"},
}


def now_utc():
    return datetime.now(timezone.utc)


def parse_release_date(raw):
    """Never transform a month, quarter or year into an invented day."""
    raw = " ".join((raw or "").split())
    match = re.fullmatch(r"(\d{1,2}) ([A-Za-z]{3}),? (\d{4})", raw)
    if not match:
        us = re.fullmatch(r"([A-Za-z]{3}) (\d{1,2}),? (\d{4})", raw)
        if us:
            match = (None, us[2], us[1], us[3])
    if match and match[2] in MONTHS:
        try:
            value = date(int(match[3]), MONTHS[match[2]], int(match[1]))
            return dict(release_date=value.isoformat(), date_precision="day", release_period=value.strftime("%Y-%m"))
        except ValueError:
            pass
    month = re.fullmatch(r"([A-Za-z]{3,9}) (\d{4})", raw)
    if month and month[1][:3] in MONTHS:
        return dict(release_date=None, date_precision="month", release_period=f"{month[2]}-{MONTHS[month[1][:3]]:02}")
    quarter = re.fullmatch(r"Q([1-4]) (\d{4})", raw)
    if quarter:
        return dict(release_date=None, date_precision="quarter", release_period=f"{quarter[2]}-Q{quarter[1]}")
    if re.fullmatch(r"20\d{2}", raw):
        return dict(release_date=None, date_precision="year", release_period=raw)
    return dict(release_date=None, date_precision="unknown", release_period=None)


def parse_rows(html, status, tag_names=None, now=None, source_id=None):
    now = now or now_utc()
    tag_names = tag_names or {}
    source_id = source_id or status
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for row in soup.select("a.search_result_row"):
        appid = row.get("data-ds-appid", "")
        href = row.get("href", "")
        if not appid.isdigit() or row.get("data-ds-itemkey") != f"App_{appid}":
            continue
        parsed = urlparse(href)
        if parsed.hostname != "store.steampowered.com" or not parsed.path.startswith(f"/app/{appid}/"):
            continue
        try:
            tags = [str(x) for x in json.loads(row.get("data-ds-tagids", "[]"))]
            descriptors = [str(x) for x in json.loads(row.get("data-ds-content-descriptors", "[]"))]
        except (ValueError, TypeError):
            continue
        # Mature/violence tags alone are not excluded. Steam descriptor 3 is
        # Adult Only Sexual Content; 9130 is Hentai.
        if "9130" in tags or "3" in descriptors:
            continue
        title, released, image = (row.select_one(x) for x in (".title", ".search_released", ".search_capsule img"))
        if title is None or released is None:
            continue
        name = title.get_text(" ", strip=True)
        if re.search(r"\bhentai\b|\bporn(?:ographic)?\b", name, re.I):
            continue
        raw = released.get_text(" ", strip=True)
        precision = parse_release_date(raw)
        # New Releases can contain odd/unreleased store records. Do not label
        # them released based on an uncertain or future date.
        if status == "released" and (not precision["release_date"] or precision["release_date"] > now.date().isoformat()):
            continue
        source_url = ("https://store.steampowered.com/search/?category1=998&cc=br&l=english&filter="
                      + SOURCES[source_id]["filter"] + "&sort_by=" + SOURCES[source_id]["sort_by"])
        rows.append(dict(appid=int(appid), name=name, url=f"https://store.steampowered.com/app/{appid}/?cc=br",
                         image=image.get("src", "") if image else "", release_date_raw=raw,
                         **precision, status=status, source="Steam", source_id=source_id, source_url=source_url,
                         tags=[tag_names[t] for t in tags if t in tag_names], tag_ids=tags,
                         verified_at=now.isoformat(), valid_until=(now + timedelta(hours=30)).isoformat(),
                         stale=False, date_note="Data informada pelo desenvolvedor na Steam; pode mudar."))
    return rows


def collect(previous=None, now=None, fetch_json=None, max_pages=6, page_size=100):
    now = now or now_utc()
    previous = previous or {}
    max_pages = max(1, min(6, max_pages))
    page_size = max(1, min(100, page_size))
    def fetch(url, params=None):
        if fetch_json:
            return fetch_json(url, params)
        response = requests.get(url, params=params, timeout=(5, 20),
                                headers={"User-Agent": "GamePromo/2.0 (+https://gamepromo.runictools.com)"})
        response.raise_for_status()
        return response.json()
    tags = {}
    tag_status = "ok"
    try:
        tags = {str(x["tagid"]): x["name"] for x in fetch(TAG_URL)}
    except (requests.RequestException, ValueError, TypeError, KeyError):
        tag_status = "unavailable"
    def source_collect(status):
        items, seen = [], set()
        pages = 0
        source_status, error = "ok", None
        total = None
        try:
            for page in range(max_pages):
                params = dict(SOURCES[status], start=page * page_size, count=page_size, infinite=1,
                              category1=998, cc="br", l="english", excluded_tags="9130", excluded_content_descriptors="3")
                payload = fetch(SEARCH, params)
                if not payload.get("success") or not isinstance(payload.get("results_html"), str):
                    raise ValueError("Invalid Steam search response")
                total = payload.get("total_count", total)
                html = payload["results_html"]
                count = len(BeautifulSoup(html, "html.parser").select("a.search_result_row"))
                if count == 0 and page == 0 and (total is None or int(total) > 0):
                    raise ValueError("Missing Steam search rows")
                parsed = parse_rows(html, "released" if status == "released" else "scheduled", tags, now, source_id=status)
                pages += 1
                fresh = [x for x in parsed if x["appid"] not in seen]
                items.extend(fresh)
                seen.update(x["appid"] for x in fresh)
                if count < page_size or count == 0 or total is not None and (page + 1) * page_size >= int(total):
                    break
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            source_status = "partial" if pages else "unavailable"
            error = type(exc).__name__
            # Carry only the failed source's prior records and retain their
            # original verification dates. A failed fetch cannot freshen data.
            for item in previous.get("releases", []):
                if item.get("source_id", item.get("status")) == status and item.get("appid") not in seen:
                    items.append(dict(item, stale=True))
        if not tags:
            old = {x.get("appid"): x for x in previous.get("releases", [])}
            for item in items:
                if not item.get("tags") and item["appid"] in old:
                    item["tags"] = old[item["appid"]].get("tags", [])
        return items, dict(id=status, status=source_status, pages=pages, count=len(items), total_available=total,
                           max_pages=max_pages, error=error, checked_at=now.isoformat())
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(source_collect, SOURCES))
    # A fresh released record supersedes a coming-soon duplicate (store rollout).
    unique = {}
    for items, _ in results:
        for item in items:
            prior = unique.get(item["appid"])
            if not prior or prior.get("stale") or not item.get("stale") and item["status"] == "released":
                unique[item["appid"]] = item
    releases = sorted(unique.values(), key=lambda x: (x["release_date"] is None, x["release_date"] or x.get("release_period") or "9999", x["name"].casefold()))
    sources = [s for _, s in results]
    return dict(generated_at=now.isoformat(), valid_until=(now + timedelta(hours=30)).isoformat(), releases=releases,
                sources=sources, tag_status=tag_status, stale=any(s["status"] != "ok" for s in sources),
                status="ok" if all(s["status"] == "ok" for s in sources) else "partial" if releases else "unavailable",
                coverage={"country": "BR", "language": "english", "pages_per_source": max_pages, "page_size": page_size,
                          "count": len(releases), "exact_dates": sum(x["date_precision"] == "day" for x in releases),
                          "note": "Amostra de até 6 páginas por fonte: próximos lançamentos por data, próximos populares e lançamentos recentes. Não é todo o catálogo. Datas mensais/trimestrais/anuais não recebem dia inventado; datas são previsões da loja e podem mudar."})


def save(payload, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="data/releases.json")
    parser.add_argument("--max-pages", type=int, default=6)
    args = parser.parse_args()
    prior = {}
    try:
        prior = json.loads(Path(args.json).read_text(encoding="utf8"))
    except (OSError, ValueError):
        pass
    payload = collect(previous=prior, max_pages=args.max_pages)
    save(payload, args.json)
    print(json.dumps({"count": len(payload["releases"]), "status": payload["status"], "sources": payload["sources"]}))
