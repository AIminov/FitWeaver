"""
Example: Tempo/Threshold Run Template

Type: Tempo (ТБ - Темповый Бег)
Pace: 4:50-5:10/km (threshold/lactate threshold pace)
Purpose: Improve lactate threshold, race-specific endurance
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent / "Scripts"))

from workout_utils import (
    dist_pace, dist_open, time_step,
    repeat_step, TEMPO_F, TEMPO_S,
    Intensity, WU, CD, REC
)


def get_workout_info():
    """Return workout metadata"""
    return {
        "name": "Tempo 4x1.5km",
        "description": "4 repetitions of 1.5km at tempo pace with 3min recovery",
        "type": "tempo",
        "distance_km": 9.0,
        "estimated_duration_min": 55,
    }


def get_workout_steps():
    """Return list of workout steps"""
    return [
        # Warmup: 2km
        dist_open(0, 2.0, WU),

        # Tempo interval: 1.5km at threshold pace
        dist_pace(1, 1.5, TEMPO_F, TEMPO_F),

        # Recovery: 3 minutes jogging
        time_step(2, 180, REC),

        # Repeat 4 times
        repeat_step(3, 1, 4),

        # Cooldown: 1km
        dist_open(4, 1.0, CD),
    ]


# For testing this template standalone
if __name__ == "__main__":
    from workout_utils import save_workout
    import os

    info = get_workout_info()
    steps = get_workout_steps()

    output_dir = Path(__file__).parent.parent / "Output_fit"
    output_dir.mkdir(exist_ok=True)

    filepath = output_dir / "test_tempo.fit"
    save_workout(str(filepath), info["name"], steps)
    print(f"Generated: {filepath}")
