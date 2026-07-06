"""FastAPI app wiring. Route handlers do only: parse request -> build
UnifiedLLMClient -> call the existing plan_service function -> serialize the
result. No YAML/repair/validation logic is reimplemented here; it stays in
plan_service.py / plan_processing.py / plan_validator.py exactly as it does
for the GUI's direct-connection path and the CLI.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException

from .. import plan_service
from ..llm.client import UnifiedLLMClient
from .auth import require_api_token
from .config import ApiSettings, load_api_settings
from .rate_limit import enforce_rate_limit
from .schemas import (
    ApplySbuChoiceRequest,
    GenerateDraftRequest,
    GeneratedYamlResultResponse,
    HealthResponse,
)


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    settings = settings or load_api_settings()
    app = FastAPI(title="FitWeaver Plan API", version="1.0")
    app.state.settings = settings
    app.state.rate_limit_buckets = {}

    def _client() -> UnifiedLLMClient:
        return UnifiedLLMClient(
            model=settings.llm_model,
            base_url=settings.llm_url,
            api_type=settings.llm_api_type,
            request_timeout_sec=settings.llm_timeout_sec,
        )

    @app.post(
        "/v1/generate-draft",
        response_model=GeneratedYamlResultResponse,
        dependencies=[Depends(require_api_token), Depends(enforce_rate_limit)],
    )
    def generate_draft(req: GenerateDraftRequest) -> GeneratedYamlResultResponse:
        result = plan_service.build_plan_draft(
            _client(), req.plan_text, max_retries=req.max_retries
        )
        return GeneratedYamlResultResponse.from_result(result)

    @app.post(
        "/v1/apply-sbu-choice",
        response_model=GeneratedYamlResultResponse,
        dependencies=[Depends(require_api_token), Depends(enforce_rate_limit)],
    )
    def apply_sbu_choice(req: ApplySbuChoiceRequest) -> GeneratedYamlResultResponse:
        try:
            result = plan_service.apply_custom_sbu_choice(_client(), req.yaml_data, req.user_text)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return GeneratedYamlResultResponse.from_result(result)

    @app.get(
        "/v1/health",
        response_model=HealthResponse,
        dependencies=[Depends(require_api_token)],
    )
    def health() -> HealthResponse:
        return HealthResponse(llm_connected=_client().check_connection())

    return app
