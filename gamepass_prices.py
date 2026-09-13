"""Independent PC Game Pass membership and exact-title Steam BR price snapshot."""
import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import time
import unicodedata
import requests
from bs4 import BeautifulSoup
from gamepass import SIGL_PC_ALL, SIGLS_URL, HEADERS

SUBSCRIPTION_URL = "https://www.xbox.com/pt-BR/games/store/game-pass/CFQ7TTC0KGQ8"
FALLBACK_SUBSCRIPTION = {"name":"PC Game Pass","monthly_cents":5999,"currency":"BRL",
    "source_url":SUBSCRIPTION_URL,"checked_at":"2026-09-13T02:10:00+00:00"}


def stamp(now):
    return now.isoformat(timespec="seconds")


def fresh(value, now, hours):
    try:
        dt = datetime.fromisoformat(value.replace("Z","+00:00"))
        return dt.tzinfo is not None and 0 <= (now-dt).total_seconds() <= hours*3600
    except (AttributeError,TypeError,ValueError):
        return False


def search_title(title):
    title = re.sub(r"\s*\((?:Windows|PC|Prévia do Jogo|Game Preview)\)\s*", " ", str(title), flags=re.I)
    return re.sub(r"\s+-\s+(?:Windows|PC)\s*$", "", title, flags=re.I).strip()


def normalize_title(title):
    title = unicodedata.normalize("NFKC", search_title(title)).casefold()
    title = re.sub(r"[™®©]", "", title)
    return " ".join("".join(c if c.isalnum() else " " for c in title).split())


def brl_cents(text):
    text = str(text).strip()
    if text.casefold() in {"gratuito", "grátis", "gratis", "free", "free to play", "gratuito para jogar"}:
        return 0
    if not text.startswith("R$"):
        return None
    raw = text[2:].strip().replace(".", "").replace(",", ".")
    try:
        value = Decimal(raw)*100
        return int(value) if value >= 0 and value == int(value) else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


def parse_subscription(html, now):
    soup = BeautifulSoup(html,"html.parser")
    text = soup.get_text(" ",strip=True)
    matches = re.findall(r"PC Game Pass\s*[–—-]\s*1 Meses? de PC Game Pass\s+Microsoft Corporation\s+R\$\s*(\d+(?:[.]\d{3})*,\d{2})\s*/\s*mês",text,re.I)
    prices = {brl_cents("R$"+p) for p in matches}
    if len(prices) != 1 or None in prices:
        return None
    return dict(FALLBACK_SUBSCRIPTION,monthly_cents=prices.pop(),checked_at=stamp(now))


class PacedClient:
    def __init__(self):
        self.last = None
        self.blocked = False

    def get(self,url,params=None):
        if self.blocked:
            raise requests.RequestException("circuit breaker open")
        for attempt in range(3):
            if self.last is not None:
                time.sleep(max(0,1.5-(time.monotonic()-self.last)))
            self.last = time.monotonic()
            try:
                response = requests.get(url,params=params,headers=HEADERS,timeout=25)
            except requests.RequestException:
                self.blocked = True
                raise
            if response.status_code not in (429,503):
                response.raise_for_status()
                return response
            if attempt == 2:
                self.blocked = True
                response.raise_for_status()
            try:
                wait = max(0,min(60,float(response.headers.get("Retry-After",30*(attempt+1)))))
            except ValueError:
                wait = 30*(attempt+1)
            time.sleep(wait)
        raise requests.RequestException("retry exhausted")


def parse_search(html,title,now):
    matches = {}
    candidate_ids = set()
    for row in BeautifulSoup(html,"html.parser").select("a.search_result_row"):
        name = row.select_one(".title")
        if not name or normalize_title(name.get_text(strip=True)) != normalize_title(title):
            continue
        match = re.search(r"https://store[.]steampowered[.]com/app/(\d+)(?:/|$)",row.get("href", ""))
        if not match:
            continue
        candidate_ids.add(match.group(1))
        if len(candidate_ids) > 1:
            return None
        price = row.select_one(".discount_final_price") or row.select_one(".search_price")
        if not price:
            continue
        for old in price.select("strike"):
            old.decompose()
        cents = brl_cents(price.get_text(" ",strip=True))
        if cents is None:
            continue
        appid = match.group(1)
        candidate = dict(appid=appid,title=name.get_text(strip=True),price_cents=cents,currency="BRL",
            url=f"https://store.steampowered.com/app/{appid}/",checked_at=stamp(now))
        if appid in matches and matches[appid]["price_cents"] != cents:
            return None
        matches[appid] = candidate
    return next(iter(matches.values())) if len(matches)==1 else None


