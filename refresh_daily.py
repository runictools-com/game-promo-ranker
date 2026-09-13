"""Run daily collectors independently; a failure does not stop other sources."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--pages', type=int, default=20)
    args = parser.parse_args()
    folder = Path(args.data_dir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    jobs = [('steam_sale_ranker.py', 'games.json', [str(args.pages)]),
            ('discovery.py', 'discovery.json', []),
            ('steam_releases.py', 'releases.json', []),
            ('free_games.py', 'free_games.json', []),
            ('epic_deals.py', 'epic_games.json', []),
            ('gamepass.py', 'gamepass.json', []),
            ('gamepass_prices.py', 'gamepass_prices.json', ['--max-lookups', '600']),
            ('steam_history_daily.py', 'steam_price_history.json', []),
            ('steam_historical_import.py', 'steam_price_history.json', [])]
    results = []
    for script, output, options in jobs:
        print(f'\n[start] {script}', flush=True)
        try:
            run = subprocess.run([sys.executable, str(Path(__file__).parent / script), *options,
                                  '--json', str(folder / output)], timeout=1800, check=False)
            status = 'ok' if run.returncode == 0 else 'failed'
        except subprocess.TimeoutExpired:
            status = 'timeout'
        results.append({'source': script, 'status': status,
                        'finished_at': datetime.now(timezone.utc).isoformat()})
        temp = folder / 'refresh_status.json.tmp'
        temp.write_text(json.dumps({'jobs': results}, indent=2), encoding='utf-8')
        os.replace(temp, folder / 'refresh_status.json')
        print(f'[done] {script}: {status}', flush=True)
    return 0 if all(row['status'] == 'ok' for row in results) else 1


if __name__ == '__main__':
    sys.exit(main())
