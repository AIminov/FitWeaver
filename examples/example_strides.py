"""
Example: Run with Strides Template

Type: Aerobic + Strides
Pace: Aerobic 5:30-5:50/km + fast 100m strides
Purpose: Neuromuscular activation, maintaining speed while building endurance
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from garmin_fit.workout_utils import AERO_F, AERO_S, CD, EASY_F, REC, WU, dist_open, dist_pace, repeat_step


def get_workout_info():
    """Return workout metadata"""
    return {
        "name": "Aerobic 8km + 4x100m Strides",
        "description": "Steady run with short fast strides",
        "type": "aerobic_strides",
        "distance_km": 8.8,
        "estimated_duration_min": 50,
    }


def get_workout_steps():
    """Return list of workout steps"""
    return [
        # Warmup: 1km
        dist_pace(0, 1.0, AERO_S, EASY_F, WU),

        # Main aerobic portion: 6km
        dist_pace(1, 6.0, AERO_F, AERO_S),

        # Stride: 100m fast (3:40-4:00/km pace)
        dist_pace(2, 0.1, "3:40", "4:00"),

        # Recovery: 100m walk/jog
        dist_open(3, 0.1, REC),

        # Repeat strides 4 times
        repeat_step(4, 2, 4),

        # Cooldown: 800m
        dist_open(5, 0.8, CD),
    ]


# For testing this template standalone
if __name__ == "__main__":
    from garmin_fit.workout_utils import save_workout

    info = get_workout_info()
    steps = get_workout_steps()

    output_dir = Path(__file__).parent.parent / "Output_fit"
    output_dir.mkdir(exist_ok=True)

    filepath = output_dir / "test_strides.fit"
    save_workout(str(filepath), info["name"], steps)
    print(f"Generated: {filepath}")
