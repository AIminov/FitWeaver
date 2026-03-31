"""
Utility functions for building Garmin FIT workout files.

This module provides helper functions for creating workout steps with proper
FIT encoding (distance, time, pace, heart rate, repeats, etc.)
"""

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.workout_message import WorkoutMessage
from fit_tool.profile.messages.workout_step_message import WorkoutStepMessage
from fit_tool.profile.profile_type import (
    FileType, Manufacturer, Sport, SubSport,
    Intensity, WorkoutStepDuration, WorkoutStepTarget,
)


# ============================================================================
# Conversion Functions
# ============================================================================

def pace_to_speed(pace_str):
    """
    Convert pace string to FIT speed units.

    Args:
        pace_str: Pace in format "MM:SS" (minutes:seconds per km)

    Returns:
        int: Speed in FIT units (mm/s, i.e. m/s * 1000)

    Example:
        pace_to_speed("5:00") -> 3333  # 5:00/km = 3.33 m/s = 3333 FIT units
        pace_to_speed("4:00") -> 4166  # 4:00/km = 4.17 m/s = 4166 FIT units

    Raises:
        ValueError: If pace_str is not in valid "MM:SS" format
    """
    if not isinstance(pace_str, str) or ':' not in pace_str:
        raise ValueError(f"Invalid pace format '{pace_str}', expected 'MM:SS'")
    parts = pace_str.split(':')
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError(f"Invalid pace format '{pace_str}', expected 'MM:SS' with digits")
    mm, ss = int(parts[0]), int(parts[1])
    if mm < 1 or ss < 0 or ss > 59:
        raise ValueError(f"Invalid pace '{pace_str}': minutes >= 1, seconds 0-59")
    total_sec = mm * 60 + ss
    return int(1000.0 / total_sec * 1000)


def km_to_dist(km):
    """
    Convert kilometers to FIT distance units.

    Args:
        km: Distance in kilometers

    Returns:
        int: Distance in FIT units (meters / 10)

    Example:
        km_to_dist(2.0) -> 200  # 2km = 2000m = 200 FIT units
    """
    return int(km * 100)


def sec_to_time(seconds):
    """
    Convert seconds to FIT time units.

    Args:
        seconds: Time in seconds

    Returns:
        int: Time in FIT units (milliseconds)

    Example:
        sec_to_time(60) -> 60000  # 60 seconds = 60000 ms
    """
    return int(seconds * 1000)


def bpm_to_fit_hr(bpm):
    """
    Convert heart rate in bpm to FIT HR target units.

    FIT SDK uses bpm + 100 offset for HR targets in workout steps.

    Args:
        bpm: Heart rate in beats per minute

    Returns:
        int: HR value in FIT units (bpm + 100)

    Example:
        bpm_to_fit_hr(150) -> 250
    """
    return int(bpm) + 100


# ============================================================================
# Pace Constants (commonly used)
# ============================================================================

EASY_F = "6:00"   # fast end of easy pace
EASY_S = "6:30"   # slow end of easy pace
AERO_F = "5:30"   # fast aerobic
AERO_S = "5:50"   # slow aerobic
LONG_F = "5:30"   # fast long run
LONG_S = "6:00"   # slow long run
TEMPO_F = "4:50"  # fast tempo/threshold
TEMPO_S = "5:10"  # slow tempo/threshold

# Intensity shortcuts
WU = Intensity.WARMUP
CD = Intensity.COOLDOWN
ACT = Intensity.ACTIVE
REC = Intensity.RECOVERY


# ============================================================================
# HR Zone Support
# ============================================================================

def load_hr_zones():
    """
    Load HR zones from user_profile.yaml.

    Returns:
        dict: HR zones configuration with keys like 'zone1', 'zone2', etc.
              Each zone has 'low' and 'high' bpm values.

    Raises:
        FileNotFoundError: If user_profile.yaml doesn't exist
    """
    import yaml
    from .config import USER_PROFILE

    if not USER_PROFILE.exists():
        raise FileNotFoundError(
            f"User profile not found: {USER_PROFILE}\n"
            "Create user_profile.yaml with your HR zones. See README for format."
        )
    with open(USER_PROFILE, 'r', encoding='utf-8') as f:
        profile = yaml.safe_load(f)
    return profile.get("hr_zones", {})


