# LLM Validation System: Complete Guide

This document explains how the Garmin FIT system now enforces strict validation at every stage of LLM-based YAML generation.

## Overview

The LLM validation system has **three complementary layers**:

1. **Structured Contract** — Rules encoded in machine-readable format
2. **Learning Examples** — Correct and incorrect examples for LLM training
3. **Runtime Validation** — Automatic checking at generation and build time

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    User Text Plan                           │
└────────────────────┬────────────────────────────────────────┘
                     │
                     v
┌─────────────────────────────────────────────────────────────┐
│           LLM Generation Pipeline                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 1. Load Prompt with:                                 │   │
│  │    - LLM Contract (validation_rules)                 │   │
│  │    - Strict Examples (correct + FAILURE cases)       │   │
│  │    - Contract forbidden_patterns (negatives)         │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 2. LLM Generates YAML using:                         │   │
│  │    - Contract rules (enforce naming, ranges, etc.)   │   │
│  │    - Failure examples (avoid common mistakes)        │   │
│  │    - Forbidden patterns (what not to emit)           │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 3. Runtime Validation:                               │   │
│  │    - Parse YAML                                      │   │
│  │    - Call plan_validator.validate_plan_data()        │   │
│  │    - If errors: Return error_categories to LLM       │   │
│  │    - If OK: Return validated YAML                    │   │
│  └──────────────────────────────────────────────────────┘   │
└────────────────────┬────────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │ Errors                 │ Success
        v                         v
   ┌─────────────┐          ┌──────────────┐
   │ Return to   │          │ Build FIT    │
   │ LLM for     │          │ from Plan    │
   │ retry       │          └──────────────┘
   └─────────────┘
```

## Layer 1: Structured Contract

**File**: `src/garmin_fit/llm/llm_contract.yaml`

The contract defines all validation rules in structured YAML that the LLM prompt builder can easily render.

### Key Sections:

> The snippets below are quoted from `src/garmin_fit/llm/llm_contract.yaml`. If they
> ever disagree with that file, the file wins — it is what the prompt actually renders.

#### output
```yaml
output:
  root_key: workouts
  skip_rest_days: true
```

The per-workout key list is not part of the contract; it is enforced by
`plan_schema.WorkoutSchema` (`filename`, `name`, `desc`, `type_code`, `distance_km`,
`estimated_duration_min`, `steps`).

#### naming
```yaml
naming:
  known_date_pattern: "W{calendar_week}_{MM-DD}_{DayName}_{Type}_{Details}"
  calendar_week_rule: "ISO 8601 week number for the source year; if absent use the current year"
```

The `N{order}_...` fallback for undated workouts and the list of recognised source date
forms (`01.12.2025`, `1 Jan`, `8.03 (вс)`, …) live in `plan_processing.py`, not in the
contract — see `docs/PROJECT_FLOW.md` under "Нормализация имен тренировок".

#### allowed_type_codes
```yaml
allowed_type_codes:
  - easy
  - aerobic
  - tempo
  - intervals
  - long
  - recovery
  - progression
  - threshold
  - marathon_pace
  - race
  - mixed
  - easy_drills
```

#### allowed_intensity
```yaml
allowed_intensity:
  - active
  - warmup
  - cooldown
  - recovery
```

#### step_types
Defines required/optional fields for each step type:
```yaml
step_types:
  dist_pace:
    required: [type, km, pace_fast, pace_slow]
    optional: [intensity]
    fit_duration: DISTANCE
    fit_target: SPEED
  dist_hr:
    required: [type, km, hr_low, hr_high]
    optional: [intensity]
  # ... and 6 more types
```

#### validation_rules
```yaml
validation_rules:
  filename_name:
    - filename and name MUST be identical
    - all filenames MUST be unique
    - must follow pattern: W{week}_{MM-DD}_{DayName}_{Type}_{Details}

  distance_time:
    - distance_km MUST be > 0
    - seconds MUST be > 0

  heart_rate:
    - hr_low < hr_high (CRITICAL!)
    - 30 ≤ hr_low, hr_high ≤ 240
    - typical zones defined

  # ... pace_format, intensity, sbu_drills, repeat_block, etc.
```

### How It's Used:

In `src/garmin_fit/llm/prompt.py`:
```python
def render_llm_contract(contract: dict[str, Any]) -> str:
    # Renders contract into human-readable prompt sections:
    # - STRICT YAML CONTRACT
    # - STEP SCHEMA
    # - FORBIDDEN OUTPUT PATTERNS
    # - etc.
