"""
State management for tracking serial numbers and timestamps.

Ensures unique file_id values across multiple generations to prevent
Garmin device deduplication issues.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

try:
    from .config import STATE_FILE, FIT_EPOCH
except ImportError:
    from config import STATE_FILE, FIT_EPOCH

LOCK_FILE = STATE_FILE.with_suffix(".lock")

DEFAULT_STATE = {
    "last_serial_number": 900000000,
    "last_timestamp": 1139302800,
    "generated_count": 0,
    "last_generation_date": None,
}


def _validate_state(state):
    """Ensure state has required keys and correct primitive types."""
    required = {
        "last_serial_number": int,
        "last_timestamp": int,
        "generated_count": int,
        "last_generation_date": (str, type(None)),
    }
    for key, expected_type in required.items():
        if key not in state:
            raise ValueError(f"State missing required key: {key}")
        if not isinstance(state[key], expected_type):
            raise ValueError(f"State key '{key}' has invalid type: {type(state[key]).__name__}")


@contextmanager
def _state_lock():
    """Cross-process lock for state updates (Windows & Linux/macOS)."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w+b") as lock_f:
        if sys.platform == "win32":
            lock_f.write(b"0")
            lock_f.flush()
            lock_f.seek(0)
            msvcrt.locking(lock_f.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_f.seek(0)
                msvcrt.locking(lock_f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)

    # Clean up lock file after use
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass  # Ignore cleanup errors


def load_state():
    """
    Load current state from state.json.

    Returns:
        dict: State dictionary with keys:
            - last_serial_number: Last used serial number
            - last_timestamp: Last used FIT timestamp
            - generated_count: Total workouts generated
            - last_generation_date: ISO format datetime of last generation
    """
    if not STATE_FILE.exists():
        # Initialize with default state
        return DEFAULT_STATE.copy()

    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        state = json.load(f)

    _validate_state(state)
    return state


def save_state(state):
    """
    Save state to state.json.

    Args:
        state: State dictionary to save
    """
    _validate_state(state)

    tmp_file = STATE_FILE.with_suffix(".tmp")
    with open(tmp_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_file, STATE_FILE)


def get_next_serial_timestamp(count=1):
    """
    Get next available serial number(s) and timestamp(s).

    Args:
        count: Number of serial/timestamp pairs needed

    Returns:
        list: List of tuples (serial_number, fit_timestamp)

    Example:
        pairs = get_next_serial_timestamp(3)
        # [(900000001, 1139302801), (900000002, 1139302802), (900000003, 1139302803)]
    """
    with _state_lock():
        state = load_state()

        base_serial = state["last_serial_number"]
        base_timestamp = state["last_timestamp"]

        pairs = []
        for i in range(1, count + 1):
            pairs.append((base_serial + i, base_timestamp + i))

        # Update state
        state["last_serial_number"] = base_serial + count
        state["last_timestamp"] = base_timestamp + count
        state["generated_count"] = state["generated_count"] + count
        state["last_generation_date"] = datetime.now(timezone.utc).isoformat()

        save_state(state)

    return pairs


def to_fit_timestamp(dt):
    """
    Convert datetime to FIT timestamp.

    Args:
        dt: datetime object (will be converted to UTC)

    Returns:
        int: Seconds since FIT epoch (1989-12-31 00:00:00 UTC)
    """
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return int((dt - FIT_EPOCH).total_seconds())


def from_fit_timestamp(fit_ts):
    """
    Convert FIT timestamp to datetime.

    Args:
        fit_ts: FIT timestamp (seconds since 1989-12-31 UTC),
                or datetime object (returned as-is)

    Returns:
        datetime: Datetime object in UTC
    """
    if isinstance(fit_ts, datetime):
        return fit_ts
    return FIT_EPOCH + timedelta(seconds=fit_ts)


def fit_timestamp_to_unix_ms(fit_ts):
    """Convert FIT timestamp seconds to Unix epoch milliseconds."""
    dt = from_fit_timestamp(fit_ts)
    return int(dt.timestamp() * 1000)


def reset_state(start_serial=900000000, start_timestamp=None):
    """
    Reset state to initial values.

    WARNING: Use with caution. This can cause duplicate file_id values
    if you already have workouts on your Garmin device.

    Args:
        start_serial: Starting serial number (default: 900000000)
        start_timestamp: Starting FIT timestamp (default: current time)
    """
    if start_timestamp is None:
        start_timestamp = to_fit_timestamp(datetime.now(timezone.utc))

    state = {
        "last_serial_number": start_serial,
        "last_timestamp": start_timestamp,
        "generated_count": 0,
        "last_generation_date": None
    }

    save_state(state)
    print(f"State reset to serial={start_serial}, timestamp={start_timestamp}")


def print_state():
    """Print current state in human-readable format."""
    state = load_state()

    print("Current State:")
    print(f"  Last serial number: {state['last_serial_number']}")
    print(f"  Last timestamp: {state['last_timestamp']} ({from_fit_timestamp(state['last_timestamp'])})")
    print(f"  Total generated: {state['generated_count']} workouts")
    print(f"  Last generation: {state['last_generation_date'] or 'Never'}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "reset":
        confirm = input("Reset state? This may cause duplicate file_id issues! (yes/no): ")
        if confirm.lower() == "yes":
            reset_state()
        else:
            print("Reset cancelled.")
    else:
        print_state()
