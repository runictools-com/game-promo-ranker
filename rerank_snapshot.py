"""Recalculate scores without changing price collection timestamps or observations."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from steam_sale_ranker import update_score_details


def rerank(payload):
    count = 0
    for block in payload['blocks']:
        for game in block['games']:
            update_score_details(game, game.get('score_components', {}).get('observed_price_proximity'))
            game['score'] = round(game['score'], 4)
            count += 1
        block['games'].sort(key=lambda g: g['score'], reverse=True)
    if not count:
        raise ValueError('Empty snapshot; refusing to replace')
    payload['ranking_updated_at'] = datetime.now(timezone.utc).isoformat()
    return payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', default='data/games.json')
    args = parser.parse_args()
    path = Path(args.file)
    payload = rerank(json.loads(path.read_text(encoding='utf-8-sig')))
    temp = path.with_suffix('.rerank.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)
    print('Ranking v4 updated; source timestamps and price observations preserved')