```

The rendered contract is included in every LLM system prompt.

## Layer 2: Learning Examples

**File**: `src/garmin_fit/llm/strict_examples.yaml`

Contains two types of examples:

### Correct Examples (10 examples)

Shows LLM how to properly handle different workout types:

```yaml
examples:
  - id: intervals_pace
    tags: [intervals, pace, repeat, 800]
    match_any: [интервалы, 800, повтор, interval, x800, ускорение]
    input: |
      14.04.2026 (вт)
      Интервалы 6x800м
      Разминка: 2 км (5:45-6:00)
      6x800м по 4:20-4:30, восстановление 400 м трусцой (5:30-6:00)
      Заминка: 1 км (5:45-6:00)
      Итого: ~10.4 км, 55 мин
    output: |
      workouts:
        - filename: W15_04-14_Tue_Intervals_6x800m
          name: W15_04-14_Tue_Intervals_6x800m
          desc: "Classic intervals: 6x800m at tempo pace with jogging recovery"
          type_code: intervals
          distance_km: 10.4
          estimated_duration_min: 55
          steps:
            - type: dist_pace
              km: 2.0
              pace_fast: "5:45"
              pace_slow: "6:00"
              intensity: warmup
            # ... (rest of steps)
            - type: repeat
              back_to_offset: 1
              count: 6
```

### Failure Examples (10+ examples)

Shows LLM what NOT to do and how to fix errors:

```yaml
failure_examples:
  - id: fail_hr_inverted
    tags: [failure, hr, inverted, critical]
    error: "hr_low >= hr_high"
    input: "User text with HR values written backwards"
    wrong_output: |
      hr_low: 150      # ❌ ERROR: Must be < hr_high!
      hr_high: 140
    correct_output: |
      hr_low: 140      # ✓ Fixed: hr_low < hr_high
      hr_high: 150
    fix_rule: "CRITICAL: hr_low MUST be < hr_high. Always check!"

  - id: fail_unquoted_pace
    tags: [failure, pace, format]
    error: "pace must be quoted string MM:SS"
    wrong_output: |
      pace_fast: 5:00    # ❌ ERROR: Must be quoted!
    correct_output: |
      pace_fast: "5:00"  # ✓ Quoted string
    fix_rule: "Pace MUST be quoted strings: \"MM:SS\", never bare numbers!"

  # ... (8 more failure examples covering all common errors)
```

### How Examples Are Selected:

In `src/garmin_fit/llm/prompt.py`:
```python
def load_strict_examples(
    source_text: str | None = None,
    max_examples: int = 2,
) -> str:
    # Loads examples from strict_examples.yaml
    # - Selects most relevant based on source_text keywords
    # - Includes both correct and failure examples
    # - Limited to max_examples to keep prompt size reasonable
```

The selected examples are included in the LLM system prompt.

## Layer 3: Runtime Validation

**File**: `src/garmin_fit/llm/client.py` (line 632)

After LLM generates YAML, runtime validation automatically checks it:

```python
def generate_yaml(user_text: str, ...) -> GeneratedYamlResult:
    # ... LLM generates YAML ...

    # Parse the YAML
    data = yaml.safe_load(llm_output)

    # Repair common issues
    repaired_data, repair_notes = repair_plan_data(data)

    # CRITICAL: Validate against SDK rules
    errors, warnings = validate_plan_data_detailed(
        repaired_data,
        enforce_filename_name_match=True,
    )

    if errors:
        # Return validation errors to caller
        return GeneratedYamlResult(
            success=False,
            errors=error_messages,
            validation_errors=error_messages,
            error_categories=group_issues_by_category(errors),
        )
    else:
        # Return validated YAML
        return GeneratedYamlResult(
            success=True,
            data=repaired_data,
        )
