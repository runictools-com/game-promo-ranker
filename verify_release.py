"""Fail a release when established GamePromo features or fresh core data disappear."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


MAX_AGE_HOURS = 36
STATIC_CONTRACT = {
    "static/app.js": (
        'historical-low', 'historical-near', '/api/gamepass',
    ),
    "static/discovery.js": ('Financiamento & Indies', 'Eventos Brasil', 'tab-crowd', 'tab-events'),
    "static/releases.js": ('button.dataset.tab = "releases"', '/api/releases'),
    "static/styles.css": (
        '.card.historical-low', '.card.historical-near',
        'tr.historical-low', 'tr.historical-near',
    ),
    "static/index.html": (
        'Baixa histórica', 'Até 10% da baixa histórica', 'qualidade³',
        '/static/vendor/anime.umd.min.js', '/static/motion.js',
    ),
    "static/motion.js": ('anime.animate', 'prefers-reduced-motion', 'pagehide', 'cancel'),
    "static/vendor/anime.umd.min.js": ('@version v4.5.0', '@license MIT'),
    "app.py": ('attach_low(game', '/healthz'),
}


def read_json(path: Path):
    with path.open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def parse_stamp(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp if stamp.tzinfo else None
    except ValueError:
        return None


def fresh(value, now):
    stamp = parse_stamp(value)
    if stamp is None:
        return False
    age = (now - stamp.astimezone(timezone.utc)).total_seconds()
    return 0 <= age <= MAX_AGE_HOURS * 3600


def verify(root: Path, data_dir: Path | None = None, require_fresh=False, now=None):
    issues = []
    for relative, markers in STATIC_CONTRACT.items():
        path = root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            issues.append(f"missing file: {relative}")
            continue
        for marker in markers:
            if marker not in text:
                issues.append(f"missing feature marker in {relative}: {marker}")

    if data_dir is None:
        return issues
    now = now or datetime.now(timezone.utc)
    try:
        games_payload = read_json(data_dir / "games.json")
        blocks = games_payload.get("blocks", [])
        games = [game for block in blocks for game in block.get("games", [])]
        if not games:
            issues.append("Steam catalog is empty")
        if not games_payload.get("coverage", {}).get("complete_catalog"):
            issues.append("Steam catalog coverage is incomplete")
        if games and any(game.get("score_version") != 4 for game in games):
            issues.append("Steam catalog contains a ranking version older than v4")
        if require_fresh and not fresh(games_payload.get("generated_at"), now):
            issues.append("Steam catalog is older than 36 hours")
    except (OSError, ValueError, TypeError) as exc:
        issues.append(f"invalid games.json: {type(exc).__name__}")

    try:
        history = read_json(data_dir / "steam_price_history.json")
        if not history.get("games"):
            issues.append("local Steam price history is empty")
        if not history.get("historical"):
            issues.append("verified historical-low cache is empty")
        last_run = history.get("last_run", {})
        if require_fresh and (last_run.get("status") != "ok" or not fresh(last_run.get("finished_at"), now)):
            issues.append("daily Steam price verification is stale or incomplete")
    except (OSError, ValueError, TypeError) as exc:
        issues.append(f"invalid steam_price_history.json: {type(exc).__name__}")
    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--data-dir")
    parser.add_argument("--require-fresh", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root)
    data_dir = Path(args.data_dir) if args.data_dir else None
    issues = verify(root, data_dir, args.require_fresh)
    print(json.dumps({"ok": not issues, "issues": issues}, ensure_ascii=False))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
