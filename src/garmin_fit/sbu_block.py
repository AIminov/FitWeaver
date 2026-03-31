"""
СБУ (Special Running Drills) block helper.

Generates workout steps for a configurable СБУ block.
Each drill = N repetitions of (active time step + open recovery step).

Default drills (used when no custom drills provided):
1. Бег с высоким подниманием бедра — 2×60сек
2. Захлёст голени — 2×60сек
3. Бег на прямых ногах — 2×60сек
4. Многоскоки — 2×60сек
5. Ускорения — 4×60сек

Total default steps: (2+2+2+2+4) × 2 = 24 steps.
"""

from .workout_utils import time_step, open_step, sec_to_time, Intensity
from fit_tool.profile.messages.workout_step_message import WorkoutStepMessage
from fit_tool.profile.profile_type import (
    WorkoutStepDuration, WorkoutStepTarget,
)

ACT = Intensity.ACTIVE
REC = Intensity.RECOVERY

# Default drill set — can be overridden via drills parameter
DEFAULT_DRILLS = [
    {"name": "Выс.бедро", "seconds": 60, "reps": 2},
    {"name": "Захлест", "seconds": 60, "reps": 2},
    {"name": "Прям.ноги", "seconds": 60, "reps": 2},
    {"name": "Многоскоки", "seconds": 60, "reps": 2},
    {"name": "Ускорение", "seconds": 60, "reps": 4},
]


def _named_time_step(idx, seconds, name, note=None, intensity=ACT):
    """Create a time-based step with a display name."""
    s = time_step(idx, seconds, intensity)
    s.wkt_step_name = name
    s.notes = note or name
    return s


def _named_open_step(idx, name, note=None, intensity=REC):
    """Create an open/lap-button step with a display name."""
    s = open_step(idx, intensity)
    s.wkt_step_name = name
    s.notes = note or name
    return s


def sbu_block(start_idx, drills=None):
    """
    Generate СБУ block steps starting at given index.

    Args:
        start_idx: Starting step index
        drills: Optional list of drill dicts with keys:
                - name (str): Short display name (max 12 chars for Garmin)
                - seconds (int): Duration per rep in seconds (default: 60)
                - reps (int): Number of repetitions (default: 2)
                If None, uses DEFAULT_DRILLS.

    Returns:
        tuple: (steps_list, next_idx)
    """
    if drills is None:
        drills = DEFAULT_DRILLS

    steps = []
    idx = start_idx

    for drill in drills:
        name = drill["name"]
        seconds = drill.get("seconds", 60)
        reps = drill.get("reps", 2)

        for i in range(1, reps + 1):
            steps.append(_named_time_step(idx, seconds, f"{name} {i}/{reps}", intensity=ACT))
            idx += 1
            steps.append(_named_open_step(idx, "Recovery", intensity=REC))
            idx += 1

    return steps, idx