def reuse_index(games,now):
    result = {}
    checked = games.get("generated_at")
    if not fresh(checked,now,24):
        return result
    for block in games.get("blocks",[]):
        for game in block.get("games",[]):
            if game.get("currency") != "BRL" or game.get("country") != "BR":
                continue
            cents = brl_cents(game.get("sale_price"))
            if cents is None:
                continue
            key = normalize_title(game.get("name", ""))
            result.setdefault(key,{})[str(game["appid"])] = dict(appid=str(game["appid"]),title=game["name"],
                price_cents=cents,currency="BRL",url=f"https://store.steampowered.com/app/{game['appid']}/",checked_at=checked)
    return {key:next(iter(values.values())) for key,values in result.items() if len(values)==1}


def collect(catalog,previous=None,games=None,now=None,max_lookups=100,client=None):
    now = now or datetime.now(timezone.utc)
    previous = previous or {}
    injected_client = client is not None
    client = client or PacedClient()
    subscription_client = client if injected_client else PacedClient()
    output = dict(generated_at=stamp(now),membership_checked_at=previous.get("membership_checked_at"),
        active_ids=previous.get("active_ids",[]), subscription=previous.get("subscription") or dict(FALLBACK_SUBSCRIPTION),
        prices=dict(previous.get("prices",{})))
    coverage = {"membership":"unavailable","lookups":0,"resolved":0,"reused":0,"failed":0,"max_lookups":max_lookups}
    output["coverage"] = coverage
    try:
        data = client.get(SIGLS_URL,{"id":SIGL_PC_ALL,"language":"pt-br","market":"BR"}).json()
        ids = list(dict.fromkeys(x["id"] for x in data if isinstance(x,dict) and x.get("id")))
        if not ids:
            raise ValueError("empty membership")
        output.update(active_ids=ids,membership_checked_at=stamp(now))
        coverage["membership"] = "ok"
    except (requests.RequestException,ValueError,TypeError):
        coverage["failed"] += 1
        return output
    try:
        sub = parse_subscription(subscription_client.get(SUBSCRIPTION_URL).text,now)
        if sub:
            output["subscription"] = sub
    except (requests.RequestException,ValueError):
        pass
    index = reuse_index(games or {},now)
    metadata = catalog.get("catalog",[])
    if isinstance(metadata,dict):
        metadata = list(metadata.values())
    titles = {g["id"]:g["title"] for g in metadata if g.get("id") and g.get("title")}
    pending = []
    for pid in ids:
        title = titles.get(pid)
        if not title:
            continue
        old = output["prices"].get(pid,{})
        if old and normalize_title(old.get("title","")) != normalize_title(title):
            output["prices"].pop(pid,None)
            old = {}
        if old.get("currency")=="BRL" and fresh(old.get("checked_at"),now,24) and normalize_title(old.get("title",""))==normalize_title(title):
            coverage["reused"] += 1
        elif normalize_title(title) in index:
            output["prices"][pid] = index[normalize_title(title)]
            coverage["reused"] += 1
        else:
            pending.append((pid,title))
    pending.sort(key=lambda row: output["prices"].get(row[0],{}).get("checked_at", ""))
    for pid,title in pending[:max(0,max_lookups)]:
        if client.blocked:
            break
        coverage["lookups"] += 1
        if coverage["lookups"] == 1 or coverage["lookups"] % 25 == 0:
            print(f"Steam prices: {coverage['lookups']}/{min(len(pending), max_lookups)} lookups; {coverage['resolved']} resolved, {coverage['reused']} reused", flush=True)
        try:
            data = client.get("https://store.steampowered.com/search/results/",{
                "term":search_title(title),"cc":"br","l":"portuguese","category1":998,"count":100,"start":0,"json":1,"infinite":1}).json()
            if "results_html" not in data and "items_html" not in data:
                raise ValueError("missing search HTML")
            item = parse_search(data.get("results_html") or data.get("items_html") or "",title,now)
            if item:
                output["prices"][pid]=item
                coverage["resolved"] += 1
        except (requests.RequestException,ValueError,TypeError):
            coverage["failed"] += 1
            break
    coverage.update(active_members=len(ids),metadata_titles=len(titles),pending=len(pending),
        current_prices=sum(fresh(v.get("checked_at"),now,24) for k,v in output["prices"].items() if k in ids))
    return output


def read(path):
    try:
        value=json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):
        return {}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-dir",default="data")
    parser.add_argument("--max-lookups",type=int,default=100)
    parser.add_argument("--json",default=None)
    args=parser.parse_args()
    path=Path(args.json) if args.json else Path(args.data_dir)/"gamepass_prices.json"
    folder=path.parent;folder.mkdir(parents=True,exist_ok=True)
    output=collect(read(folder/"gamepass.json"),read(path),read(folder/"games.json"),max_lookups=args.max_lookups)
    tmp=path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(tmp,path)
    print(json.dumps(output["coverage"]))
    return 1 if output["coverage"]["membership"] != "ok" or output["coverage"]["failed"] else 0

if __name__=="__main__":
    raise SystemExit(main())
