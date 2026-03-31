"""
Example: Long Run Template

Type: Long Run (ДБ - Длительный Бег)
Pace: 5:30-6:00/km (comfortable aerobic pace)
Purpose: Build aerobic endurance, practice race nutrition/pacing
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent / "Scripts"))

from workout_utils import (
    dist_pace, dist_open,
    LONG_F, LONG_S, EASY_S,
    Intensity, WU, CD
)


def get_workout_info():
    """Return workout metadata"""
    return {
        "name": "Long Run 18km",
        "description": "Long steady run with progression finish",
        "type": "long",
        "distance_km": 18.0,
        "estimated_duration_min": 105,
    }


def get_workout_steps():
    """Return list of workout steps"""
    return [
        # Warmup: 1km easy
        dist_pace(0, 1.0, LONG_S, EASY_S, WU),

        # Main portion: 12km at long run pace
        dist_pace(1, 12.0, LONG_F, LONG_S),

        # Progression: 5km at faster pace (tempo zone)
        dist_pace(2, 5.0, "5:10", LONG_F),
    ]


# For testing this template standalone
if __name__ == "__main__":
    from workout_utils import save_workout
    import os

    info = get_workout_info()
    steps = get_workout_steps()

    output_dir = Path(__file__).parent.parent / "Output_fit"
    output_dir.mkdir(exist_ok=True)

    filepath = output_dir / "test_long_run.fit"
    save_workout(str(filepath), info["name"], steps)
    print(f"Generated: {filepath}")
