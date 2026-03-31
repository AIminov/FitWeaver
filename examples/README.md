# Garmin FIT Workout Generator - Instructions

This directory contains example workout templates and documentation for creating custom Garmin FIT workout files.

Primary package-first interfaces:

```bash
python -m garmin_fit.cli run
python -m garmin_fit.validate_cli --plan Plan/plan.yaml
python -m garmin_fit.check_fit Output_fit/
python -m garmin_fit.legacy_cli templates --plan Plan/plan.yaml
```

`Scripts.*` commands remain available only as compatibility paths.

## Overview

The workout generator uses a three-stage pipeline:

```
Plan/ (training plan)
    ↓
Workout_templates/ (Python files with workout definitions)
    ↓
Output_fit/ (FIT files ready for Garmin watch)
```

## Quick Start

### 1. Complete Workflow

```bash
cd Final/
python get_fit.py
```

This will:
1. Check prerequisites
2. Look for workout templates
3. Build FIT files with unique file_id values
4. Validate generated files
5. Report results

### 2. Validation Only

```bash
python get_fit.py --validate-only
```

Validates existing FIT files in Output_fit/ without regenerating them.

### 3. Build Only

```bash
python get_fit.py --build-only
```

Builds FIT files from existing templates (skips template generation).

## Creating Workout Templates

### Template Structure

Each workout template is a Python file with two required functions:

```python
def get_workout_info():
    """Return workout metadata"""
    return {
        "name": "Workout Name",
        "description": "Description",
        "type": "easy|intervals|tempo|long|drills",
        "distance_km": 10.0,
        "estimated_duration_min": 60,
    }

def get_workout_steps():
    """Return list of workout steps"""
    return [
        # List of WorkoutStepMessage objects
    ]
```

### Example Templates

See the example templates in this directory:

- **example_easy_run.py** - Simple recovery run
- **example_intervals.py** - Interval training with repeats
- **example_tempo.py** - Threshold/tempo run
- **example_long_run.py** - Long steady run with progression
- **example_drills.py** - Easy run with drill section
- **example_strides.py** - Aerobic run with fast strides

### Testing Templates

You can test a template standalone:

```bash
cd Final/Instructions/
python example_intervals.py
```

This generates a test FIT file in Output_fit/ for verification.

## Workout Building Blocks

Import from `garmin_fit.workout_utils`:

```python
from garmin_fit.workout_utils import (
    # Distance steps
    dist_pace,   # Distance with pace target
    dist_open,   # Distance without pace target

    # Time steps
    time_step,   # Time-based step (usually recovery)

    # Special steps
    open_step,   # Lap button press (for drills)
    repeat_step, # Repeat previous steps

    # Pace constants
    EASY_F, EASY_S,   # Easy pace (6:00-6:30/km)
    AERO_F, AERO_S,   # Aerobic (5:30-5:50/km)
    LONG_F, LONG_S,   # Long run (5:30-6:00/km)
    TEMPO_F, TEMPO_S, # Tempo (4:50-5:10/km)

    # Intensity shortcuts
    WU, CD, ACT, REC, # Warmup, Cooldown, Active, Recovery

    # Full intensity enum
    Intensity,
)
```

### Common Workout Patterns

#### 1. Simple Easy Run

```python
def get_workout_steps():
    return [
        dist_pace(0, 5.0, EASY_F, EASY_S),
    ]
```

#### 2. Warmup + Main + Cooldown

```python
def get_workout_steps():
    return [
        dist_open(0, 2.0, WU),           # 2km warmup
        dist_pace(1, 5.0, TEMPO_F, TEMPO_S),  # 5km tempo
        dist_open(2, 1.0, CD),           # 1km cooldown
    ]
```

#### 3. Intervals with Repeats

```python
def get_workout_steps():
    return [
        dist_open(0, 2.0, WU),           # Warmup
        dist_pace(1, 1.0, "4:00", "4:10"),    # 1km fast
        dist_open(2, 0.4, REC),          # 400m recovery
        repeat_step(3, 1, 6),            # Repeat steps 1-2 six times
        dist_open(4, 1.0, CD),           # Cooldown
    ]
```

#### 4. Progressive Run

```python
def get_workout_steps():
    return [
        dist_pace(0, 1.0, LONG_S, EASY_S, WU),
        dist_pace(1, 5.0, "5:35", "5:45"),    # Start easy
        dist_pace(2, 4.0, "5:20", "5:30"),    # Get faster
        dist_pace(3, 3.0, "5:00", "5:10"),    # Finish strong
    ]
```

#### 5. Run with Drills

```python
def get_workout_steps():
    return [
        dist_pace(0, 1.0, EASY_F, EASY_S, WU),
        dist_pace(1, 3.0, EASY_F, EASY_S),
        open_step(2),                    # Press lap after drills
        dist_open(3, 1.0, CD),
    ]
```

#### 6. Run with Strides

