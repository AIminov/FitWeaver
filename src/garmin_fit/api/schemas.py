"""Pydantic request/response models. Deliberately does NOT re-validate
yaml_data against plan_schema.WorkoutPlanSchema -- plan_service.apply_custom_sbu_choice
already calls repair_plan_data + validate_plan_data internally, so a second
schema-level validation here would reject partially-invalid-but-repairable
data that plan_service already handles correctly, and would drift from what
plan_service actually guarantees.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..llm.client import GeneratedYamlResult


class GenerateDraftRequest(BaseModel):
    plan_text: str = Field(min_length=1)
    max_retries: int = Field(default=3, ge=1, le=10)


class ApplySbuChoiceRequest(BaseModel):
    yaml_data: dict[str, Any]
    user_text: str = Field(min_length=1)


class GeneratedYamlResultResponse(BaseModel):
    yaml_text: str | None = None
    data: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    repairs: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    error_categories: dict[str, list[str]] = Field(default_factory=dict)
    attempts: int = 0

    @classmethod
    def from_result(cls, result: GeneratedYamlResult) -> "GeneratedYamlResultResponse":
        return cls(
            yaml_text=result.yaml_text,
            data=result.data,
            warnings=result.warnings,
            repairs=result.repairs,
            ambiguities=result.ambiguities,
            validation_errors=result.validation_errors,
            error_categories=result.error_categories,
            attempts=result.attempts,
        )


class HealthResponse(BaseModel):
    llm_connected: bool
