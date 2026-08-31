"""Safe read and write operations for Gen-2 watering schedules."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import time
from typing import TYPE_CHECKING

from gardena_bluetooth.schedule import (
    ScheduleCharacteristics,
    decode_schedule,
    encode_fixed_schedule,
    schedule_characteristics,
)

from homeassistant.exceptions import HomeAssistantError

if TYPE_CHECKING:
    from .coordinator import GardenaBluetoothCoordinator


def _short_uuid(uuid: str) -> str:
    return uuid.split("-", 1)[0]


async def _disable_best_effort_locked(
    coordinator: GardenaBluetoothCoordinator,
    schedule: ScheduleCharacteristics,
) -> None:
    """Best-effort fail-safe for an incompletely restored schedule."""
    try:
        await coordinator.client.write_char_raw(schedule.repetition_value, bytes(4))
    except Exception:
        pass


def _validate_snapshot(
    schedule: ScheduleCharacteristics, values: Mapping[str, bytes]
) -> None:
    """Validate field lengths by decoding the complete snapshot."""
    decode_schedule(schedule, values)


async def _read_snapshot_locked(
    coordinator: GardenaBluetoothCoordinator,
    schedule: ScheduleCharacteristics,
) -> dict[str, bytes]:
    """Read a complete schedule while the coordinator operation lock is held."""
    values = {
        uuid: await coordinator.client.read_char_raw(uuid) for uuid in schedule.uuids
    }
    _validate_snapshot(schedule, values)
    return values


async def _write_and_verify_locked(
    coordinator: GardenaBluetoothCoordinator, uuid: str, value: bytes
) -> None:
    """Write one raw characteristic and verify its readback."""
    await coordinator.client.write_char_raw(uuid, value)
    if await coordinator.client.read_char_raw(uuid) != value:
        raise HomeAssistantError(
            f"Schedule write verification failed for {_short_uuid(uuid)}"
        )


async def _restore_locked(
    coordinator: GardenaBluetoothCoordinator,
    schedule: ScheduleCharacteristics,
    original: Mapping[str, bytes],
) -> list[str]:
    """Restore an original snapshot, keeping recurrence disabled until last."""
    errors: list[str] = []
    zero_mask = bytes(4)
    try:
        await _write_and_verify_locked(
            coordinator, schedule.repetition_value, zero_mask
        )
    except Exception:
        errors.append(_short_uuid(schedule.repetition_value))

    restore_order = (
        schedule.start_reference,
        schedule.start_offset,
        schedule.end_reference,
        schedule.end_offset,
        schedule.repetition_type,
    )
    for uuid in restore_order:
        try:
            await _write_and_verify_locked(coordinator, uuid, original[uuid])
        except Exception:
            errors.append(_short_uuid(uuid))

    if not errors:
        try:
            await _write_and_verify_locked(
                coordinator,
                schedule.repetition_value,
                original[schedule.repetition_value],
            )
        except Exception:
            errors.append(_short_uuid(schedule.repetition_value))

    if errors:
        # Best-effort fail-safe: a partially restored schedule must stay disabled.
        await _disable_best_effort_locked(coordinator, schedule)
        return errors

    try:
        restored = await _read_snapshot_locked(coordinator, schedule)
    except Exception:
        await _disable_best_effort_locked(coordinator, schedule)
        return ["snapshot"]
    mismatches = [
        _short_uuid(uuid)
        for uuid in schedule.uuids
        if restored[uuid] != original[uuid]
    ]
    if mismatches:
        await _disable_best_effort_locked(coordinator, schedule)
    return mismatches


def _ensure_supported(
    coordinator: GardenaBluetoothCoordinator, schedule: ScheduleCharacteristics
) -> None:
    missing = set(schedule.uuids) - coordinator.raw_characteristics
    if missing:
        raise HomeAssistantError(
            f"Schedule slot {schedule.slot} is not supported by this device"
        )


async def async_set_schedule(
    coordinator: GardenaBluetoothCoordinator,
    slot: int,
    start: time,
    end: time,
    weekdays: list[str],
) -> None:
    """Atomically configure and enable one fixed-time weekly schedule."""
    schedule = schedule_characteristics(slot)
    _ensure_supported(coordinator, schedule)
    desired = encode_fixed_schedule(schedule, start, end, weekdays)

    async with coordinator.operation_lock:
        original = await _read_snapshot_locked(coordinator, schedule)
        if original[schedule.actuator] != b"\x00":
            raise HomeAssistantError(
                f"Schedule slot {slot} targets an unsupported actuator"
            )

        try:
            # Disable first; enable only after every other field is verified.
            await _write_and_verify_locked(
                coordinator, schedule.repetition_value, bytes(4)
            )
            for uuid in (
                schedule.start_reference,
                schedule.start_offset,
                schedule.end_reference,
                schedule.end_offset,
                schedule.repetition_type,
            ):
                await _write_and_verify_locked(coordinator, uuid, desired[uuid])
            await _write_and_verify_locked(
                coordinator,
                schedule.repetition_value,
                desired[schedule.repetition_value],
            )
            # Gardena's HWC API explicitly assigns the actuator after the
            # schedule fields. Even for valve 0, the same-value write is needed
            # so the device commits/re-evaluates the configured schedule.
            await _write_and_verify_locked(
                coordinator, schedule.actuator, desired[schedule.actuator]
            )
            snapshot = await _read_snapshot_locked(coordinator, schedule)
            for uuid, value in desired.items():
                if snapshot[uuid] != value:
                    raise HomeAssistantError(
                        f"Schedule verification failed for {_short_uuid(uuid)}"
                    )
        except (Exception, asyncio.CancelledError) as exception:
            restore_errors = await _restore_locked(
                coordinator, schedule, original
            )
            if restore_errors:
                raise HomeAssistantError(
                    "Schedule update failed and could not restore all values; "
                    "the schedule was left disabled. Affected fields: "
                    + ", ".join(restore_errors)
                ) from exception
            if isinstance(exception, asyncio.CancelledError):
                raise
            raise HomeAssistantError(
                "Schedule update failed; the previous schedule was restored"
            ) from exception

    coordinator.cache_schedule_snapshot(snapshot)


async def async_clear_schedule(
    coordinator: GardenaBluetoothCoordinator, slot: int
) -> None:
    """Disable and clear one schedule without changing backend metadata."""
    schedule = schedule_characteristics(slot)
    _ensure_supported(coordinator, schedule)
    zero_values = {
        schedule.start_reference: bytes(1),
        schedule.start_offset: bytes(4),
        schedule.end_reference: bytes(1),
        schedule.end_offset: bytes(4),
        schedule.repetition_type: bytes(1),
    }

    async with coordinator.operation_lock:
        await _read_snapshot_locked(coordinator, schedule)
        errors: list[str] = []
        try:
            await _write_and_verify_locked(
                coordinator, schedule.repetition_value, bytes(4)
            )
        except Exception as exception:
            raise HomeAssistantError(
                "Unable to disable the schedule before clearing it"
            ) from exception

        for uuid, value in zero_values.items():
            try:
                await _write_and_verify_locked(coordinator, uuid, value)
            except Exception:
                errors.append(_short_uuid(uuid))

        snapshot = await _read_snapshot_locked(coordinator, schedule)
        if snapshot[schedule.repetition_value] != bytes(4):
            errors.append(_short_uuid(schedule.repetition_value))

    coordinator.cache_schedule_snapshot(snapshot)
    if errors:
        raise HomeAssistantError(
            "The schedule is disabled but not every field could be cleared: "
            + ", ".join(errors)
        )
