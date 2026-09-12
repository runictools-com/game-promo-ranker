"""DisplayCatalog failures must never masquerade as games leaving Game Pass."""
import unittest
from unittest.mock import Mock, patch

import requests

import gamepass


def response(status, products=None, retry_after=None):
    result = Mock(status_code=status, headers={})
    result.json.return_value = {"Products": products or []}
    if retry_after is not None:
        result.headers["Retry-After"] = retry_after
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(str(status))
    return result


class GamePassResolutionTests(unittest.TestCase):
    def test_rate_limit_recovers_after_one_retry(self):
        product = {"ProductId": "A", "LocalizedProperties": [{"ProductTitle": "Game"}]}
        with patch.object(gamepass.requests, "get", side_effect=[
            response(429, retry_after="3"), response(200, [product])
        ]) as get, patch.object(gamepass.time, "sleep") as sleep:
            self.assertEqual(gamepass.resolve(["A"])["A"]["title"], "Game")
            self.assertEqual(get.call_count, 2)
            sleep.assert_called_once_with(3)

    def test_persistent_rate_limit_is_reported(self):
        with patch.object(gamepass.requests, "get", return_value=response(429)) as get, \
                patch.object(gamepass.time, "sleep"):
            with self.assertRaises(requests.HTTPError):
                gamepass.resolve(["A"])
            self.assertEqual(get.call_count, 2)

    def test_long_retry_after_does_not_retry_early(self):
        with patch.object(gamepass.requests, "get", return_value=response(429, retry_after="60")) as get, \
                patch.object(gamepass.time, "sleep") as sleep:
            with self.assertRaises(requests.HTTPError):
                gamepass.resolve(["A"])
            self.assertEqual(get.call_count, 1)
            sleep.assert_not_called()

    def test_partial_catalog_is_not_returned_for_removal_diff(self):
        with patch.object(gamepass.requests, "get", return_value=response(200, [{"ProductId": "A"}])):
            with self.assertRaisesRegex(ValueError, "incompleto"):
                gamepass.resolve(["A", "B"])

    def test_empty_catalog_is_not_returned_for_removal_diff(self):
        with patch.object(gamepass.requests, "get", return_value=response(200)):
            with self.assertRaisesRegex(ValueError, "incompleto"):
                gamepass.resolve(["A"])


if __name__ == "__main__":
    unittest.main()