```

### Validation Stages:

1. **YAML Parsing**: Ensure valid YAML syntax
2. **Repair**: Fix known issues (whitespace, name normalization)
3. **Validation**: Check against all SDK rules:
   - Field presence and types
   - Value ranges (HR 30-240, km > 0)
   - Format requirements (pace as "MM:SS")
   - Semantic rules (hr_low < hr_high, unique names)
   - Step type constraints (no mixing HR and pace)
   - Repeat bounds checking
   - SBU drill name length

### Error Reporting:

Validation errors are grouped by category:
```python
error_categories = {
    "hr_range": ["hr_low must be >= 30", "hr_high must be <= 240"],
    "naming": ["filename and name must be identical"],
    "heart_rate": ["hr_low must be < hr_high"],
    "repeat": ["back_to_offset must be < current step index"],
    # ... etc.
}
```

These are returned to the LLM (in some modes) for retry with feedback.

## Layer 4: Pre-submission rules in the contract

**File**: `src/garmin_fit/llm/llm_contract.yaml` (rendered into the prompt by
`src/garmin_fit/llm/prompt.py`)

> **Historical note.** Up to v8.4 this was a literal 16-point "VALIDATION CHECKLIST"
> block hardcoded in `prompt.py`. It no longer exists there — the rules moved into the
> machine-readable contract, where there are now more of them and where the validator
> and the prompt read from one file instead of two hand-synced lists.

The contract carries the rules in two sections. `validation_rules` groups the positive
requirements:

| Group | Covers |
|---|---|
| `naming` | filename pattern `W{week}_{MM-DD}_{Day}_{Type}_{Details}`, uniqueness, `filename == name` |
| `distances` | every `km` strictly positive |
| `durations` | every `seconds` strictly positive |
| `heart_rate` | `hr_low < hr_high`, range 30–240, upper-only cap becomes `hr_low: 80` |
| `pace_format` | quoted `"MM:SS"`, `MM >= 1`, `SS` in `00-59` |
| `intensity` | only `active` / `warmup` / `cooldown` / `recovery` |
| `sbu_drills` | drill names ≤ 12 chars, fields `{name, seconds, reps}` only, no `type` |
| `repeat_block` | `back_to_offset` is a 0-based index below the current step index |

`forbidden_patterns` lists the same ground as negatives (mixing `hr_*` with `pace_*`,
`type` inside drills, zero/negative values, unquoted pace, and so on), which gives the
model both framings of each rule.

### Nested repeats

Nested `repeat` blocks are allowed, and the contract says so. They are how sets are
expressed — "3 sets of 4x400m" is an inner repeat over the 400m group plus an outer
repeat that spans it. What the validator rejects is repeat ranges that *cross* without
one containing the other: their replay order is ambiguous and cannot be represented as
a tree of Garmin repeat groups.

Until 2026-09-07 the contract forbade nesting outright. That rule came from the v8.4
prompt checklist and outlived its reason: `plan_validator.py` had already been taught
containment-vs-crossing, and the Garmin REST mapper emits nested `RepeatGroupDTO`s. The
practical cost was that a perfectly ordinary set workout could not be expressed, so the
model flattened it and lost the between-sets recovery.

## Integration with Full Pipeline

When the user runs the GUI build action or `python -m garmin_fit.cli run`:

```
Pipeline steps:
  1) Validate YAML (SDK rules)           ← Uses validation_rules from contract
  2) Build FIT files (direct builder)    ← Direct builder from YAML
  3) Validate FIT files                  ← FIT-specific validation
  4) Auto-archive on success
```

The validation happens at **two levels**:
1. **Before building**: Explicit validation of YAML
2. **During building**: Embedded validation in build_from_plan.py

## Best Practices for LLM Generation

### For Users Providing Text Plans:

1. Be explicit about pace vs. HR targets
2. Include distance and time estimates
3. Specify heart rate zones clearly (e.g., "пульс 135-150")
4. Use standard terminology (разминка, заминка, трусца, etc.)

### For LLM Developers:

1. Keep the rules in `llm_contract.yaml`, not in prompt string literals
2. Load both correct AND failure examples
3. Render the full llm_contract in the system prompt
4. Handle validation errors gracefully (show error categories to user/LLM)
5. Log which validation rules are most frequently violated

## Testing the System

### Test LLM Generation + Validation:

```bash
python -m garmin_fit.llm.request_cli \
  --api openai \
  --url http://127.0.0.1:1234/v1 \
  --model qwen3.8-27b
```

If validation fails, error categories are returned.

### Test Contract Rendering:

```bash
python -c "
from garmin_fit.llm.prompt import render_llm_contract, load_llm_contract
contract = load_llm_contract()
print(render_llm_contract(contract))
"
```

### Test Examples Loading:

```bash
python -c "
from garmin_fit.llm.prompt import load_strict_examples
print(load_strict_examples())
"
```

### Validate Generated YAML:

```bash
python -m garmin_fit.cli validate-yaml --plan Plan/plan.yaml
```

## Files Reference

| File | Purpose |
|------|---------|
| `src/garmin_fit/llm/llm_contract.yaml` | Machine-readable validation rules and step schema |
| `src/garmin_fit/llm/strict_examples.yaml` | Correct examples (10) + Failure examples (10+) |
| `src/garmin_fit/llm/prompt.py` | Renders contract and examples into the system prompt |
| `src/garmin_fit/plan_validator.py` | Runtime validation logic (source of truth) |
| `src/garmin_fit/plan_domain.py` | Constants: STEP_REQUIRED_FIELDS, ALLOWED_INTENSITY, etc. |
| `docs/YAML_GUIDE.md` | Complete YAML syntax reference and human-readable LLM guide |

## Key Takeaways

✅ **Three-Layer Validation**: Contract → Examples → Runtime
✅ **Structured Rules**: LLM contract in YAML format
✅ **Learning by Example**: Both correct and failure cases
✅ **Rules in One Place**: contract drives both the prompt and the reviewer's expectations
✅ **Automatic Enforcement**: Runtime validation in pipeline
✅ **Comprehensive Training**: ~30 examples covering all workout types and error scenarios

This system significantly reduces YAML generation errors by providing:
- Clear rules (contract)
- Practical examples (correct and failure cases)
- Negative framing of every rule (`forbidden_patterns`)
- Automatic safety checks (runtime validation)
