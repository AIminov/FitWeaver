"""
Example: Easy Recovery Run Template

Type: Recovery (ВБ - Восстановительный Бег)
Pace: 6:00-6:30/km
Purpose: Active recovery, building aerobic base
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent / "Scripts"))

from workout_utils import dist_pace, EASY_F, EASY_S


def get_workout_info():
    """Return workout metadata"""
    return {
        "name": "Easy 5km",
        "description": "Recovery run at easy conversational pace",
        "type": "easy",
        "distance_km": 5.0,
        "estimated_duration_min": 30,
    }


def get_workout_steps():
    """Return list of workout steps"""
    return [
        dist_pace(0, 5.0, EASY_F, EASY_S),
    ]


# For testing this template standalone
if __name__ == "__main__":
    from workout_utils import save_workout
    import os

    info = get_workout_info()
    steps = get_workout_steps()

    output_dir = Path(__file__).parent.parent / "Output_fit"
    output_dir.mkdir(exist_ok=True)

    filepath = output_dir / "test_easy_run.fit"
    save_workout(str(filepath), info["name"], steps)
    print(f"Generated: {filepath}")
