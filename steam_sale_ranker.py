#!/usr/bin/env python3
import io, sys
if sys.platform == "win32":
    for _s in ("stdout", "stderr"):
        _cur = getattr(sys, _s)
        if hasattr(_cur, "reconfigure"):
            _cur.reconfigure(encoding="utf-8", errors="replace")

"""
Game Promo Ranker
=================
Lista jogos em promoção na Steam ordenados por score composto.

Fórmula v2 (0–10): 10 × Wilson 95% × (0.60 + 0.40 × desconto) × fator histórico.
Fator histórico 0.90–1.00 após duas datas BRL; neutro (1) enquanto insuficiente.
Sem multiplicador de fama: tamanho da amostra entra apenas na confiança.
Mínimo de 100 avaliações; preços regionais BRL; baixa apenas observada no Brasil.

Blocos seguem a classificação oficial da Steam:
  Overwhelmingly Positive : 95%+  (500+ reviews)
  Very Positive           : 80-94% (500+ reviews)
  Mostly Positive         : 70-79%
  Mixed                   : 40-69%
  Mostly Negative         : 20-39%
  Overwhelmingly Negative : 0-19%  (500+ reviews)

Uso:
  python steam_sale_ranker.py                          # 10 páginas (~500 jogos)
  python steam_sale_ranker.py 20                       # 20 páginas (~1000 jogos)
  python steam_sale_ranker.py 20 --html                # gera steam_sale_ranker.html
  python steam_sale_ranker.py 20 --json data/games.json  # gera JSON p/ a app Flask
"""

import json
import math
import os
import re
import sys
import time
import threading as _threading
from email.utils import parsedate_to_datetime
from collections import defaultdict
from datetime import datetime, timezone


try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[!] Dependências necessárias:")
    print("    pip install requests beautifulsoup4")
    sys.exit(1)

# ─── Config ──────────────────────────────────────────────────────────────────

STEAM_SEARCH_URL = "https://store.steampowered.com/search/results/"
COUNT_PER_PAGE   = 50
MAX_PER_BLOCK    = 30   # máximo exibido por bloco no terminal
MIN_REVIEWS      = 100   # jogos com menos reviews são ignorados
MIN_DISCOUNT     = 15    # descontos abaixo disso são ignorados

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
        "Gecko/20100101 Firefox/124.0"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://store.steampowered.com/",
}
COOKIES = {
    "birthtime":           "631152001",
    "mature_content":      "1",
    "wants_mature_content": "1",
    "lastagecheckage":     "1-0-2000",
}

# ─── Blocos ──────────────────────────────────────────────────────────────────

BLOCK_ORDER = [
    "Overwhelmingly Positive",
    "Very Positive",
    "Mostly Positive",
    "Mixed",
    "Mostly Negative",
    "Overwhelmingly Negative",
    "Sem Avaliações",
]

BLOCK_COLORS = {
    "Overwhelmingly Positive": "\033[92m",   # verde brilhante
    "Very Positive":           "\033[32m",   # verde
    "Mostly Positive":         "\033[33m",   # amarelo
    "Mixed":                   "\033[93m",   # amarelo brilhante
    "Mostly Negative":         "\033[91m",   # vermelho brilhante
    "Overwhelmingly Negative": "\033[31m",   # vermelho
    "Sem Avaliações":          "\033[90m",   # cinza
}

BLOCK_HEX = {
    "Overwhelmingly Positive": "#4fc24f",
    "Very Positive":           "#66c0f4",
    "Mostly Positive":         "#a4d4a4",
    "Mixed":                   "#f5c518",
    "Mostly Negative":         "#f06c6c",
    "Overwhelmingly Negative": "#c0392b",
    "Sem Avaliações":          "#888",
}

RESET = "\033[0m"
BOLD  = "\033[1m"
GRAY  = "\033[90m"
CYAN  = "\033[96m"

# ─── Score e classificação ────────────────────────────────────────────────────

def quality_lower_bound(pct: float, total: int) -> float:
    """Wilson 95%: penaliza incerteza sem premiar fama duas vezes."""
    if total <= 0 or not math.isfinite(float(pct)):
        return 0.0
    p = max(0.0, min(float(pct), 100.0)) / 100
    n, z = float(total), 1.96
    return (p + z*z/(2*n) - z*math.sqrt((p*(1-p)+z*z/(4*n))/n))/(1+z*z/n)


def review_volume_factor(total: int) -> float:
    """Volume explícito, logarítmico e limitado: 100 mil reviews já saturam."""
    return 0.50 + 0.50 * min(1.0, math.log10(1 + max(0, total)) / 5)


def calc_score(pct: int, total: int, discount: int) -> float:
    """Qualidade conservadora × oportunidade; desconto não resgata qualidade ruim."""
    if total < MIN_REVIEWS:
        return 0.0
    return (10 * quality_lower_bound(pct, total)**2 * review_volume_factor(total)
            * (0.40 + 0.60 * max(0, min(discount, 100))/100))


# Tag Hentai e descritor 3 (Adult Only Sexual Content).
# Nudez (6650), violência e mature geral NÃO são excluídos.
EXPLICIT_TAG_IDS = {"9130"}
TAG_NAMES = {}
COLLECTION_COVERAGE = {"status": "not_run", "strategies": [], "complete_catalog": False}


