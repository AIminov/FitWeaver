import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient

    from garmin_fit.api.app import create_app
    from garmin_fit.api.config import ApiSettings
    from garmin_fit.llm.client import GeneratedYamlResult

    fastapi_available = True
except ImportError:
    fastapi_available = False


@unittest.skipIf(not fastapi_available, "fastapi/uvicorn not installed (pip install -e '.[api]')")
class PlanApiTests(unittest.TestCase):
    def setUp(self):
        self.settings = ApiSettings(
            api_token="test-token", rate_limit_per_minute=6.0, rate_limit_burst=2.0
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)
        self.headers = {"X-Api-Token": "test-token"}

    def test_generate_draft_success(self):
        canned = GeneratedYamlResult(
            yaml_text="workouts: []",
            data={"workouts": []},
            warnings=["w1"],
            repairs=["r1"],
            ambiguities=["a1"],
            validation_errors=[],
            error_categories={},
            attempts=1,
        )
        with patch("garmin_fit.api.app.plan_service.build_plan_draft", return_value=canned):
            resp = self.client.post(
                "/v1/generate-draft",
                json={"plan_text": "10km easy run", "max_retries": 2},
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["yaml_text"], "workouts: []")
        self.assertEqual(body["data"], {"workouts": []})
        self.assertEqual(body["warnings"], ["w1"])
        self.assertEqual(body["repairs"], ["r1"])
        self.assertEqual(body["ambiguities"], ["a1"])
        self.assertEqual(body["attempts"], 1)

    def test_generate_draft_requires_token(self):
        resp = self.client.post("/v1/generate-draft", json={"plan_text": "10km easy run"})
        self.assertEqual(resp.status_code, 401)

    def test_generate_draft_wrong_token(self):
        resp = self.client.post(
            "/v1/generate-draft",
            json={"plan_text": "10km easy run"},
            headers={"X-Api-Token": "wrong"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_apply_sbu_choice_success(self):
        canned = GeneratedYamlResult(yaml_text="workouts: []", data={"workouts": []}, attempts=1)
        with patch("garmin_fit.api.app.plan_service.apply_custom_sbu_choice", return_value=canned):
            resp = self.client.post(
                "/v1/apply-sbu-choice",
                json={"yaml_data": {"workouts": []}, "user_text": "high knees 30s x2"},
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["yaml_text"], "workouts: []")

    def test_apply_sbu_choice_value_error_returns_422(self):
        with patch(
            "garmin_fit.api.app.plan_service.apply_custom_sbu_choice",
            side_effect=ValueError("Could not parse drills"),
        ):
            resp = self.client.post(
                "/v1/apply-sbu-choice",
                json={"yaml_data": {"workouts": []}, "user_text": "gibberish"},
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 422)
        self.assertIn("Could not parse drills", resp.json()["detail"])

    def test_health_endpoint_reports_llm_connected_true(self):
        with patch(
            "garmin_fit.api.app.UnifiedLLMClient.check_connection", return_value=True
        ):
            resp = self.client.get("/v1/health", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"llm_connected": True})

    def test_health_endpoint_reports_llm_connected_false(self):
        with patch(
            "garmin_fit.api.app.UnifiedLLMClient.check_connection", return_value=False
        ):
            resp = self.client.get("/v1/health", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"llm_connected": False})

    def test_rate_limit_returns_429_after_burst(self):
        tight_settings = ApiSettings(
            api_token="test-token", rate_limit_per_minute=6.0, rate_limit_burst=1.0
        )
        app = create_app(tight_settings)
        client = TestClient(app)
        canned = GeneratedYamlResult(yaml_text="workouts: []", attempts=1)

        with patch("garmin_fit.api.app.plan_service.build_plan_draft", return_value=canned):
            first = client.post(
                "/v1/generate-draft", json={"plan_text": "plan one"}, headers=self.headers
            )
            second = client.post(
                "/v1/generate-draft", json={"plan_text": "plan two"}, headers=self.headers
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_rate_limit_state_is_isolated_per_app_instance(self):
        """Two separate create_app() calls must not share bucket state."""
        settings = ApiSettings(api_token="test-token", rate_limit_burst=1.0)
        app_a = create_app(settings)
        app_b = create_app(settings)
        self.assertIsNot(app_a.state.rate_limit_buckets, app_b.state.rate_limit_buckets)


if __name__ == "__main__":
    unittest.main()
