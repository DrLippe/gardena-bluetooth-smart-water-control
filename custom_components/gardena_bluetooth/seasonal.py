"""Conversions for seasonal watering reduction."""


def reduction_from_runtime(runtime_percent: int) -> float:
    """Convert the device's remaining-runtime percentage to a reduction."""
    if not 0 <= runtime_percent <= 100:
        raise ValueError("Seasonal runtime must be between 0 and 100 percent")
    return float(100 - runtime_percent)


def runtime_from_reduction(reduction_percent: float) -> int:
    """Convert a user-facing reduction to the device's runtime percentage."""
    if not 0 <= reduction_percent <= 100:
        raise ValueError("Seasonal reduction must be between 0 and 100 percent")
    return 100 - round(reduction_percent)