def fetch_tag_names() -> dict:
    try:
        resp = requests.get("https://store.steampowered.com/tagdata/populartags/english",
                            params={"cc": "br"}, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return {str(t["tagid"]): t["name"] for t in data if t.get("tagid") and t.get("name")}
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return {}


def review_block(pct: int, total: int) -> str:
    """Classifica o jogo no bloco correto conforme o sistema Steam."""
    if total < 10:
        return "Sem Avaliações"
    if total >= 500:
        if pct >= 95: return "Overwhelmingly Positive"
        if pct >= 80: return "Very Positive"
        if pct < 20:  return "Overwhelmingly Negative"
    if pct >= 70: return "Mostly Positive"
    if pct >= 40: return "Mixed"
    return "Mostly Negative"

# ─── Coleta ───────────────────────────────────────────────────────────────────

SEARCH_INTERVAL = 3.0
SEARCH_RETRIES = 2
_search_lock = _threading.Lock()
_search_last_call = None


def _retry_delay(response, attempt):
    """Retry-After seconds or HTTP date; bounded 120s, fallback 30/60s."""
    raw = response.headers.get("Retry-After", "")
    try:
        delay = float(raw)
        if not math.isfinite(delay):
            raise ValueError("non-finite delay")
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(raw)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            delay = (date - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            delay = 30.0 * (attempt + 1)
    return max(0.0, min(120.0, delay))


def _search_get(params):
    """Shared pacing for all search strategies, including transient retries."""
    global _search_last_call
    for attempt in range(SEARCH_RETRIES + 1):
        with _search_lock:
            if _search_last_call is not None:
                gap = SEARCH_INTERVAL - (time.monotonic() - _search_last_call)
                if gap > 0:
                    time.sleep(gap)
            _search_last_call = time.monotonic()
        response = requests.get(STEAM_SEARCH_URL, params=params, headers=HEADERS,
                                cookies=COOKIES, timeout=20)
        if response.status_code not in (429, 503) or attempt == SEARCH_RETRIES:
            response.raise_for_status()
            return response
        time.sleep(_retry_delay(response, attempt))
    raise RuntimeError("Steam search retry exhausted")


def fetch_page(start: int, sort_by: str = "Reviews_DESC") -> tuple[list[dict], int]:
    """Busca uma página do search da Steam. Retorna (jogos_parsed, total_count)."""
    params = {
        "specials": 1,
        "cc": "br", "l": "english", "category1": 998,
        "ignore_preferences": 1,
        "excluded_tags": ",".join(sorted(EXPLICIT_TAG_IDS)),
        "excluded_content_descriptors": "3",
        "json":     1,
        "count":    COUNT_PER_PAGE,
        "start":    start,
        "infinite": 1,
    }
    if sort_by:
        params["sort_by"] = sort_by
    resp = _search_get(params)
    data = resp.json()

    total = int(data.get("total_count", 0))

    # A Steam retorna HTML no items_html ou results_html
    raw_html = (
        data.get("items_html")
        or data.get("results_html")
        or ""
    )
    if not raw_html:
        # Fallback: items como lista de strings
        items = data.get("items", [])
        if isinstance(items, list):
            raw_html = "\n".join(str(x) for x in items)

    if total > start and not raw_html.strip():
        raise ValueError("Steam returned missing search HTML")
    soup  = BeautifulSoup(raw_html, "html.parser")
    rows  = soup.find_all("a", class_="search_result_row")
    games = [g for r in rows if (g := _parse_row(r)) is not None]
    return games, total


def _parse_row(row) -> dict | None:
    """Extrai metadados de um search_result_row."""
    try:
        # ── Nome ──────────────────────────────────────────────────────────
        name_tag = row.find("span", class_="title")
        name = name_tag.get_text(strip=True) if name_tag else "?"

        appid = row.get("data-ds-appid", "").split(",")[0]
        if not appid.isdigit() or not re.search(r"/app/" + appid + r"(?:/|$)", row.get("href", "")):
            return None
        tag_ids = [str(t) for t in json.loads(row.get("data-ds-tagids") or "[]")]
        if EXPLICIT_TAG_IDS.intersection(tag_ids) or "3" in {str(d) for d in json.loads(row.get("data-ds-content-descriptors") or "[]")}:
            return None

        # ── Desconto ──────────────────────────────────────────────────────
        discount = 0

        # Tentativa 1: atributo data-ds-discount
        if row.get("data-ds-discount"):
            try:
                discount = int(row["data-ds-discount"])
            except ValueError:
                pass

        # Tentativa 2: div.search_discount > span
        if discount == 0:
            disc_tag = row.find("div", class_="search_discount")
            if disc_tag:
                m = re.search(r"(\d+)%", disc_tag.get_text())
                if m:
                    discount = int(m.group(1))

        # Tentativa 3: div.discount_pct
        if discount == 0:
            disc_tag = row.find("div", class_="discount_pct")
            if disc_tag:
                m = re.search(r"(\d+)", disc_tag.get_text())
                if m:
                    discount = int(m.group(1))

        if discount < MIN_DISCOUNT:
            return None

        # ── Preços ────────────────────────────────────────────────────────
        orig_price = ""
        sale_price = ""

        orig_tag = row.find(class_="discount_original_price")
        sale_tag = row.find(class_="discount_final_price")
        if orig_tag:
            orig_price = orig_tag.get_text(strip=True)
        if sale_tag:
            sale_price = sale_tag.get_text(strip=True)

        # Fallback: search_price genérico
        if not sale_price:
            price_block = row.find("div", class_="search_price")
            if price_block:
                strike = price_block.find("strike")
                if strike:
                    orig_price = strike.get_text(strip=True)
                texts = [t.strip() for t in price_block.get_text("\n").split("\n") if t.strip()]
                if texts:
                    sale_price = texts[-1]

        if not sale_price.startswith("R$"):
            return None

        # ── Reviews ───────────────────────────────────────────────────────
        pct_positive  = 0
        total_reviews = 0

        review_span = row.find("span", class_="search_review_summary")
        if review_span:
            tooltip = review_span.get("data-tooltip-html", "")
            # "94% of 28,521 user reviews for this game are positive."
            # "94% das 28.521 análises dos usuários recomendam este jogo."
            m_pct = re.search(r"(\d+)%", tooltip)
            m_tot = re.search(
                r"([\d,\.]+)\s*(user reviews|análises|reviews)",
                tooltip, re.IGNORECASE
            )
            if m_pct:
                pct_positive = int(m_pct.group(1))
            if m_tot:
                total_reviews = int(re.sub(r"[,\.]", "", m_tot.group(1)))

        if total_reviews < MIN_REVIEWS:
            return None

        # ── Imagem ────────────────────────────────────────────────────────
        img_url = ""
        img_tag = row.find("div", class_="search_capsule")
        if img_tag:
            img_el = img_tag.find("img")
            if img_el:
                img_url = img_el.get("src", "")
        if not img_url and appid:
            img_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/capsule_231x87.jpg"

        # Capa larga (460x215) para a visão em cards do frontend.
        header_img = (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"
                      if appid else "")

        return {
            "tag_ids": tag_ids,
            "tags": [TAG_NAMES[t] for t in tag_ids if t in TAG_NAMES],
            "genres": [], "categories": [], "currency": "BRL", "country": "BR",
            "quality_score": round(10 * quality_lower_bound(pct_positive, total_reviews), 3),
            "confidence": "high" if total_reviews >= 1000 else "moderate",
            "score_version": 3,
            "name":          name,
            "appid":         appid,
            "discount":      discount,
            "pct_positive":  pct_positive,
            "total_reviews": total_reviews,
            "orig_price":    orig_price,
            "sale_price":    sale_price,
            "score":         calc_score(pct_positive, total_reviews, discount),
            "block":         review_block(pct_positive, total_reviews),
            "url":           row.get("href", f"https://store.steampowered.com/app/{appid}/"),
            "img_url":       img_url,
            "header_img":    header_img,
        }
    except Exception:
        return None

# ─── Coleta com paginação ─────────────────────────────────────────────────────

# Duas passagens para cobrir jogos diferentes:
# Reviews_DESC → jogos populares (muitos reviews, desconto variado)
# sem sort     → relevância Steam para promoções (tende a priorizar descontos maiores)
FETCH_STRATEGIES = ["Reviews_DESC", "Discount_DESC", "Released_DESC", ""]

def _fetch_strategy(sort_by: str, max_pages: int, label: str) -> tuple[list[dict], int]:
    games: list[dict] = []
    total_available = 0
    report = {"sort": sort_by or "relevance", "pages_scanned": 0, "pages_requested": max_pages,
              "eligible": 0, "total_available": 0, "status": "bounded"}
    COLLECTION_COVERAGE["strategies"].append(report)
    for page in range(max_pages):
        start = page * COUNT_PER_PAGE
        print(f"\r  {label} [{page + 1}/{max_pages}] offset={start}...", end="", flush=True)
        try:
            batch, total = fetch_page(start, sort_by=sort_by)
            total_available = total
            report.update(pages_scanned=page+1, total_available=total)
            report["eligible"] += len(batch)
            games.extend(batch)
            if start + COUNT_PER_PAGE >= total:
                report["status"] = "exhausted"
                break
        except requests.HTTPError as e:
            report["status"] = "failed"
            raise RuntimeError("Steam collection failed; previous output must be retained") from e
        except Exception as e:
            report["status"] = "failed"
            raise RuntimeError("Steam collection failed; previous output must be retained") from e
    return games, total_available


def collect_all(max_pages: int) -> list[dict]:
    max_pages = max(1, min(20, max_pages))
    COLLECTION_COVERAGE.update(status="running", strategies=[], complete_catalog=False)
    TAG_NAMES.update(fetch_tag_names())
    seen:      set[str]   = set()
    all_games: list[dict] = []
    total_available = 0

    for i, sort_by in enumerate(FETCH_STRATEGIES):
        label = f"[pass {i+1}/{len(FETCH_STRATEGIES)} {'reviews' if sort_by else 'relevância'}]"
        batch, total = _fetch_strategy(sort_by, max_pages, label)
        total_available = max(total_available, total)
        new = 0
        for g in batch:
            if g["appid"] not in seen:
                seen.add(g["appid"])
                all_games.append(g)
                new += 1
        print(f"\r  pass {i+1}: +{new} novos (total único: {len(all_games)})          ")

    COLLECTION_COVERAGE.update(status="bounded_sample", unique_games=len(all_games),
                               total_available=total_available,
                               pages_scanned=sum(x["pages_scanned"] for x in COLLECTION_COVERAGE["strategies"]))
    print(f"  Total disponível na Steam: ~{total_available} jogos em promoção")
    return all_games


# ─── Histórico regional observado (BRL) ─────────────────────────────────────


def _parse_brl(price_str: str) -> float:
    """Extrai valor numérico de 'R$ 9,99' ou 'R$9.99'. Retorna 0.0 se falhar."""
    try:
        s = re.sub(r"[R$\s]", "", price_str)   # remove R$, espaços
        s = s.replace(".", "").replace(",", ".") if "," in s else s  # "9.999,99" → "9999.99"
        return float(s)
    except Exception:
        return 0.0


def _fmt_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# Série v2 exclui cache legado sem região e preços sintéticos derivados de USD.
HIST_CACHE_NAME = "observed_lows_br_app_v2.json"


def _load_low_cache(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_low_cache(path: str, cache: dict) -> None:
    try:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        pass


def update_score_details(game: dict, proximity: float | None = None) -> None:
    """Desconto + distância ao menor BRL observado, nunca uma mínima global inventada."""
    quality = quality_lower_bound(game.get("pct_positive", 0), game.get("total_reviews", 0))
    discount = max(0, min(game.get("discount", 0), 100)) / 100
    history_factor = 1.0 if proximity is None else 0.90 + 0.10 * max(0, min(proximity, 1))
    deal = (0.40 + 0.60 * discount) * history_factor
    volume = review_volume_factor(game.get("total_reviews", 0))
    game.update(quality_score=round(quality * 10, 3), deal_score=round(deal * 10, 3), score_version=3,
                score=calc_score(game.get("pct_positive", 0), game.get("total_reviews", 0), game.get("discount", 0)) * history_factor,
                hidden_gem=bool(MIN_REVIEWS <= game.get("total_reviews", 0) < 5000 and quality >= 0.85),
                score_components={"wilson_lower_bound": round(quality, 6), "discount_fraction": discount,
                                  "review_volume_factor": volume, "quality_exponent": 2,
                                  "observed_price_proximity": proximity, "history_factor": history_factor},
                score_rationale="Qualidade Wilson ao quadrado × desconto × volume logarítmico de reviews (limitado em 100 mil). "
                    + ("Histórico BR insuficiente: efeito neutro." if proximity is None else
                       "Oportunidade ajustada pela distância ao menor BRL observado em pelo menos duas datas."))


def apply_low_cache(games: list[dict], cache_path: str) -> None:
    """Menor preço OBSERVADO BRL. USD ou antigos valores sintéticos são inválidos."""
    cache = _load_low_cache(cache_path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for g in games:
        appid = g["appid"]
        cur = _parse_brl(g.get("sale_price", ""))
        ent = cache.get(appid) or {}
        if ent.get("src") != "obs" or ent.get("currency") != "BRL":
            ent = {}
        g.update(historical_low=False, observed_low=False, stores=[], low_src="obs",
                 low_price_brl="", low_observed_since="")
        if cur <= 0:
            update_score_details(g)
            continue
        if not ent:
            ent = {"low_brl": cur, "src": "obs", "currency": "BRL", "country": "BR",
                   "first_seen": now, "beaten": False}
        elif cur < float(ent.get("low_brl") or cur) - 0.005:
            ent.update(low_brl=cur, beaten=True)
        dates = sorted(set(ent.get("observed_dates", []) + [now[:10]]))
        ent.update(low_str=_fmt_brl(ent["low_brl"]), updated=now, observed_dates=dates[-90:])
        cache[appid] = ent
        update_score_details(g, min(1.0, ent["low_brl"] / cur) if len(dates) >= 2 else None)
        g.update(low_price_brl=ent["low_str"], low_observed_since=ent["first_seen"],
                 observed_low=bool(ent.get("beaten") and cur <= ent["low_brl"] + 0.005))
    _save_low_cache(cache_path, cache)


def seed_low_cache(games: list[dict], cache_path: str) -> None:
    """Compatibilidade: CheapShark USD não comprova mínima regional Steam BRL."""
    return None

# ─── Metadados: gênero / tags / Steam Deck (Steam appdetails) ─────────────────
# Enriquece cada jogo com gêneros, algumas tags de jogabilidade e a compatibilidade
# com o Steam Deck. Como o appdetails é bem rate-limited, semeamos um LOTE pequeno
# por execução; TTL de 30 dias, tentativas antigas têm prioridade na fila.
META_CACHE_NAME = "meta_cache.json"
META_BATCH      = 80
META_INTERVAL   = 1.5          # ~40 req/min — gentil com o appdetails da Steam

# resolved_category do relatório de Deck → rótulo do frontend.
_DECK_MAP = {0: "unknown", 1: "unsupported", 2: "playable", 3: "verified"}

_meta_lock    = _threading.Lock()
_meta_last    = [0.0]
_meta_blocked = [False]
_meta_streak  = [0]


def _steam_get(url: str, params: dict):
    """GET a um endpoint da store da Steam com rate limit + circuit breaker (429)."""
    if _meta_blocked[0]:
        return None
    with _meta_lock:
        gap = META_INTERVAL - (time.time() - _meta_last[0])
        if gap > 0:
            time.sleep(gap)
        _meta_last[0] = time.time()
    try:
        r = requests.get(url, params=params, headers=HEADERS, cookies=COOKIES, timeout=15)
        if r.status_code == 429:
            _meta_streak[0] += 1
            if _meta_streak[0] >= 5:
                _meta_blocked[0] = True
            return None
        if r.status_code == 200:
            _meta_streak[0] = 0
            return r.json()
        return None
    except Exception:
        return None


def _fetch_meta_one(appid: str) -> dict | None:
    """Busca gêneros/tags (appdetails) + Deck (relatório de compat). None se falhar."""
    d = _steam_get("https://store.steampowered.com/api/appdetails",
                   {"appids": appid, "cc": "br", "l": "brazilian"})
    node = (d or {}).get(str(appid)) if isinstance(d, dict) else None
    if not node or not node.get("success"):
        return None
    data = node.get("data") or {}
    genres = [g.get("description") for g in (data.get("genres") or []) if g.get("description")]
    cats   = [c.get("description") for c in (data.get("categories") or []) if c.get("description")]
    deck = "unknown"
    dj = _steam_get("https://store.steampowered.com/saleaction/ajaxgetdeckappcompatibilityreport",
                    {"nAppID": appid, "l": "english"})
    if isinstance(dj, dict):
        cat = (dj.get("results") or {}).get("resolved_category")
        if isinstance(cat, int):
            deck = _DECK_MAP.get(cat, "unknown")
    return {"genres": genres, "tags": [], "categories": cats, "deck": deck, "schema_version": 2,
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def _meta_fresh(ent: dict) -> bool:
    if not isinstance(ent, dict) or ent.get("schema_version") != 2:
        return False
    try:
        updated = datetime.fromisoformat(ent["updated"])
        return updated.tzinfo is not None and 0 <= (datetime.now(timezone.utc)-updated).total_seconds() < 30*86400
    except (KeyError, TypeError, ValueError):
        return False


def apply_meta_cache(games: list[dict], cache_path: str) -> None:
    """Aplica o cache de metadados a TODOS os jogos (sem rede)."""
    cache = _load_low_cache(cache_path)   # mesmo helper de I/O de JSON
    for g in games:
        ent = cache.get(g.get("appid", ""))
        g["metadata_status"] = "missing"
        if isinstance(ent, dict) and ent.get("schema_version") == 2:
            g["metadata_status"] = "verified" if _meta_fresh(ent) else "stale"
            g["genres"] = ent.get("genres") or []
            g["categories"] = ent.get("categories") or []
            g["deck"]   = ent.get("deck") or "unknown"


def seed_meta_cache(games: list[dict], cache_path: str) -> None:
    """Semeia metadados p/ os jogos ainda não cacheados (lote pequeno, resumível)."""
    cache = _load_low_cache(cache_path)
    needs = [g for g in games if g.get("appid") and not _meta_fresh(cache.get(g["appid"], {}))]
    needs.sort(key=lambda g: cache.get(g["appid"], {}).get("last_attempt", ""))
    if not needs:
        print("  Metadados: cache cobre todos os jogos (0 chamadas externas).")
        return
    total = len(needs)
    needs = needs[:META_BATCH]
    print(f"  Metadados: buscando {len(needs)}/{total} jogos (gênero/tags/Deck; "
          f"lote diário, o resto vem depois)...")
    done = 0
    for g in needs:
        if _meta_blocked[0]:
            print("\n  [!] appdetails limitou o IP — para o lote (continua amanhã).")
            break
        meta = _fetch_meta_one(g["appid"])
        if meta:
            cache[g["appid"]] = meta
        cache.setdefault(g["appid"], {})["last_attempt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _save_low_cache(cache_path, cache)   # grava na hora → resumível
        done += 1
        print(f"\r  appdetails: {done}/{len(needs)}...", end="", flush=True)
    print()


# ─── Histórico de preço (série diária, acumulada) ─────────────────────────────
# Sem fonte pública de histórico Steam sem API key; então acumulamos 1 ponto/dia
# (o preço promocional observado) em price_series.json. A sparkline enche com o
# tempo — honesto, no mesmo espírito da baixa "observada".
PRICE_SERIES_NAME = "price_series_br_app_v2.json"
PRICE_SERIES_MAX  = 365


def record_price_history(games: list[dict], path: str) -> None:
    """Anexa o ponto de hoje (preço promo) por jogo e expõe g['price_history']."""
    series = _load_low_cache(path)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dirty = False
    for g in games:
        appid = g.get("appid", "")
        p = _parse_brl(g.get("sale_price", ""))
        if not appid or p <= 0:
            continue
        pts = series.get(appid)
        if not isinstance(pts, list):
            pts = []
        if pts and pts[-1].get("d") == today:
            if abs(float(pts[-1].get("p", 0)) - p) > 0.005:
                pts[-1]["p"] = round(p, 2)
                dirty = True
        else:
            pts.append({"d": today, "p": round(p, 2)})
            dirty = True
        if len(pts) > PRICE_SERIES_MAX:
            pts = pts[-PRICE_SERIES_MAX:]
            dirty = True
        series[appid] = pts
        g["price_history"] = pts
    if dirty:
        _save_low_cache(path, series)


def apply_price_history(games: list[dict], path: str) -> None:
    """Anexa a série já existente aos jogos (sem gravar) — usado na fase 1."""
    series = _load_low_cache(path)
    for g in games:
        pts = series.get(g.get("appid", ""))
        if isinstance(pts, list):
            g["price_history"] = pts


# ─── Output terminal ──────────────────────────────────────────────────────────

def fmt_num(n: int) -> str:
    if n >= 1_000_000: return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:     return f"{n / 1_000:.0f}k"
    return str(n)


def print_results(by_block: dict[str, list[dict]], total_collected: int):
    W = 75

    print(f"\n{BOLD}{CYAN}{'═' * W}")
    print(f"  GAME PROMO RANKER  —  {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"  Score 0-10 = qualidade(Wilson 95%) × (0.60 + 0.40 × desconto)")
    print(f"  Quanto maior, melhor a relação qualidade conservadora + desconto")
    print(f"{'═' * W}{RESET}\n")

    total_shown = 0
    for block_name in BLOCK_ORDER:
        games = sorted(by_block.get(block_name, []), key=lambda g: g.get("score", 0), reverse=True)
        if not games:
            continue

        color = BLOCK_COLORS[block_name]
        print(f"\n{color}{BOLD}{'═' * W}")
        print(f"  {block_name.upper()}  ({len(games)} jogos encontrados)")
        print(f"{'═' * W}{RESET}")

        print(
            f"{GRAY}{'#':>3}  {'Nome':<39} {'Desc':>5}  "
            f"{'Rev%':>4}  {'Reviews':>7}  {'Low Ever (BRL)':>14}  {'Score':>6}{RESET}"
        )
        print(f"{GRAY}{'─' * W}{RESET}")

        top = games[:MAX_PER_BLOCK]
        for i, g in enumerate(top, 1):
            is_low   = g.get("historical_low", False)
            row_col   = "\033[92m" if is_low else ""
            low_tag   = f" {BOLD}\033[92m★{RESET}" if is_low else ""
            low_brl   = g.get("low_price_brl", "")
            low_col   = "\033[92m" if is_low else "\033[90m"
            low_str   = f"{low_col}{low_brl if low_brl else '—':>12}{RESET}"
            disc_str  = f"{color}-{g['discount']}%{RESET}"
            name_str  = g["name"][:38].ljust(38)
            print(
                f"{row_col}{i:>3}  {name_str}{low_tag} "
                f"{disc_str}  "
                f"{g['pct_positive']:>3}%  "
                f"{fmt_num(g['total_reviews']):>7}  "
                f"{low_str}  "
                f"{g['score']:>6.2f}{RESET}"
            )
            total_shown += 1

        extra = len(games) - MAX_PER_BLOCK
        if extra > 0:
            print(f"{GRAY}  ... +{extra} jogos omitidos (use --html para ver todos){RESET}")

    omitted = total_collected - total_shown
    print(f"\n{BOLD}Exibidos: {total_shown}  |  Total coletado: {total_collected}{RESET}")
    if omitted > 0:
        print(f"{GRAY}Use --html para relatório completo.{RESET}")

# ─── Output HTML ──────────────────────────────────────────────────────────────

def generate_html(by_block: dict[str, list[dict]], total_collected: int) -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    rows_by_block = ""
    for block_name in BLOCK_ORDER:
        games = sorted(by_block.get(block_name, []), key=lambda g: g.get("score", 0), reverse=True)
        if not games:
            continue
        hex_color = BLOCK_HEX[block_name]
        rows_html = ""
        for i, g in enumerate(games, 1):
            store_url = g.get("url", f"https://store.steampowered.com/app/{g['appid']}/")
            img_url   = g.get("img_url", "")
            img_html  = (
                f'<img src="{img_url}" alt="" loading="lazy">'
                if img_url else ""
            )
            is_low   = g.get("historical_low", False)
            is_new   = g.get("is_new", False)
            _cls     = (["new-row"] if is_new else []) + (["hist-low"] if is_low else [])
            tr_class = (' class="' + " ".join(_cls) + '"') if _cls else ""
            low_badge = (('<span class="new-badge">NEW</span>' if is_new else "")
                         + ('<span class="low-badge">BAIXA HISTÓRICA</span>' if is_low else ""))
            rows_html += f"""
              <tr{tr_class}>
                <td class="rank">{i}</td>
                <td class="name">
                  <a href="{store_url}" target="_blank">
                    {img_html}
                    <span>{g['name']}{low_badge}</span>
                  </a>
                </td>
                <td class="disc" style="color:{hex_color}">-{g['discount']}%</td>
                <td class="pct">{g['pct_positive']}%</td>
                <td class="reviews">{fmt_num(g['total_reviews'])}</td>
                <td class="orig">{g['orig_price']}</td>
                <td class="sale">{g['sale_price']}</td>
                <td class="low-ever">{g.get('low_price_brl') or '—'}</td>
                <td class="score">{g['score']:.2f}</td>
              </tr>"""

        rows_by_block += f"""
        <div class="block">
          <div class="block-header" style="background:{hex_color}">
            <span class="block-name">{block_name}</span>
            <span class="block-count">{len(games)} jogos</span>
          </div>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Nome</th>
                <th>Desconto</th>
                <th>Review%</th>
                <th>Reviews</th>
                <th>Preço Original</th>
                <th>Preço Promo</th>
                <th>Low Ever (BRL)</th>
                <th>Score ▼</th>
              </tr>
            </thead>
            <tbody>{rows_html}
            </tbody>
          </table>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Game Promo Ranker</title>
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: "Segoe UI", sans-serif;
      background: #1b2838;
      color: #c6d4df;
      padding: 20px;
    }}
    h1 {{
      color: #66c0f4;
      font-size: 1.6rem;
      margin-bottom: 6px;
    }}
    .subtitle {{
      color: #8f98a0;
      font-size: 0.85rem;
      margin-bottom: 24px;
    }}
    .formula {{
      background: #16202d;
      border-left: 3px solid #66c0f4;
      padding: 8px 14px;
      border-radius: 4px;
      font-family: monospace;
      font-size: 0.9rem;
      color: #c7d5e0;
      margin-bottom: 28px;
      display: inline-block;
    }}
    .block {{
      margin-bottom: 32px;
      border-radius: 6px;
      overflow: hidden;
      box-shadow: 0 2px 8px rgba(0,0,0,0.4);
    }}
    .block-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 16px;
      color: #fff;
    }}
    .block-name {{ font-weight: 700; font-size: 1rem; }}
    .block-count {{ font-size: 0.82rem; opacity: 0.85; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #16202d;
      font-size: 0.83rem;
    }}
    thead th {{
      background: #0e1822;
      padding: 7px 10px;
      text-align: left;
      color: #8f98a0;
      font-weight: 600;
      white-space: nowrap;
    }}
    tbody tr:nth-child(even) {{ background: #1a2535; }}
    tbody tr:hover {{ background: #2a3f5a; }}
    td {{ padding: 5px 10px; vertical-align: middle; }}
    td.rank  {{ color: #8f98a0; width: 36px; text-align: right; }}
    td.name  {{ min-width: 260px; }}
    td.name a {{
      display: flex;
      align-items: center;
      gap: 10px;
      color: #c6d4df;
      text-decoration: none;
    }}
    td.name a:hover span {{ color: #66c0f4; text-decoration: underline; }}
    td.name img {{
      width: 116px;
      height: 43px;
      object-fit: cover;
      border-radius: 3px;
      flex-shrink: 0;
      background: #0e1822;
    }}
    td.name span {{
      font-size: 0.84rem;
      line-height: 1.3;
    }}
    td.disc  {{ font-weight: 700; width: 70px; white-space: nowrap; }}
    td.pct   {{ width: 55px; white-space: nowrap; }}
    td.reviews {{ width: 75px; color: #8f98a0; white-space: nowrap; }}
    td.orig  {{ width: 105px; color: #8f98a0; text-decoration: line-through; white-space: nowrap; }}
    td.sale      {{ width: 105px; font-weight: 600; color: #beee11; white-space: nowrap; }}
    td.low-ever  {{ width: 90px; font-family: monospace; color: #8f98a0; white-space: nowrap; font-size: 0.8rem; }}
    tr.hist-low td.low-ever {{ color: #ffd24a; font-weight: 700; }}
    td.score {{ width: 65px; font-family: monospace; color: #66c0f4; white-space: nowrap; }}
    /* baixa histórica = AMARELO */
    tr.hist-low {{ background: #332b14 !important; border-left: 3px solid #ffce4a; }}
    tr.hist-low:hover {{ background: #403418 !important; }}
    /* novidade (entrou em promoção hoje) = VERDE — vence o amarelo se ambos */
    tr.new-row {{ background: #14331c !important; border-left: 3px solid #4fd06a; }}
    tr.new-row:hover {{ background: #1a4024 !important; }}
    tr.new-row.hist-low {{ border-left: 3px solid #4fd06a; }}
    .low-badge, .new-badge {{
      display: inline-block;
      margin-left: 7px;
      padding: 1px 5px;
      border-radius: 3px;
      font-size: 0.68rem;
      font-weight: 700;
      vertical-align: middle;
      letter-spacing: 0.03em;
    }}
    .low-badge {{ background: #ffce4a; color: #1a1400; }}
    .new-badge {{ background: #4fd06a; color: #04210b; }}
    .legend {{
      display: flex; flex-wrap: wrap; gap: 18px;
      margin: 0 0 18px; padding: 10px 14px;
      background: #16202d; border: 1px solid #2a3f57; border-radius: 8px;
      font-size: 0.82rem; color: #c7d5e0;
    }}
    .legend .sw {{ display: inline-block; width: 13px; height: 13px; border-radius: 3px; margin-right: 6px; vertical-align: -2px; }}
    .legend .sw.new {{ background: #4fd06a; }}
    .legend .sw.hist {{ background: #ffce4a; }}
    footer {{
      margin-top: 30px;
      color: #8f98a0;
      font-size: 0.78rem;
    }}
  </style>
</head>
<body>
  <h1>Game Promo Ranker</h1>
  <div class="subtitle">Gerado em {now}  —  {total_collected} jogos coletados</div>
  <div class="formula">
    score 0–10 = 10 × Wilson95² × volume de reviews × (0.40 + 0.60 × desconto) × histórico
  </div>
  <div class="legend">
    <span><span class="sw new"></span> <b>NEW</b> — entrou em promoção hoje (vs. ontem)</span>
    <span><span class="sw hist"></span> <b>Menor observado BRL</b> — limitado ao período acompanhado</span>
  </div>
  {rows_by_block}
  <footer>
    Fórmula: Wilson 95% × (0.60 + 0.40 × desconto); sem bônus de fama.<br>
    O desconto pesa 50% do seu valor real para não suplantar qualidade e popularidade.
  </footer>
</body>
</html>"""


def save_html(html: str, path: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[✓] HTML salvo em: {path}")

# ─── Output JSON (consumido pela app Flask) ───────────────────────────────────

# Campos de cada jogo expostos no JSON (mesma ordem/nomes do dict interno).
JSON_GAME_FIELDS = [
    "appid", "name", "discount", "orig_price", "sale_price",
    "pct_positive", "total_reviews", "score", "block",
    "historical_low", "low_price_brl", "is_new", "img_url", "url",
    # enriquecidos (v2): capa larga, gênero/tags, Steam Deck, multi-loja, histórico
    "header_img", "genres", "tags", "deck", "stores", "price_history",
    "categories", "tag_ids", "currency", "country", "quality_score", "confidence",
    "score_version", "observed_low", "low_observed_since",
    "deal_score", "score_components", "score_rationale", "hidden_gem", "metadata_status",
]


def build_json_payload(by_block: dict[str, list[dict]], total_collected: int) -> dict:
    """
    Monta o payload JSON consumido pelo frontend.

    Estrutura:
      {
        "generated_at": "2026-06-29T14:30:00",        # ISO 8601 (local)
        "generated_at_human": "29/06/2026 14:30",
        "total_collected": 512,
        "block_order": [...],                          # ordem canônica dos blocos
        "block_colors": {block: "#hex"},               # cores p/ headers/legenda
        "blocks": [
          {"name": "Very Positive", "color": "#66c0f4", "count": 30, "games": [ {<campos>}... ]},
          ...
        ]
      }

    Jogos de cada bloco já vêm ordenados por score desc (feito em main()).
    """
    now = datetime.now(timezone.utc)
    blocks = []
    for block_name in BLOCK_ORDER:
        games = sorted(by_block.get(block_name, []), key=lambda g: g.get("score", 0), reverse=True)
        if not games:
            continue
        serialized = []
        for g in games:
            row = {k: g.get(k) for k in JSON_GAME_FIELDS}
            # normaliza tipos pra JSON limpo
            row["discount"]      = int(g.get("discount") or 0)
            row["pct_positive"]  = int(g.get("pct_positive") or 0)
            row["total_reviews"] = int(g.get("total_reviews") or 0)
            row["score"]         = round(float(g.get("score") or 0.0), 4)
            row["historical_low"] = bool(g.get("historical_low", False))
            row["is_new"]         = bool(g.get("is_new", False))
            row["low_price_brl"]  = g.get("low_price_brl") or ""
            row["low_src"]        = g.get("low_src") or ""   # "obs"=menor observado Steam BRL
            row["reviews_human"]  = fmt_num(int(g.get("total_reviews") or 0))
            # enriquecidos: garante defaults limpos (listas/strings) p/ o frontend
            row["header_img"]     = g.get("header_img") or ""
            row["genres"]         = g.get("genres") or []
            row["tags"]           = g.get("tags") or []
            row["deck"]           = g.get("deck") or ""
            row["stores"]         = g.get("stores") or []
            row["price_history"]  = g.get("price_history") or []
            serialized.append(row)
        blocks.append({
            "name":  block_name,
            "color": BLOCK_HEX.get(block_name, "#888"),
            "count": len(serialized),
            "games": serialized,
        })

    return {
        "coverage": dict(COLLECTION_COVERAGE, metadata_verified=sum(
            1 for block in blocks for g in block["games"] if g.get("metadata_status") == "verified"),
            tags_resolved=sum(1 for block in blocks for g in block["games"] if g.get("tags"))),
        "generated_at":       now.isoformat(timespec="seconds"),
        "generated_at_human": now.strftime("%d/%m/%Y %H:%M"),
        "total_collected":    total_collected,
        "block_order":        BLOCK_ORDER,
        "block_colors":       BLOCK_HEX,
        "blocks":             blocks,
    }


def save_json(by_block: dict[str, list[dict]], total_collected: int, path: str):
    """Escreve o payload JSON em `path` (cria o diretório-pai se preciso)."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = build_json_payload(by_block, total_collected)
    # escreve atomicamente: grava em .tmp e renomeia (evita o Flask ler arquivo parcial)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    print(f"\n[✓] JSON salvo em: {path}")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    args       = sys.argv[1:]
    max_pages  = 20
    output_html = "--html" in args
    out_path = "steam_sale_ranker.html"
    if "--out" in args:
        _i = args.index("--out")
        if _i + 1 < len(args):
            out_path = args[_i + 1]

    # --json <PATH>: escreve a lista de jogos (agrupada por block) como JSON.
    # É o que a app Flask serve; o cron passa a usar este modo.
    json_path = None
    if "--json" in args:
        _i = args.index("--json")
        if _i + 1 < len(args):
            json_path = args[_i + 1]
        else:
            print("[!] --json requer um caminho: --json data/games.json")
            sys.exit(1)

    # estado de NEW: guarda os appids ao lado do output principal (JSON tem prioridade)
    _state_anchor = json_path or out_path
    state_path = os.path.join(os.path.dirname(_state_anchor) or ".", "_prev_appids.json")
    hist_cache_path = os.path.join(os.path.dirname(_state_anchor) or ".", HIST_CACHE_NAME)
    meta_cache_path = os.path.join(os.path.dirname(_state_anchor) or ".", META_CACHE_NAME)
    price_series_path = os.path.join(os.path.dirname(_state_anchor) or ".", PRICE_SERIES_NAME)

    numeric = [a for a in args if a.isdigit()]
    if numeric:
        max_pages = max(1, min(20, int(numeric[0])))

    print(f"\n{BOLD}Game Promo Ranker{RESET}")
    print(f"Buscando até {max_pages * COUNT_PER_PAGE} jogos em promoção...\n")

    all_games = collect_all(max_pages)

    if not all_games:
        print("\n[!] Nenhum jogo encontrado; snapshot anterior preservado.")
        COLLECTION_COVERAGE["status"] = "failed"
        sys.exit(1)

    # Deduplicar por appid
    seen: set[str] = set()
    unique: list[dict] = []
    for g in all_games:
        if g["appid"] not in seen:
            seen.add(g["appid"])
            unique.append(g)

    # NEW: jogos que NÃO estavam na geração anterior (ontem) = novidade de hoje.
    prev_appids: set = set()
    try:
        with open(state_path, encoding="utf-8") as _f:
            prev_appids = set(json.load(_f))
    except Exception:
        prev_appids = set()
    for g in unique:
        g["is_new"] = bool(prev_appids) and g["appid"] not in prev_appids

    # Agrupar e ordenar por score
    by_block: dict[str, list[dict]] = defaultdict(list)
    for g in unique:
        by_block[g["block"]].append(g)
    for k in by_block:
        by_block[k].sort(key=lambda x: x["score"], reverse=True)

    # FASE 1 — aplica o que JÁ está em cache (sem rede) e publica imediatamente:
    # baixas históricas, metadados (gênero/tags/Deck) e histórico de preço.
    apply_low_cache(unique, hist_cache_path)
    apply_meta_cache(unique, meta_cache_path)
    apply_price_history(unique, price_series_path)
    if output_html:
        save_html(generate_html(by_block, len(unique)), out_path)
        print(f"\n[fase 1] lista publicada em {out_path}")
    if json_path:
        save_json(by_block, len(unique), json_path)
        print(f"[fase 1] JSON publicado em {json_path} (com as baixas do cache)")

    # FASE 2 — semeia os jogos ainda não cacheados (appdetails, lentos
    # e resumíveis), reaplica os caches e republica com tudo enriquecido.
    seed_low_cache(unique, hist_cache_path)
    apply_low_cache(unique, hist_cache_path)
    seed_meta_cache(unique, meta_cache_path)
    apply_meta_cache(unique, meta_cache_path)
    record_price_history(unique, price_series_path)

    print_results(by_block, len(unique))

    if output_html:
        save_html(generate_html(by_block, len(unique)), out_path)
        print(f"\n[fase 2] baixas históricas (amarelo) marcadas em {out_path}")
    if json_path:
        save_json(by_block, len(unique), json_path)
        print(f"[fase 2] baixas históricas marcadas no JSON {json_path}")

    # salva os appids de hoje para a comparação de NEW na próxima geração
    try:
        with open(state_path, "w", encoding="utf-8") as _f:
            json.dump([g["appid"] for g in unique], _f)
    except Exception:
        pass


if __name__ == "__main__":
    main()