```python
def get_workout_steps():
    return [
        dist_pace(0, 1.0, AERO_S, EASY_F, WU),
        dist_pace(1, 6.0, AERO_F, AERO_S),
        dist_pace(2, 0.1, "3:40", "4:00"),    # 100m stride
        dist_open(3, 0.1, REC),               # 100m recovery
        repeat_step(4, 2, 4),                 # 4 strides
        dist_open(5, 0.8, CD),
    ]
```

## Unit Conversions

The FIT format uses specific units:

### Distance
```python
km_to_dist(2.0)  # 2km = 200 FIT units (meters / 10)
```

### Time
```python
sec_to_time(60)  # 60 seconds = 60000 FIT units (milliseconds)
```

### Pace (Speed)
```python
pace_to_speed("5:00")  # 5:00/km = 200000 FIT units (m/s * 1000)
```

**Important**: Slower pace = lower speed value
- `custom_target_value_low` = slower pace (e.g., "5:30")
- `custom_target_value_high` = faster pace (e.g., "5:00")

## Intensity Types

```python
Intensity.WARMUP    # Warmup phase
Intensity.ACTIVE    # Main work
Intensity.RECOVERY  # Recovery between intervals
Intensity.COOLDOWN  # Cooldown phase
```

## Step Types

### Duration Types

```python
WorkoutStepDuration.DISTANCE  # Distance-based (km)
WorkoutStepDuration.TIME      # Time-based (seconds)
WorkoutStepDuration.OPEN      # Lap button press
WorkoutStepDuration.REPEAT_UNTIL_STEPS_CMPLT  # Repeat
```

### Target Types

```python
WorkoutStepTarget.SPEED  # Pace target (m/s * 1000)
WorkoutStepTarget.OPEN   # No target
WorkoutStepTarget.HEART_RATE  # HR target (not commonly used)
```

## File Naming Convention

Template files should follow this pattern:

```
W{week}_{month}-{day}_{weekday}_{type}_{description}.py
```

Examples:
- `W01_02-10_tue_aero_7k.py` - Week 1, Feb 10, Tuesday, Aerobic 7km
- `W03_02-27_fri_intervals_5x1000.py` - Week 3, Feb 27, Friday, 5×1000m
- `W12_05-03_sun_HALF_MARATHON.py` - Race day

## Common Issues

### Issue: "Serial number is default (12345)"

**Cause**: Template is using default serial number

**Fix**: Don't set serial_number in templates. The build script assigns unique values automatically.

### Issue: "Step count mismatch"

**Cause**: `num_valid_steps` doesn't match actual step count

**Fix**: Don't set `num_valid_steps` manually. Use `save_workout()` which calculates it automatically.

### Issue: "Pace target backwards"

**Symptom**: Watch shows incorrect pace zone

**Cause**: `custom_target_value_low` and `high` are swapped

**Fix**: Remember: slower pace = lower speed value
```python
dist_pace(0, 5.0, "5:00", "5:30")  # Correct: 5:00-5:30/km
# Low = pace_to_speed("5:30") = slower
# High = pace_to_speed("5:00") = faster
```

## Validation

### Validate a Single File

```bash
python -m garmin_fit.check_fit Output_fit/workout.fit
```

### Validate All Files

```bash
python -m garmin_fit.check_fit Output_fit/
```

### Strict Validation

```bash
python -m garmin_fit.check_fit --strict Output_fit/
```

Strict mode treats warnings as errors.

## Dependencies

```bash
pip install fit_tool garmin-fit-sdk
```

## Advanced: Using Claude AI

To generate templates automatically from the training plan:

```bash
python -m garmin_fit.legacy_cli templates --plan Plan/plan.yaml
```

Or ask Claude Code directly:
```
"Please read the training plan in Final/Plan/ and generate workout
templates in Final/Workout_templates/ based on the examples in
Final/Instructions/"
```

## Loading Workouts onto Garmin Watch

1. Connect watch via USB
2. Copy FIT files from `Final/Output_fit/` to watch at `GARMIN/NewFiles/`
3. Safely eject watch
4. Wait 1-2 minutes for import
5. Check: **Run → Training → Workouts → My Workouts**

## Troubleshooting

### Only One Workout Appears on Watch

**Cause**: Files have identical `file_id` values

**Fix**: Run `build_fits.py` which assigns unique serial numbers automatically

### Watch Shows "Error Uploading Workout"

**Cause**: Invalid FIT file structure

**Fix**: Run `python -m garmin_fit.check_fit Output_fit/` to identify issues

### "No templates found"

**Cause**: Workout_templates/ directory is empty

**Fix**: Generate templates using Claude AI or copy examples from Instructions/

## Support

For issues or questions:
1. Check logs in `Logs/` directory
2. Run validation: `python get_fit.py --validate-only`
3. Review CLAUDE.md in parent directory
4. Check example templates in this directory

## References

- [Garmin FIT SDK Documentation](https://developer.garmin.com/fit/overview/)
- [fit_tool Python Library](https://pypi.org/project/fit_tool/)
- [garmin-fit-sdk Python Library](https://pypi.org/project/garmin-fit-sdk/)