def load_user_profile():
    """
    Load full user profile from user_profile.yaml.

    Returns:
        dict: Full user profile including max_hr, resting_hr, hr_zones
    """
    import yaml
    from .config import USER_PROFILE

    if not USER_PROFILE.exists():
        raise FileNotFoundError(f"User profile not found: {USER_PROFILE}")
    with open(USER_PROFILE, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# ============================================================================
# Step Builder Functions
# ============================================================================

def make_step(idx, dur_type, dur_val, tgt_type, intensity,
              tgt_val=None, tgt_low=None, tgt_high=None):
    """
    Create a workout step with specified parameters.

    Args:
        idx: Step index (0-based)
        dur_type: WorkoutStepDuration enum value
        dur_val: Duration value (units depend on dur_type)
        tgt_type: WorkoutStepTarget enum value
        intensity: Intensity enum value (WARMUP, ACTIVE, RECOVERY, COOLDOWN)
        tgt_val: Target value (optional)
        tgt_low: Custom target low value (optional)
        tgt_high: Custom target high value (optional)

    Returns:
        WorkoutStepMessage: Configured workout step
    """
    s = WorkoutStepMessage()
    s.message_index = idx
    s.duration_type = dur_type
    s.duration_value = dur_val
    s.target_type = tgt_type
    s.intensity = intensity
    if tgt_val is not None:
        s.target_value = tgt_val
    if tgt_low is not None:
        s.custom_target_value_low = tgt_low
    if tgt_high is not None:
        s.custom_target_value_high = tgt_high
    return s


def dist_pace(idx, km, pace_fast, pace_slow, intensity=Intensity.ACTIVE):
    """
    Create a distance-based step with pace target range.

    Args:
        idx: Step index
        km: Distance in kilometers
        pace_fast: Fast end of pace range (e.g., "5:00")
        pace_slow: Slow end of pace range (e.g., "5:30")
        intensity: Step intensity (default: ACTIVE)

    Returns:
        WorkoutStepMessage: Distance step with pace zone

    Example:
        dist_pace(0, 5.0, "5:00", "5:30")  # 5km at 5:00-5:30/km pace
    """
    return make_step(idx,
        WorkoutStepDuration.DISTANCE, km_to_dist(km),
        WorkoutStepTarget.SPEED, intensity,
        tgt_val=0,
        tgt_low=pace_to_speed(pace_slow),    # slower = lower speed
        tgt_high=pace_to_speed(pace_fast))   # faster = higher speed


def dist_open(idx, km, intensity=Intensity.ACTIVE):
    """
    Create a distance-based step without pace target.

    Args:
        idx: Step index
        km: Distance in kilometers
        intensity: Step intensity (default: ACTIVE)

    Returns:
        WorkoutStepMessage: Distance step with open target

    Example:
        dist_open(0, 2.0, Intensity.WARMUP)  # 2km warmup, any pace
    """
    return make_step(idx,
        WorkoutStepDuration.DISTANCE, km_to_dist(km),
        WorkoutStepTarget.OPEN, intensity)


def open_step(idx, intensity=Intensity.ACTIVE):
    """
    Create an open/lap-button step.

    User presses lap button to complete this step.
    Useful for drills, exercises, or flexible recovery.

    Args:
        idx: Step index
        intensity: Step intensity (default: ACTIVE)

    Returns:
        WorkoutStepMessage: Open step (lap button to advance)

    Example:
        open_step(2)  # Press lap when ready to continue
    """
    return make_step(idx,
        WorkoutStepDuration.OPEN, 0,
        WorkoutStepTarget.OPEN, intensity)


def time_step(idx, seconds, intensity=Intensity.RECOVERY):
    """
    Create a time-based step without target.

    Args:
        idx: Step index
        seconds: Duration in seconds
        intensity: Step intensity (default: RECOVERY)

    Returns:
        WorkoutStepMessage: Time-based step

    Example:
        time_step(2, 180, Intensity.RECOVERY)  # 3-minute recovery
    """
    return make_step(idx,
        WorkoutStepDuration.TIME, sec_to_time(seconds),
        WorkoutStepTarget.OPEN, intensity)


def time_pace(idx, seconds, pace_fast, pace_slow, intensity=Intensity.ACTIVE):
    """
    Create a time-based step with pace target range.

    Args:
        idx: Step index
        seconds: Duration in seconds
        pace_fast: Fast end of pace range (e.g., "5:00")
        pace_slow: Slow end of pace range (e.g., "5:30")
        intensity: Step intensity (default: ACTIVE)

    Returns:
        WorkoutStepMessage: Time step with pace zone

    Example:
        time_pace(1, 600, "5:00", "5:30")  # 10 min at 5:00-5:30/km
    """
    return make_step(idx,
        WorkoutStepDuration.TIME, sec_to_time(seconds),
        WorkoutStepTarget.SPEED, intensity,
        tgt_val=0,
        tgt_low=pace_to_speed(pace_slow),
        tgt_high=pace_to_speed(pace_fast))


def dist_hr(idx, km, hr_low, hr_high, intensity=Intensity.ACTIVE):
    """
    Create a distance-based step with heart rate target range.

    Args:
        idx: Step index
        km: Distance in kilometers
        hr_low: Low end of HR range in bpm (e.g., 140)
        hr_high: High end of HR range in bpm (e.g., 155)
        intensity: Step intensity (default: ACTIVE)

    Returns:
        WorkoutStepMessage: Distance step with HR zone

    Example:
        dist_hr(0, 10.0, 140, 155)  # 10km at 140-155 bpm
    """
    return make_step(idx,
        WorkoutStepDuration.DISTANCE, km_to_dist(km),
        WorkoutStepTarget.HEART_RATE, intensity,
        tgt_val=0,
        tgt_low=bpm_to_fit_hr(hr_low),
        tgt_high=bpm_to_fit_hr(hr_high))


def time_hr(idx, seconds, hr_low, hr_high, intensity=Intensity.ACTIVE):
    """
    Create a time-based step with heart rate target range.

    Args:
        idx: Step index
        seconds: Duration in seconds
        hr_low: Low end of HR range in bpm
        hr_high: High end of HR range in bpm
        intensity: Step intensity (default: ACTIVE)

    Returns:
        WorkoutStepMessage: Time step with HR zone

    Example:
        time_hr(1, 1200, 150, 165)  # 20 min at 150-165 bpm
    """
    return make_step(idx,
        WorkoutStepDuration.TIME, sec_to_time(seconds),
        WorkoutStepTarget.HEART_RATE, intensity,
        tgt_val=0,
        tgt_low=bpm_to_fit_hr(hr_low),
        tgt_high=bpm_to_fit_hr(hr_high))


def repeat_step(idx, back_to, count):
    """
    Create a repeat step.

    Args:
        idx: Step index
        back_to: Step index to repeat from
        count: Number of repetitions

    Returns:
        WorkoutStepMessage: Repeat step

    Example:
        # Steps: 0=warmup, 1=interval, 2=recovery, 3=repeat
        repeat_step(3, 1, 6)  # Repeat steps 1-2 six times
    """
    return make_step(idx,
        WorkoutStepDuration.REPEAT_UNTIL_STEPS_CMPLT, back_to,
        WorkoutStepTarget.OPEN, Intensity.ACTIVE,
        tgt_val=count)


# ============================================================================
# FIT File Saving
# ============================================================================

def save_workout(filepath, name, steps, serial_number=12345, time_created_ms=None):
    """
    Build and save a FIT workout file.

    Args:
        filepath: Output path for .fit file
        name: Workout name (displayed on watch)
        steps: List of WorkoutStepMessage objects
        serial_number: Device serial number for file_id (default: 12345)
        time_created_ms: Creation timestamp in milliseconds since epoch (default: current time)

    Returns:
        None

    Example:
        steps = [
            dist_pace(0, 1.0, "6:00", "6:30", Intensity.WARMUP),
            dist_pace(1, 5.0, "5:00", "5:30"),
            dist_open(2, 1.0, Intensity.COOLDOWN),
        ]
        save_workout("output.fit", "Easy 7km", steps, serial_number=900000001)
    """
    from datetime import datetime

    if time_created_ms is None:
        time_created_ms = int(datetime.now().timestamp() * 1000)

    builder = FitFileBuilder()

    fid = FileIdMessage()
    fid.type = FileType.WORKOUT
    fid.manufacturer = Manufacturer.GARMIN.value
    fid.product = 0
    fid.serial_number = serial_number
    fid.time_created = time_created_ms

    wkt = WorkoutMessage()
    wkt.sport = Sport.RUNNING
    wkt.sub_sport = SubSport.GENERIC
    wkt.num_valid_steps = len(steps)
    wkt.workout_name = name

    builder.add(fid)
    builder.add(wkt)
    builder.add_all(steps)

    fit_file = builder.build()
    fit_file.to_file(filepath)
