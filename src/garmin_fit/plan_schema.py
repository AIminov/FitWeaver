"""
Pydantic v2 schema models for YAML workout plan validation.

Performs structural and type-level checks at the YAML input boundary.
Semantic checks requiring positional context (e.g. back_to_offset < step index)
remain in plan_validator.py.

The top-level WorkoutPlanSchema can also generate a JSON Schema for the LLM prompt:

    from garmin_fit.plan_schema import WorkoutPlanSchema
    schema = WorkoutPlanSchema.model_json_schema()
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .plan_domain import KNOWN_PACE_CONSTANTS

# ---------------------------------------------------------------------------
# Shared config and helpers
# ---------------------------------------------------------------------------

_EXTRA_ALLOW = ConfigDict(extra="allow", str_strip_whitespace=True)


def _is_valid_pace(value: Any) -> bool:
    if isinstance(value, str) and value in KNOWN_PACE_CONSTANTS:
        return True
    if not isinstance(value, str):
        return False
    parts = value.split(":")
    if len(parts) != 2:
        return False
    if not (parts[0].isdigit() and parts[1].isdigit()):
        return False
    mm, ss = int(parts[0]), int(parts[1])
    return mm >= 1 and 0 <= ss <= 59


def _pace_to_seconds(pace: str) -> int:
    mm, ss = pace.split(":")
    return int(mm) * 60 + int(ss)


def _check_pace_ordering(pace_fast: str, pace_slow: str) -> None:
    """Raise ValueError if pace_fast is not strictly faster than pace_slow."""
    if (
        pace_fast not in KNOWN_PACE_CONSTANTS
        and pace_slow not in KNOWN_PACE_CONSTANTS
    ):
        if _pace_to_seconds(pace_fast) >= _pace_to_seconds(pace_slow):
            raise ValueError(
                f"pace_fast '{pace_fast}' must be faster (lower) than"
                f" pace_slow '{pace_slow}'"
            )


# ---------------------------------------------------------------------------
# Drill schema
# ---------------------------------------------------------------------------

class DrillSchema(BaseModel):
    model_config = _EXTRA_ALLOW

    name: str
    seconds: int = Field(default=60, gt=0)
    reps: int = Field(default=2, gt=0)

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("drill name must not be empty")
        return v


# ---------------------------------------------------------------------------
# Step schemas — one model per canonical step type
# ---------------------------------------------------------------------------

class DistHrStep(BaseModel):
    model_config = _EXTRA_ALLOW

    type: Literal["dist_hr"]
    km: float = Field(gt=0)
    hr_low: int = Field(gt=0, le=250)
    hr_high: int = Field(gt=0, le=250)
    intensity: Optional[str] = None

    @model_validator(mode="after")
    def check_hr_ordering(self) -> DistHrStep:
        if self.hr_low >= self.hr_high:
            raise ValueError(
                f"hr_low ({self.hr_low}) must be less than hr_high ({self.hr_high})"
            )
        return self


class TimeHrStep(BaseModel):
    model_config = _EXTRA_ALLOW

    type: Literal["time_hr"]
    seconds: int = Field(gt=0)
    hr_low: int = Field(gt=0, le=250)
    hr_high: int = Field(gt=0, le=250)
    intensity: Optional[str] = None

    @model_validator(mode="after")
    def check_hr_ordering(self) -> TimeHrStep:
        if self.hr_low >= self.hr_high:
            raise ValueError(
                f"hr_low ({self.hr_low}) must be less than hr_high ({self.hr_high})"
            )
        return self


class DistPaceStep(BaseModel):
    model_config = _EXTRA_ALLOW

    type: Literal["dist_pace"]
    km: float = Field(gt=0)
    pace_fast: str
    pace_slow: str
    intensity: Optional[str] = None

    @field_validator("pace_fast", "pace_slow")
    @classmethod
    def validate_pace_format(cls, v: str) -> str:
        if not _is_valid_pace(v):
            raise ValueError(
                f"invalid pace '{v}', expected MM:SS (e.g. '4:30') or a pace constant"
            )
        return v

    @model_validator(mode="after")
    def check_pace_ordering(self) -> DistPaceStep:
        _check_pace_ordering(self.pace_fast, self.pace_slow)
        return self


class TimePaceStep(BaseModel):
    model_config = _EXTRA_ALLOW

    type: Literal["time_pace"]
    seconds: int = Field(gt=0)
    pace_fast: str
    pace_slow: str
    intensity: Optional[str] = None

    @field_validator("pace_fast", "pace_slow")
    @classmethod
    def validate_pace_format(cls, v: str) -> str:
        if not _is_valid_pace(v):
            raise ValueError(
                f"invalid pace '{v}', expected MM:SS (e.g. '4:30') or a pace constant"
            )
        return v

    @model_validator(mode="after")
    def check_pace_ordering(self) -> TimePaceStep:
        _check_pace_ordering(self.pace_fast, self.pace_slow)
        return self


class DistOpenStep(BaseModel):
    model_config = _EXTRA_ALLOW

    type: Literal["dist_open"]
    km: float = Field(gt=0)
    intensity: Optional[str] = None


class TimeStepStep(BaseModel):
    model_config = _EXTRA_ALLOW

    type: Literal["time_step"]
    seconds: int = Field(gt=0)
    intensity: Optional[str] = None


class OpenStep(BaseModel):
    model_config = _EXTRA_ALLOW

    type: Literal["open_step"]
    intensity: Optional[str] = None


class RepeatStep(BaseModel):
    model_config = _EXTRA_ALLOW

    type: Literal["repeat"]
    back_to_offset: int = Field(ge=0)
    count: int = Field(gt=0)


class SbuBlockStep(BaseModel):
    model_config = _EXTRA_ALLOW

    type: Literal["sbu_block"]
    drills: Optional[list[DrillSchema]] = None

    @field_validator("drills")
    @classmethod
    def drills_not_empty(
        cls, v: Optional[list[DrillSchema]]
    ) -> Optional[list[DrillSchema]]:
        if v is not None and len(v) == 0:
            raise ValueError("drills must be a non-empty list when provided")
        return v


# ---------------------------------------------------------------------------
# Discriminated union on the `type` field
# ---------------------------------------------------------------------------

WorkoutStepUnion = Annotated[
    Union[
        DistHrStep,
        TimeHrStep,
        DistPaceStep,
        TimePaceStep,
        DistOpenStep,
        TimeStepStep,
        OpenStep,
        RepeatStep,
        SbuBlockStep,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Workout and plan schemas
# ---------------------------------------------------------------------------

class WorkoutSchema(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    filename: str
    name: str
    desc: Optional[str] = None
    type_code: Optional[str] = None
    distance_km: Optional[float] = None
    estimated_duration_min: Optional[float] = None
    steps: list[WorkoutStepUnion] = Field(min_length=1)

    @field_validator("filename", "name")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v


class WorkoutPlanSchema(BaseModel):
    """
    Top-level plan schema. Use model_json_schema() to generate JSON Schema
    for inclusion in LLM prompts.
    """

    model_config = ConfigDict(extra="allow")

    workouts: list[WorkoutSchema] = Field(min_length=1)

    @model_validator(mode="after")
    def check_unique_filenames(self) -> WorkoutPlanSchema:
        seen: set[str] = set()
        duplicates: list[str] = []
        for w in self.workouts:
            if w.filename in seen:
                duplicates.append(w.filename)
            seen.add(w.filename)
        if duplicates:
            raise ValueError(f"duplicate filenames: {duplicates}")
        return self
