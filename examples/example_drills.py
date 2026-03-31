"""
Example: Easy Run with Drills Template

Type: Easy + Drills (ВБ + СБУ)
Pace: 6:00-6:30/km + drills section
Purpose: Technical work, running form improvement
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent / "Scripts"))

from workout_utils import (
    dist_pace, dist_open, open_step,
    EASY_F, EASY_S,
    Intensity, WU, CD
)


def get_workout_info():
    """Return workout metadata"""
    return {
        "name": "Easy 5km + Drills",
        "description": "Easy run with drill exercises (use lap button)",
        "type": "easy_drills",
        "distance_km": 5.0,
        "estimated_duration_min": 35,
    }


def get_workout_steps():
    """Return list of workout steps"""
    return [
        # Warmup: 1km easy
        dist_pace(0, 1.0, EASY_F, EASY_S, WU),

        # Main: 3km easy
        dist_pace(1, 3.0, EASY_F, EASY_S),

        # Drills section: open step (press lap when drills complete)
        # User does: high knees, butt kicks, bounding, strides, etc.
        open_step(2),

        # Cooldown: 1km
        dist_open(3, 1.0, CD),
    ]


# For testing this template standalone
if __name__ == "__main__":
    from workout_utils import save_workout
    import os

    info = get_workout_info()
    steps = get_workout_steps()

    output_dir = Path(__file__).parent.parent / "Output_fit"
    output_dir.mkdir(exist_ok=True)

    filepath = output_dir / "test_drills.fit"
    save_workout(str(filepath), info["name"], steps)
    print(f"Generated: {filepath}")
