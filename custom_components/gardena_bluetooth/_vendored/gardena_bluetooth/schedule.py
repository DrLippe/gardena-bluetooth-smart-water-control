"""Gen-2 watering schedule protocol helpers."""

from dataclasses import dataclass
from datetime import time
from typing import Mapping

UUID_SUFFIX = "-0b0e-421a-84e5-ddbf75dc6de4"
SCHEDULE_SLOT_COUNT = 3
REFERENCE_MIDNIGHT = 0
REFERENCE_DURATION = 4
# Confirmed by reading a Home Assistant-created plan in Gardena's Android app.
REPETITION_TYPE_WEEKDAYS = 2

# Gardena's HWC weekday representation starts with Monday in bit 0.
WEEKDAY_BITS = {
    "monday": 0x01,
    "tuesday": 0x02,
    "wednesday": 0x04,
    "thursday": 0x08,
    "friday": 0x10,
    "saturday": 0x20,
    "sunday": 0x40,
}
WEEKDAY_ORDER = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


@dataclass(frozen=True)
class ScheduleCharacteristics:
    """UUIDs belonging to one Gen-2 schedule instance."""

    slot: int
    start_reference: str
    start_offset: str
    end_reference: str
    end_offset: str
    repetition_type: str
    repetition_value: str
    actuator: str
    pre_offset: str

    @property
    def uuids(self) -> tuple[str, ...]:
        """Return all characteristic UUIDs in protocol order."""
        return (
            self.start_reference,
            self.start_offset,
            self.end_reference,
            self.end_offset,
            self.repetition_type,
            self.repetition_value,
            self.actuator,
            self.pre_offset,
        )


def _schedule_uuid(instance: int, resource: int) -> str:
    return f"98bdd{instance}{resource:02d}{UUID_SUFFIX}"


def schedule_characteristics(slot: int) -> ScheduleCharacteristics:
    """Return the characteristic set for a one-based schedule slot."""
    if not 1 <= slot <= SCHEDULE_SLOT_COUNT:
        raise ValueError(f"Schedule slot must be between 1 and {SCHEDULE_SLOT_COUNT}")
    instance = slot - 1
    return ScheduleCharacteristics(
        slot=slot,
        start_reference=_schedule_uuid(instance, 1),
        start_offset=_schedule_uuid(instance, 2),
        end_reference=_schedule_uuid(instance, 3),
        end_offset=_schedule_uuid(instance, 4),
        repetition_type=_schedule_uuid(instance, 6),
        repetition_value=_schedule_uuid(instance, 7),
        actuator=_schedule_uuid(instance, 8),
        pre_offset=_schedule_uuid(instance, 9),
    )


SCHEDULES = tuple(
    schedule_characteristics(slot) for slot in range(1, SCHEDULE_SLOT_COUNT + 1)
)
SCHEDULE_UUIDS = frozenset(uuid for schedule in SCHEDULES for uuid in schedule.uuids)
SCHEDULE_MASK_UUIDS = frozenset(
    schedule.repetition_value for schedule in SCHEDULES
)


def encode_weekdays(weekdays: list[str]) -> int:
    """Encode weekday names into Gardena's bitmask."""
    if not weekdays:
        raise ValueError("At least one weekday is required")
    unknown = set(weekdays) - WEEKDAY_BITS.keys()
    if unknown:
        raise ValueError(f"Unknown weekdays: {', '.join(sorted(unknown))}")
    return sum(WEEKDAY_BITS[weekday] for weekday in set(weekdays))


def decode_weekdays(value: int) -> tuple[str, ...]:
    """Decode Gardena's weekday bitmask in calendar order."""
    return tuple(day for day in WEEKDAY_ORDER if value & WEEKDAY_BITS[day])


def time_to_seconds(value: time) -> int:
    """Convert a local wall-clock time into seconds after midnight."""
    if value.tzinfo is not None:
        raise ValueError("Schedule times must not contain a timezone")
    return value.hour * 3600 + value.minute * 60 + value.second


def seconds_to_time(value: int) -> time | None:
    """Convert seconds after midnight into a wall-clock time."""
    if not 0 <= value < 24 * 3600:
        return None
    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    return time(hours, minutes, seconds)


