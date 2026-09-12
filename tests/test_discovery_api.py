import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import app


class DiscoveryApiTests(unittest.TestCase):
    def test_release_calendar_preserves_partial_status_and_uncertain_dates(self):
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'releases.json'
            path.write_text(json.dumps({'valid_until': future, 'stale': True,
                'releases': [{'release_date': None, 'release_date_raw': 'Q4 2026'}]}), encoding='utf-8')
            with patch.object(app, 'RELEASES_FILE', str(path)):
                response = app.app.test_client().get('/api/releases')
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.get_json()['stale'])
                self.assertIsNone(response.get_json()['releases'][0]['release_date'])

    def test_missing_returns_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(app, 'DISCOVERY_FILE', str(Path(folder) / 'missing.json')):
                self.assertEqual(app.app.test_client().get('/api/discovery').status_code, 503)

    def test_expired_campaigns_removed_without_changing_timestamp(self):
        now = datetime.now(timezone.utc)
        future = (now + timedelta(days=2)).isoformat()
        past = (now - timedelta(days=2)).isoformat()
        data = {'updated_at': past, 'valid_until': future, 'campaigns': [
            {'id': 'closed', 'end_date': past, 'valid_until': future},
            {'id': 'open', 'end_date': future, 'valid_until': future}],
            'events': [{'id': 'past', 'end_date': past, 'valid_until': future}],
            'indie_games': []}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'discovery.json'
            with patch.object(app, 'DISCOVERY_FILE', str(path)):
                path.write_text(json.dumps(data), encoding='utf-8')
                result = app.app.test_client().get('/api/discovery').get_json()
                self.assertEqual([x['id'] for x in result['campaigns']], ['open'])
                self.assertEqual(result['events'], [])
                self.assertEqual(result['updated_at'], past)
                data['valid_until'] = past
                path.write_text(json.dumps(data), encoding='utf-8')
                result = app.app.test_client().get('/api/discovery').get_json()
                self.assertTrue(result['stale'])
                self.assertEqual(result['campaigns'], [])
