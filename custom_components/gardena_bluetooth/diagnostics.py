"""Diagnostics support for Gardena Bluetooth."""

import asyncio
from typing import Any

from gardena_bluetooth.exceptions import (
    CharacteristicNoAccess,
    GardenaBluetoothException,
)

from homeassistant.core import HomeAssistant

from .coordinator import GardenaBluetoothConfigEntry, DeviceUnavailable

SCHEDULE_UUID_PREFIX = "98bdd"
VALVE_DIAGNOSTIC_UUIDS = frozenset(
    {
        "98bda001",  # Default/manual watering duration
        "98bda002",  # Available
        "98bda003",  # Error
        "98bda004",  # Paused until
        "98bda008",  # State
        "98bda010",  # Remaining open time
        "98bda011",  # Activation reason
    }
)
SYSTEM_DIAGNOSTIC_UUIDS = frozenset(
    {
        "98bd0101",  # Confirmed device uptime on wc_single
        "98bd0102",
        "98bd0103",
        "98bd0104",
        # This block is exposed by G-19033/G-19034 but is not documented yet.
        # Capturing it around a missed schedule may reveal clock/timeslot state.
        "98bd9001",
        "98bd9002",
        "98bd9003",
        "98bd9004",
    }
)
READ_TIMEOUT = 10


async def _async_read_raw_characteristics(
    coordinator, uuids: list[str]
) -> dict[str, dict[str, int | str]]:
    """Read selected characteristics without interpreting experimental data."""
    result: dict[str, dict[str, int | str]] = {}

    for uuid in uuids:
        short_uuid = uuid.split("-", 1)[0]
        try:
            async with asyncio.timeout(READ_TIMEOUT):
                async with coordinator.operation_lock:
                    value = await coordinator.client.read_char_raw(uuid)
        except CharacteristicNoAccess:
            result[short_uuid] = {"error": "not_readable"}
        except TimeoutError:
            result[short_uuid] = {"error": "timeout"}
        except (GardenaBluetoothException, DeviceUnavailable) as exception:
            result[short_uuid] = {"error": type(exception).__name__}
        else:
            result[short_uuid] = {"length": len(value), "hex": value.hex()}

    return result


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GardenaBluetoothConfigEntry
) -> dict[str, Any]:
    """Return raw Gen-2 scheduling and execution data for protocol analysis."""
    del hass
    coordinator = entry.runtime_data
    characteristics = coordinator.raw_characteristics
    groups = {
        "schedule_characteristics": sorted(
            uuid for uuid in characteristics if uuid.startswith(SCHEDULE_UUID_PREFIX)
        ),
        "valve_execution_characteristics": sorted(
            uuid
            for uuid in characteristics
            if uuid.split("-", 1)[0] in VALVE_DIAGNOSTIC_UUIDS
        ),
        "system_characteristics": sorted(
            uuid
            for uuid in characteristics
            if uuid.split("-", 1)[0] in SYSTEM_DIAGNOSTIC_UUIDS
        ),
    }

    return {
        name: await _async_read_raw_characteristics(coordinator, uuids)
        for name, uuids in groups.items()
    }
