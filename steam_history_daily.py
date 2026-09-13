"""Refresh every known Steam BR price, including off-sale and upcoming games.

python steam_history_daily.py --data-dir data
python steam_history_daily.py --data-dir data --seed-only
Missing prices are pending/unavailable, never zero. Observed minima survive errors.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import requests

from price_history_store import (HistoryError, cents_valid, load_snapshot, observe,
                                 read_history, seed_from_snapshots, timestamp, write_history)
from steam_releases import SteamTransport

STEAM_APPDETAILS = "https://store.steampowered.com/api/appdetails"


def appids_in(value):
    """Only named appid fields; other numeric mapping keys are not app IDs."""
    result = set()
    if isinstance(value, dict):
        for name in ("appid", "steam_appid"):
            appid = value.get(name)
            if not isinstance(appid, bool) and str(appid).isdigit() and int(appid) > 0:
                result.add(str(int(appid)))
        for child in value.values():
            if isinstance(child, (dict, list)):
                result.update(appids_in(child))
    elif isinstance(value, list):
        for child in value:
            result.update(appids_in(child))
    return result


def known_appids(folder, history):
    ids = {str(x) for x in history["games"] if str(x).isdigit() and int(x) > 0}
    ids.update(str(x) for x in history.get("attempts", {}) if str(x).isdigit() and int(x) > 0)
    for filename in ("games.json", "gamepass_prices.json", "releases.json"):
        ids.update(appids_in(load_snapshot(Path(folder) / filename)))
    return sorted(ids, key=int)


def brl_price(record):
    if not isinstance(record, dict) or record.get("success") is not True:
        return None
    data = record.get("data")
    if not isinstance(data, dict):
        return None
    price = data.get("price_overview")
    if not isinstance(price, dict) or price.get("currency") != "BRL":
        return None
    cents = price.get("final")
    return cents if cents_valid(cents) else None


def coverage(history, ids, now):
    stale = 0
    for appid in ids:
        entry = history["games"].get(appid)
        if entry is not None:
            age = (now - timestamp(entry["last_checked"])).total_seconds()
            if age > 36 * 3600 or age < 0:
                stale += 1
    priced = sum(appid in history["games"] for appid in ids)
    return dict(monitored_count=len(ids), priced_known=priced, unpriced_known=len(ids) - priced,
                stale_prices=stale, currency="BRL", country="BR",
                note="Mínimas observadas pelo GamePromo; ausência de preço não significa grátis. Jogos sem preço continuam monitorados diariamente.")


def run(data_dir="data", output_path=None, seed_only=False, fetch_batch=None, now=None, batch_size=50):
    folder = Path(data_dir)
    path = Path(output_path) if output_path else folder / "steam_price_history.json"
    clock = (lambda: now) if now is not None else (lambda: datetime.now(timezone.utc))
    started = clock()
    history = read_history(path)  # Corruption stops before any request or write.
    seed_from_snapshots(folder, history, started)
    ids = known_appids(folder, history)
    attempts = history.setdefault("attempts", {})
    if not isinstance(attempts, dict):
        raise HistoryError("Invalid attempts mapping; original preserved")
    for appid in ids:
        attempts.setdefault(appid, {"last_attempt": None, "status": "awaiting_price" if appid not in history["games"] else "seeded"})
    batch_size = max(1, min(50, int(batch_size)))
    report = dict(started_at=started.isoformat(), status="seeded" if seed_only else "running",
                  target_count=len(ids), attempted_count=0, observed_count=0, unavailable_count=0,
                  failed_count=0, unattempted_count=len(ids), batches_completed=0, batch_size=batch_size,
                  source=STEAM_APPDETAILS, country="BR", currency="BRL", errors=[])
    history["last_run"] = report
    def persist():
        history["coverage"] = coverage(history, ids, clock())
        write_history(path, history)
    if seed_only:
        report["finished_at"] = clock().isoformat()
        persist()
        return history
    persist()
    transport = SteamTransport(interval=3.0)
    def fetch(batch):
        if fetch_batch is not None:
            return fetch_batch(batch)
        return transport.get_json(STEAM_APPDETAILS, params={"appids": ",".join(batch), "cc": "br", "filters": "price_overview"})
    for offset in range(0, len(ids), batch_size):
        batch = ids[offset:offset + batch_size]
        checked = clock().isoformat()
        try:
            response = fetch(batch)
            if not isinstance(response, dict) or not any(appid in response for appid in batch):
                raise ValueError("Invalid Steam bulk response")
            checked = clock().isoformat()
        except (requests.RequestException, ValueError, TypeError) as exc:
            checked = clock().isoformat()
            report["attempted_count"] += len(batch)
            report["failed_count"] += len(batch)
            report["unattempted_count"] = len(ids) - report["attempted_count"]
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            report["errors"].append(dict(type=type(exc).__name__, http_status=status_code, batch_offset=offset))
            for appid in batch:
                attempts[appid] = dict(last_attempt=checked, status="source_error")
                if appid in history["games"]:
                    history["games"][appid].update(last_attempt=checked, price_status="source_error")
            report["status"] = "partial" if report["batches_completed"] else "failed"
            # Circuit stop after this batch exhausted bounded transport retries.
            # Do not hammer the source for every remaining ID.
            break
        for appid in batch:
            cents = brl_price(response.get(appid))
            if cents is None:
                report["unavailable_count"] += 1
                attempts[appid] = dict(last_attempt=checked, status="awaiting_price")
                if appid in history["games"]:
                    history["games"][appid].update(last_attempt=checked, price_status="awaiting_price")
            else:
                entry = observe(history, appid, cents, checked)
                entry.update(last_attempt=checked, price_status="observed")
                attempts[appid] = dict(last_attempt=checked, status="observed")
                report["observed_count"] += 1
        report["attempted_count"] += len(batch)
        report["unattempted_count"] = len(ids) - report["attempted_count"]
        report["batches_completed"] += 1
        persist()  # Preserve progress and minima if a later batch fails.
        if report['batches_completed'] % 5 == 0 or report['unattempted_count'] == 0:
            print(f"History: {report['attempted_count']}/{len(ids)} checked, {report['observed_count']} prices, {report['unavailable_count']} awaiting price", flush=True)
    if report["status"] == "running":
        report["status"] = "ok"
    report["finished_at"] = clock().isoformat()
    persist()
    return history


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--json", default=None, help="History output path; defaults to DATA-DIR/steam_price_history.json")
    parser.add_argument("--seed-only", action="store_true", help="Backfill trusted local snapshots without network")
    args = parser.parse_args(argv)
    try:
        history = run(args.data_dir, args.json, args.seed_only)
    except (HistoryError, OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__, "detail": str(exc)}))
        return 1
    print(json.dumps(history["last_run"], ensure_ascii=False))
    return 0 if history["last_run"]["status"] in ("ok", "seeded") else 1


if __name__ == "__main__":
    raise SystemExit(main())
