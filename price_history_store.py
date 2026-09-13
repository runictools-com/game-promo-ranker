"""Persistent observed Steam Brazil minima; never an external all-time low."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import tempfile


class HistoryError(ValueError):
    pass


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError) as exc:
        raise HistoryError("Invalid timezone-aware timestamp") from exc


def cents_valid(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_envelope(history):
    if not isinstance(history, dict) or history.get("schema_version") != 1 or not isinstance(history.get("games"), dict):
        raise HistoryError("Invalid history schema")


def validate_entry(appid, entry):
    if not str(appid).isdigit() or not isinstance(entry, dict):
        raise HistoryError("Invalid game record")
    if entry.get("currency") != "BRL" or entry.get("country") != "BR":
        raise HistoryError("Invalid history region")
    if not cents_valid(entry.get("low_cents")) or not cents_valid(entry.get("last_price_cents")):
        raise HistoryError("Invalid price")
    for name in ("first_seen", "last_checked"):
        timestamp(entry.get(name))
    for name in ("low_at", "new_low_at"):
        if entry.get(name) is not None:
            timestamp(entry[name])
    if not isinstance(entry.get("observation_dates"), list):
        raise HistoryError("Invalid observation dates")
    for day in entry["observation_dates"]:
        try:
            if datetime.strptime(day, "%Y-%m-%d").strftime("%Y-%m-%d") != day:
                raise ValueError("invalid date")
        except (TypeError, ValueError) as exc:
            raise HistoryError("Invalid observation date") from exc


def validate(history):
    validate_envelope(history)
    for appid, entry in history["games"].items():
        validate_entry(appid, entry)
    return history


def read_history(path):
    path = Path(path)
    if not path.exists():
        return {"schema_version": 1, "games": {}}
    try:
        return validate(json.loads(path.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError) as exc:
        raise HistoryError(f"Cannot read history: {path.name}; original preserved") from exc


def write_history(path, history):
    validate(history)
    path = Path(path)
    # Refuse to replace an existing malformed history even if caller skipped read.
    if path.exists():
        read_history(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name+".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(history, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def observe(history, appid, cents, checked_at):
    validate_envelope(history)
    appid = str(appid)
    if not appid.isdigit() or not cents_valid(cents):
        raise HistoryError("Appid and integer BRL cents required")
    when = timestamp(checked_at)
    iso = when.isoformat(timespec="seconds")
    day = when.astimezone(timezone(timedelta(hours=-3))).date().isoformat()
    entry = history["games"].get(appid)
    if appid in history["games"]:
        validate_entry(appid, entry)
    if entry is None:
        entry = dict(low_cents=cents, currency="BRL", country="BR", first_seen=iso,
            low_at=iso, last_checked=iso, last_price_cents=cents, observation_dates=[day], new_low_at=None)
        history["games"][appid] = entry
        return entry
    if when < timestamp(entry["first_seen"]):
        entry["first_seen"] = iso
    if cents < entry["low_cents"]:
        entry.update(low_cents=cents, low_at=iso, new_low_at=iso)
    if when > timestamp(entry["last_checked"]):
        entry.update(last_checked=iso, last_price_cents=cents)
    entry["observation_dates"] = sorted(set(entry["observation_dates"] + [day]))
    return entry


def decimal_cents(value):
    try:
        amount = Decimal(str(value)) * 100
        if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
            return None
        return int(amount)
    except (InvalidOperation, ValueError):
        return None


def brl_cents(value):
    if not isinstance(value, str) or not value.strip().startswith("R$"):
        return None
    raw = value.strip()[2:].strip().replace(" ", "")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    return decimal_cents(raw)


def load_snapshot(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def fresh(checked_at, now):
    try:
        elapsed = (now-timestamp(checked_at)).total_seconds()
        return 0 <= elapsed <= 36*3600
    except HistoryError:
        return False


def migrate_legacy(history, legacy):
    for appid, value in legacy.items():
        if not isinstance(value, dict) or (value.get("src"), value.get("currency"), value.get("country")) != ("obs", "BRL", "BR"):
            continue
        cents = decimal_cents(value.get("low_brl"))
        if cents is None or not str(appid).isdigit():
            continue
        try:
            first = timestamp(value.get("first_seen"))
            last = timestamp(value.get("updated"))
        except HistoryError:
            continue
        # Legacy updated is cache maintenance, NOT an observation of the low.
        entry = history["games"].get(str(appid))
        if entry is None:
            entry = observe(history, appid, cents, first.isoformat())
            entry["low_at"] = None
            entry["new_low_at"] = None
        elif cents < entry["low_cents"]:
            entry.update(low_cents=cents, low_at=None, new_low_at=None)
        if first < timestamp(entry["first_seen"]):
            entry["first_seen"] = first.isoformat()
        valid_dates = []
        for day in value.get("observed_dates", []):
            try:
                if datetime.strptime(day, "%Y-%m-%d").strftime("%Y-%m-%d") == day:
                    valid_dates.append(day)
            except (TypeError, ValueError):
                pass
        entry["observation_dates"] = sorted(set(entry["observation_dates"] + valid_dates))


def seed_from_snapshots(folder, history, now=None):
    validate(history)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise HistoryError("Timezone required for now")
    folder = Path(folder)
    migrate_legacy(history, load_snapshot(folder/"observed_lows_br_app_v2.json"))
    games = load_snapshot(folder/"games.json")
    checked = games.get("generated_at")
    if fresh(checked, now):
        for block in games.get("blocks", []):
            for game in block.get("games", []):
                if (game.get("currency"), game.get("country")) != ("BRL", "BR"):
                    continue
                cents = brl_cents(game.get("sale_price"))
                if cents is not None:
                    try:
                        observe(history, game.get("appid", ""), cents, checked)
                    except HistoryError:
                        continue
    prices = load_snapshot(folder/"gamepass_prices.json")
    for game in prices.get("prices", {}).values():
        checked = game.get("checked_at")
        cents = game.get("price_cents")
        if game.get("currency") == "BRL" and game.get("country", "BR") == "BR" and cents_valid(cents) and fresh(checked, now):
            try:
                observe(history, game.get("appid", ""), cents, checked)
            except HistoryError:
                continue
    return history
