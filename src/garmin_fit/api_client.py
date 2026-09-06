"""HTTP client for the FitWeaver Plan API (src/garmin_fit/api/). Shared by
the Telegram bot and the GUI's "LLM автора" mode -- both become callers of
the same three endpoints instead of building UnifiedLLMClient directly.
"""

from __future__ import annotations

import requests

from .llm.client import MAX_RETRIES, GeneratedYamlResult


class PlanApiError(RuntimeError):
    """Auth failure, rate limit, validation error, or unreachable API.

    Subclasses RuntimeError so existing broad `except Exception` call sites
    (e.g. in telegram_bot.py) catch it with no changes needed there.
    """

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class PlanApiClient:
    def __init__(self, base_url: str, api_token: str, timeout_sec: int = 300):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        # Fire a little before the caller's own outer timeout so a clean
        # PlanApiError surfaces instead of the caller's wrapper abandoning
        # an in-flight request.
        self.timeout_sec = max(1, timeout_sec - 5)

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Token": self.api_token}

    def check_connection(self) -> bool:
        try:
            resp = requests.get(
                f"{self.base_url}/v1/health", headers=self._headers(), timeout=10
            )
            return resp.status_code == 200 and bool(resp.json().get("llm_connected"))
        except requests.RequestException:
            return False

    def build_plan_draft(self, plan_text: str, max_retries: int = MAX_RETRIES) -> GeneratedYamlResult:
        return self._post(
            "/v1/generate-draft", {"plan_text": plan_text, "max_retries": max_retries}
        )

    def apply_custom_sbu_choice(self, yaml_data: dict, user_text: str) -> GeneratedYamlResult:
        return self._post(
            "/v1/apply-sbu-choice", {"yaml_data": yaml_data, "user_text": user_text}
        )

    def _post(self, path: str, payload: dict) -> GeneratedYamlResult:
        try:
            resp = requests.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout_sec,
            )
        except requests.Timeout as exc:
            raise PlanApiError(f"API timeout after {self.timeout_sec}s") from exc
        except requests.ConnectionError as exc:
            raise PlanApiError(f"Cannot connect to API at {self.base_url}") from exc

        if resp.status_code == 401:
            raise PlanApiError("Invalid API token", status_code=401)
        if resp.status_code == 429:
            raise PlanApiError("API rate limit exceeded", status_code=429)
        if resp.status_code == 422:
            detail = "Invalid request"
            try:
                detail = resp.json().get("detail", detail)
            except ValueError:
                pass
            raise PlanApiError(detail, status_code=422)
        resp.raise_for_status()

        body = resp.json()
        return GeneratedYamlResult(
            yaml_text=body.get("yaml_text"),
            data=body.get("data"),
            warnings=body.get("warnings", []),
            repairs=body.get("repairs", []),
            ambiguities=body.get("ambiguities", []),
            validation_errors=body.get("validation_errors", []),
            error_categories=body.get("error_categories", {}),
            attempts=body.get("attempts", 0),
        )
