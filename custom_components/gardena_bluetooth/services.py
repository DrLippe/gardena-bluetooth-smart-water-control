"""Services for Gardena Bluetooth schedules."""

from datetime import time

from gardena_bluetooth.schedule import WEEKDAY_BITS
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, service

from .const import DOMAIN
from .coordinator import GardenaBluetoothConfigEntry
from .schedule_manager import async_clear_schedule, async_set_schedule

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_SLOT = "slot"
ATTR_START_TIME = "start_time"
ATTR_END_TIME = "end_time"
ATTR_WEEKDAYS = "weekdays"

SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_CLEAR_SCHEDULE = "clear_schedule"

SLOT_SCHEMA = vol.All(vol.Coerce(int), vol.Range(min=1, max=3))
SET_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): str,
        vol.Required(ATTR_SLOT): SLOT_SCHEMA,
        vol.Required(ATTR_START_TIME): cv.time,
        vol.Required(ATTR_END_TIME): cv.time,
        vol.Required(ATTR_WEEKDAYS): vol.All(
            cv.ensure_list, [vol.In(WEEKDAY_BITS)], vol.Length(min=1)
        ),
    }
)
CLEAR_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): str,
        vol.Required(ATTR_SLOT): SLOT_SCHEMA,
    }
)


def _entry(call: ServiceCall) -> GardenaBluetoothConfigEntry:
    return service.async_get_config_entry(
        call.hass, DOMAIN, call.data[ATTR_CONFIG_ENTRY_ID]
    )


async def _async_set_schedule(call: ServiceCall) -> None:
    """Set a weekly watering schedule."""
    start: time = call.data[ATTR_START_TIME]
    end: time = call.data[ATTR_END_TIME]
    if end <= start:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="schedule_end_not_after_start",
        )
    await async_set_schedule(
        _entry(call).runtime_data,
        call.data[ATTR_SLOT],
        start,
        end,
        call.data[ATTR_WEEKDAYS],
    )


async def _async_clear_schedule(call: ServiceCall) -> None:
    """Disable and clear a watering schedule."""
    await async_clear_schedule(
        _entry(call).runtime_data,
        call.data[ATTR_SLOT],
    )


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register Gardena Bluetooth schedule services."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULE,
        _async_set_schedule,
        schema=SET_SCHEDULE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_SCHEDULE,
        _async_clear_schedule,
        schema=CLEAR_SCHEDULE_SCHEMA,
    )
