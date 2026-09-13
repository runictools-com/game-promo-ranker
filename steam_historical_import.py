"""Import Steam-only BRL historical minima from IsThereAnyDeal/Augmented Steam."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.parse import urlparse

import requests
from price_history_store import read_history, write_history, timestamp, cents_valid
from steam_history_daily import known_appids

ENDPOINT = "https://api.augmentedsteam.com/prices/v2"


def import_low(history, appid, data, checked_at):
    """Do not import another shop, another currency, or overwrite a lower record."""
    low = data.get("lowest") if isinstance(data, dict) else None
    if not isinstance(low, dict) or (low.get("shop") or {}).get("id") != 61:
        return False
    price = low.get("price") or {}
    cents = price.get("amountInt")
    if price.get("currency") != "BRL" or not cents_valid(cents):
        return False
    when = timestamp(low.get("timestamp"))
    checked = timestamp(checked_at)
    if when > checked:
        return False
    url = (data.get("urls") or {}).get("history", "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "isthereanydeal.com":
        return False
    records = history.setdefault("historical", {})
    old = records.get(str(appid))
    if old is None or cents < old["low_cents"]:
        records[str(appid)] = dict(low_cents=cents, low_at=when.isoformat(), currency="BRL", country="BR",
            shop_id=61, source="IsThereAnyDeal / Augmented Steam", source_url=url, checked_at=checked.isoformat())
    else:
        old["checked_at"] = checked.isoformat()
    # One canonical minimum also feeds existing ranking calculations. Historical
    # imports do not add fake daily observations or renew the live Steam quote.
    entry = history["games"].get(str(appid))
    best = records[str(appid)]
    if entry and best["low_cents"] <= entry["low_cents"]:
        entry.update(low_cents=best["low_cents"], low_at=best["low_at"], new_low_at=None)
    return True


def run(path, fetch=None, sleep=time.sleep, now=None):
    path = Path(path)
    history = read_history(path)
    clock = lambda: now or datetime.now(timezone.utc)
    ids = known_appids(path.parent, history)
    ids = sorted(set(ids) | set(history.get("historical", {})), key=int)
    report = dict(started_at=clock().isoformat(), status="running", total=len(ids), checked=0, imported=0, unavailable=0)
    history["historical_run"] = report
    attempts = history.setdefault("historical_attempts", {})
    def request(batch):
        response = requests.post(ENDPOINT, json=dict(country="BR", apps=[int(x) for x in batch],
            subs=[], bundles=[], voucher=False, shops=[61]), timeout=(5, 40),
            headers={"User-Agent": "GamePromo/2.0 (+https://gamepromo.runictools.com)"})
        response.raise_for_status()
        return response.json()
    request = fetch or request
    try:
        for start in range(0, len(ids), 50):
            batch = ids[start:start + 50]
            if start:
                sleep(3)
            result = request(batch)
            if not isinstance(result, dict) or not isinstance(result.get("prices"), dict):
                raise ValueError("Invalid price response")
            checked = clock().isoformat()
            for appid in batch:
                found = import_low(history, appid, result["prices"].get("app/" + appid), checked)
                attempts[appid] = dict(checked_at=checked, status="verified" if found else "unavailable")
                report["imported" if found else "unavailable"] += 1
                report["checked"] += 1
            write_history(path, history)
            print(f'Historical: {report["checked"]}/{len(ids)}, {report["imported"]} verified', flush=True)
        report["status"] = "ok"
    except (requests.RequestException, ValueError) as exc:
        report.update(status="failed", error=type(exc).__name__)
    report["finished_at"] = clock().isoformat()
    write_history(path, history)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="data/steam_price_history.json")
    args = parser.parse_args()
    result = run(args.json)
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "ok" else 1)