@dataclass(frozen=True)
class DecodedSchedule:
    """Decoded values of one schedule slot."""

    start_reference: int
    start_offset: int
    end_reference: int
    end_offset: int
    repetition_type: int
    repetition_value: int
    actuator: int
    pre_offset: int

    @property
    def active(self) -> bool:
        """Return whether the schedule has at least one active weekday."""
        return self.repetition_value != 0

    @property
    def weekdays(self) -> tuple[str, ...]:
        """Return active weekdays."""
        return decode_weekdays(self.repetition_value)

    @property
    def start_time(self) -> time | None:
        """Return a fixed start time, or None for solar references."""
        if self.start_reference != REFERENCE_MIDNIGHT:
            return None
        return seconds_to_time(self.start_offset)

    @property
    def end_time(self) -> time | None:
        """Return the calculated fixed end time."""
        if self.end_reference == REFERENCE_MIDNIGHT:
            return seconds_to_time(self.end_offset)
        if self.end_reference == REFERENCE_DURATION:
            return seconds_to_time(self.start_offset + self.end_offset)
        return None

    @property
    def duration_seconds(self) -> int | None:
        """Return the watering duration for a fixed schedule."""
        if self.start_time is None or self.end_time is None:
            return None
        if self.end_reference == REFERENCE_DURATION:
            return self.end_offset
        return self.end_offset - self.start_offset

    @property
    def supported(self) -> bool:
        """Return whether this integration can safely edit the schedule."""
        return (
            self.start_time is not None
            and self.end_time is not None
            and self.repetition_type == REPETITION_TYPE_WEEKDAYS
            and self.actuator == 0
            and not self.repetition_value & ~0x7F
        )


def decode_schedule(
    schedule: ScheduleCharacteristics, values: Mapping[str, bytes]
) -> DecodedSchedule:
    """Decode a complete raw schedule snapshot."""
    expected_lengths = {
        schedule.start_reference: 1,
        schedule.start_offset: 4,
        schedule.end_reference: 1,
        schedule.end_offset: 4,
        schedule.repetition_type: 1,
        schedule.repetition_value: 4,
        schedule.actuator: 1,
        schedule.pre_offset: 2,
    }
    for uuid, expected_length in expected_lengths.items():
        if uuid not in values:
            raise ValueError(f"Missing schedule characteristic {uuid}")
        if len(values[uuid]) != expected_length:
            raise ValueError(
                f"Unexpected value length for {uuid}: {len(values[uuid])}"
            )

    return DecodedSchedule(
        start_reference=values[schedule.start_reference][0],
        start_offset=int.from_bytes(
            values[schedule.start_offset], "little", signed=True
        ),
        end_reference=values[schedule.end_reference][0],
        end_offset=int.from_bytes(values[schedule.end_offset], "little", signed=True),
        repetition_type=values[schedule.repetition_type][0],
        repetition_value=int.from_bytes(
            values[schedule.repetition_value], "little"
        ),
        actuator=values[schedule.actuator][0],
        pre_offset=int.from_bytes(values[schedule.pre_offset], "little"),
    )


def encode_fixed_schedule(
    schedule: ScheduleCharacteristics,
    start: time,
    end: time,
    weekdays: list[str],
) -> dict[str, bytes]:
    """Encode a fixed-time weekly schedule for valve 1."""
    start_seconds = time_to_seconds(start)
    end_seconds = time_to_seconds(end)
    if end_seconds <= start_seconds:
        raise ValueError("Schedule end time must be after its start time")

    return {
        schedule.start_reference: REFERENCE_MIDNIGHT.to_bytes(1, "little"),
        schedule.start_offset: start_seconds.to_bytes(4, "little", signed=True),
        schedule.end_reference: REFERENCE_DURATION.to_bytes(1, "little"),
        schedule.end_offset: (end_seconds - start_seconds).to_bytes(
            4, "little", signed=True
        ),
        schedule.repetition_type: REPETITION_TYPE_WEEKDAYS.to_bytes(1, "little"),
        schedule.repetition_value: encode_weekdays(weekdays).to_bytes(4, "little"),
        schedule.actuator: bytes(1),
    }
