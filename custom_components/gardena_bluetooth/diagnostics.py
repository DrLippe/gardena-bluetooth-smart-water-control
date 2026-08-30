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
READ_TIMEOUT = 10


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GardenaBluetoothConfigEntry
) -> dict[str, Any]:
    """Return raw Gen-2 schedule data for protocol analysis."""
    del hass
    coordinator = entry.runtime_data
    schedule_data: dict[str, dict[str, int | str]] = {}

    characteristics = coordinator.raw_characteristics

    for uuid in sorted(characteristics):
        if not uuid.startswith(SCHEDULE_UUID_PREFIX):
            continue

        short_uuid = uuid.split("-", 1)[0]
        try:
            async with asyncio.timeout(READ_TIMEOUT):
                async with coordinator.operation_lock:
                    value = await coordinator.client.read_char_raw(uuid)
        except CharacteristicNoAccess:
            schedule_data[short_uuid] = {"error": "not_readable"}
        except TimeoutError:
            schedule_data[short_uuid] = {"error": "timeout"}
        except (GardenaBluetoothException, DeviceUnavailable) as exception:
            schedule_data[short_uuid] = {
                "error": type(exception).__name__,
            }
        else:
            schedule_data[short_uuid] = {
                "length": len(value),
                "hex": value.hex(),
            }

    return {"schedule_characteristics": schedule_data}
