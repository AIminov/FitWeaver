"""
Example: Interval Training Template

Type: Intervals (ИТ - Интервальная Тренировка)
Pace: Fast intervals (4:00-4:20/km) with recovery
Purpose: VO2max development, speed endurance
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from garmin_fit.workout_utils import CD, REC, WU, dist_open, dist_pace, repeat_step


def get_workout_info():
    """Return workout metadata"""
    return {
        "name": "6x800m Intervals",
        "description": "6 repetitions of 800m at fast pace with 400m recovery",
        "type": "intervals",
        "distance_km": 10.0,  # approximate total
        "estimated_duration_min": 50,
    }


def get_workout_steps():
    """Return list of workout steps"""
    return [
        # Warmup: 2km easy
        dist_open(0, 2.0, WU),

        # Interval: 800m at 4:10-4:20/km
        dist_pace(1, 0.8, "4:10", "4:20"),

        # Recovery: 400m jog
        dist_open(2, 0.4, REC),

        # Repeat the interval+recovery 6 times
        repeat_step(3, 1, 6),

        # Cooldown: 1km easy
        dist_open(4, 1.0, CD),
    ]


# For testing this template standalone
if __name__ == "__main__":
    from garmin_fit.workout_utils import save_workout

    info = get_workout_info()
    steps = get_workout_steps()

    output_dir = Path(__file__).parent.parent / "Output_fit"
    output_dir.mkdir(exist_ok=True)

    filepath = output_dir / "test_intervals.fit"
    save_workout(str(filepath), info["name"], steps)
    print(f"Generated: {filepath}")
