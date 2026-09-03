"""Conversions for user-facing manual watering settings."""

MIN_MANUAL_WATERING_MINUTES = 1
MAX_MANUAL_WATERING_MINUTES = 90


def manual_seconds_from_minutes(value: float | int) -> int:
    """Validate whole minutes and convert them to device seconds."""
    minutes = float(value)
    if not minutes.is_integer():
        raise ValueError("Manual watering duration must use whole minutes")
    if not MIN_MANUAL_WATERING_MINUTES <= minutes <= MAX_MANUAL_WATERING_MINUTES:
        raise ValueError("Manual watering duration must be between 1 and 90 minutes")
    return int(minutes) * 60


def manual_minutes_from_seconds(value: int) -> int:
    """Convert device seconds to a valid whole-minute form default."""
    minutes = round(value / 60)
    return max(
        MIN_MANUAL_WATERING_MINUTES,
        min(MAX_MANUAL_WATERING_MINUTES, minutes),
    )
