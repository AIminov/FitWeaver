import unittest
from unittest.mock import Mock, patch

import requests

from garmin_fit.api_client import PlanApiClient, PlanApiError


class PlanApiClientTests(unittest.TestCase):
    def setUp(self):
        self.client = PlanApiClient("http://127.0.0.1:8008", "test-token", timeout_sec=30)

    def _mock_response(self, status_code, json_body):
        resp = Mock()
        resp.status_code = status_code
        resp.json.return_value = json_body
        resp.raise_for_status = Mock()
        return resp

    def test_build_plan_draft_success(self):
        resp = self._mock_response(200, {
            "yaml_text": "workouts: []", "data": {"workouts": []},
            "warnings": [], "repairs": [], "ambiguities": [],
            "validation_errors": [], "error_categories": {}, "attempts": 1,
        })
        with patch("requests.post", return_value=resp) as mock_post:
            result = self.client.build_plan_draft("some plan text", max_retries=2)
        self.assertEqual(result.yaml_text, "workouts: []")
        self.assertEqual(result.attempts, 1)
        mock_post.assert_called_once()
        called_headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(called_headers["X-Api-Token"], "test-token")

    def test_401_raises_plan_api_error_with_status_code(self):
        resp = self._mock_response(401, {"detail": "Invalid or missing X-Api-Token header"})
        with patch("requests.post", return_value=resp):
            with self.assertRaises(PlanApiError) as ctx:
                self.client.build_plan_draft("text")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_429_raises_plan_api_error_with_status_code(self):
        resp = self._mock_response(429, {"detail": "Rate limit exceeded"})
        with patch("requests.post", return_value=resp):
            with self.assertRaises(PlanApiError) as ctx:
                self.client.build_plan_draft("text")
        self.assertEqual(ctx.exception.status_code, 429)

    def test_422_raises_plan_api_error_with_detail_message(self):
        resp = self._mock_response(422, {"detail": "Could not parse drills"})
        with patch("requests.post", return_value=resp):
            with self.assertRaises(PlanApiError) as ctx:
                self.client.apply_custom_sbu_choice({"workouts": []}, "gibberish")
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Could not parse drills", str(ctx.exception))

    def test_timeout_raises_plan_api_error_without_status_code(self):
        with patch("requests.post", side_effect=requests.Timeout("timed out")):
            with self.assertRaises(PlanApiError) as ctx:
                self.client.build_plan_draft("text")
        self.assertIsNone(ctx.exception.status_code)

    def test_connection_error_raises_plan_api_error_without_status_code(self):
        with patch("requests.post", side_effect=requests.ConnectionError("refused")):
            with self.assertRaises(PlanApiError) as ctx:
                self.client.build_plan_draft("text")
        self.assertIsNone(ctx.exception.status_code)

    def test_check_connection_true(self):
        resp = self._mock_response(200, {"llm_connected": True})
        with patch("requests.get", return_value=resp):
            self.assertTrue(self.client.check_connection())

    def test_check_connection_false_on_bad_status(self):
        resp = self._mock_response(500, {})
        with patch("requests.get", return_value=resp):
            self.assertFalse(self.client.check_connection())

    def test_check_connection_false_on_network_error(self):
        with patch("requests.get", side_effect=requests.ConnectionError("refused")):
            self.assertFalse(self.client.check_connection())

    def test_timeout_sec_fires_before_callers_outer_timeout(self):
        client = PlanApiClient("http://x", "tok", timeout_sec=300)
        self.assertEqual(client.timeout_sec, 295)

    def test_timeout_sec_has_floor_of_one(self):
        client = PlanApiClient("http://x", "tok", timeout_sec=2)
        self.assertEqual(client.timeout_sec, 1)


if __name__ == "__main__":
    unittest.main()
