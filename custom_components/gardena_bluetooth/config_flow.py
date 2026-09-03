"""Config flow for Gardena Bluetooth integration."""

from __future__ import annotations

from datetime import time
import logging
from typing import Any

from gardena_bluetooth.client import Client
from gardena_bluetooth.const import PRODUCT_NAMES, DeviceInformation, Valve1
from gardena_bluetooth.exceptions import CharacteristicNotFound, CommunicationFailure
from gardena_bluetooth.parse import ManufacturerData, ProductType
from gardena_bluetooth.schedule import SCHEDULES, WEEKDAY_ORDER
from gardena_bluetooth.scan import async_get_manufacturer_data
import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfo,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TimeSelector,
)

from . import get_connection
from .const import CONF_PRODUCT_TYPE, CONF_SERIAL_NUMBER, DOMAIN
from .schedule_manager import (
    async_clear_schedule,
    async_read_schedule,
    async_set_schedule,
)
from .watering import (
    MAX_MANUAL_WATERING_MINUTES,
    MIN_MANUAL_WATERING_MINUTES,
    manual_minutes_from_seconds,
    manual_seconds_from_minutes,
)

_LOGGER = logging.getLogger(__name__)

_SUPPORTED_PRODUCT_TYPES = {
    ProductType.PUMP,
    ProductType.VALVE,
    ProductType.WATER_COMPUTER,
    ProductType.AUTOMATS,
    ProductType.PRESSURE_TANKS,
    ProductType.AQUA_CONTOURS,
}

CONF_ENABLED = "enabled"
CONF_START_TIME = "start_time"
CONF_END_TIME = "end_time"
CONF_WEEKDAYS = "weekdays"
CONF_VALVE_NAME = "valve_name"
CONF_MANUAL_WATERING_MINUTES = "manual_watering_minutes"

_MANUFACTURER_IDENTITY_FIELDS = {"group", "model", "variant", "serial"}


def _is_supported(discovery_info: BluetoothServiceInfo):
    """Check if device is supported.

    Accepts any device carrying Gardena manufacturer data (company id 0x0426).
    The legacy 01889-20 family also advertised the ScanService UUID
    98bd0001-..., but newer Smart Water Control devices (G-19033, G-19034,
    G-19050) advertise only manufacturer data with no service UUIDs, so the
    UUID is no longer a reliable filter.
    """
    if discovery_info.manufacturer_data.get(ManufacturerData.company) is None:
        _LOGGER.debug("Missing Gardena manufacturer data: %s", discovery_info)
        return False
    return True


class GardenaBluetoothConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Gardena Bluetooth."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.devices: dict[str, str] = {}
        self.product_types: dict[str, str] = {}
        self.serial_numbers: dict[str, int] = {}
        self.address: str | None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> GardenaBluetoothOptionsFlow:
        """Return the watering schedule editor."""
        del config_entry
        return GardenaBluetoothOptionsFlow()

    async def async_read_data(self):
        """Try to connect to device and extract information."""
        assert self.address
        client = Client(get_connection(self.hass, self.address))
        try:
            model = await client.read_char(DeviceInformation.model_number)
            _LOGGER.debug("Found device with model: %s", model)
        except (CharacteristicNotFound, CommunicationFailure) as exception:
            raise AbortFlow(
                "cannot_connect", description_placeholders={"error": str(exception)}
            ) from exception
        finally:
            await client.disconnect()

        data = {CONF_ADDRESS: self.address}
        # Persist the product type resolved during pairing: Aqua Contours
        # devices only advertise it in pairing mode, so a setup-time re-scan
        # cannot be relied on after a restart.
        if product_type := self.product_types.get(self.address):
            data[CONF_PRODUCT_TYPE] = product_type
        if serial_number := self.serial_numbers.get(self.address):
            data[CONF_SERIAL_NUMBER] = serial_number
        return data

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfo
    ) -> ConfigFlowResult:
        """Handle the bluetooth discovery step."""
        _LOGGER.debug("Discovered device: %s", discovery_info)
        data = await async_get_manufacturer_data(
            {discovery_info.address}, fields=_MANUFACTURER_IDENTITY_FIELDS
        )
        product_type = data[discovery_info.address].product_type
        if product_type not in _SUPPORTED_PRODUCT_TYPES:
            return self.async_abort(reason="no_devices_found")

        self.address = discovery_info.address
        self.devices = {discovery_info.address: PRODUCT_NAMES[product_type]}
        self.product_types[discovery_info.address] = product_type.name
        if serial_number := data[discovery_info.address].serial:
            self.serial_numbers[discovery_info.address] = serial_number
        await self.async_set_unique_id(self.address)
        self._abort_if_unique_id_configured()
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovery."""
        assert self.address
        title = self.devices[self.address]

        if user_input is not None:
            data = await self.async_read_data()
            return self.async_create_entry(title=title, data=data)

        self.context["title_placeholders"] = {
            "name": title,
        }

        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders=self.context["title_placeholders"],
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is not None:
            self.address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(self.address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_confirm()

        current_addresses = self._async_current_ids(include_ignore=False)
        candidates = set()
        for discovery_info in async_discovered_service_info(self.hass):
            address = discovery_info.address
            if address in current_addresses or not _is_supported(discovery_info):
                continue
            candidates.add(address)

        data = await async_get_manufacturer_data(
            candidates, fields=_MANUFACTURER_IDENTITY_FIELDS
        )
        for address, mfg_data in data.items():
            if mfg_data.product_type not in _SUPPORTED_PRODUCT_TYPES:
                continue
            self.devices[address] = PRODUCT_NAMES[mfg_data.product_type]
            self.product_types[address] = mfg_data.product_type.name
            if serial_number := mfg_data.serial:
                self.serial_numbers[address] = serial_number

        # Keep selection sorted by address to ensure stable tests
        self.devices = dict(sorted(self.devices.items(), key=lambda x: x[0]))

        if not self.devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(self.devices),
                },
            ),
        )


class GardenaBluetoothOptionsFlow(OptionsFlow):
    """Edit Smart Water Control schedules directly from the integration."""

    def __init__(self) -> None:
        """Initialize options flow state."""
        self._defaults: dict[int, dict[str, Any]] = {}

    def _schedule_is_supported(self, slot: int) -> bool:
        """Return whether the connected device exposes a complete slot."""
        schedule = SCHEDULES[slot - 1]
        return set(schedule.uuids).issubset(
            self.config_entry.runtime_data.raw_characteristics
        )

    def _valve_settings_are_supported(self) -> bool:
        """Return whether valve name and manual duration can be configured."""
        characteristics = self.config_entry.runtime_data.characteristics
        return {
            Valve1.name.unique_id,
            Valve1.manual_watering_duration.unique_id,
        }.issubset(characteristics)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the schedule slot menu."""
        del user_input
        try:
            _ = self.config_entry.runtime_data
        except RuntimeError:
            return self.async_abort(reason="entry_not_loaded")
        menu_options = []
        if self._valve_settings_are_supported():
            menu_options.append("valve_settings")
        menu_options.extend(
            f"schedule_{slot}"
            for slot in range(1, 4)
            if self._schedule_is_supported(slot)
        )
        if not menu_options:
            return self.async_abort(reason="schedules_not_supported")
        return self.async_show_menu(
            step_id="init",
            menu_options=menu_options,
        )

    async def _async_read_valve_settings(self) -> dict[str, Any]:
        """Read valve settings directly so the form never shows stale values."""
        coordinator = self.config_entry.runtime_data
        async with coordinator.operation_lock:
            name = await coordinator.client.read_char(Valve1.name)
            duration_seconds = await coordinator.client.read_char(
                Valve1.manual_watering_duration
            )
        return {
            CONF_VALVE_NAME: name,
            CONF_MANUAL_WATERING_MINUTES: manual_minutes_from_seconds(
                duration_seconds
            ),
        }

    def _valve_settings_schema(self, defaults: dict[str, Any]) -> vol.Schema:
        """Return the valve settings schema."""
        return vol.Schema(
            {
                vol.Required(
                    CONF_VALVE_NAME, default=defaults[CONF_VALVE_NAME]
                ): vol.All(str, vol.Length(min=1, max=20)),
                vol.Required(
                    CONF_MANUAL_WATERING_MINUTES,
                    default=defaults[CONF_MANUAL_WATERING_MINUTES],
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_MANUAL_WATERING_MINUTES,
                        max=MAX_MANUAL_WATERING_MINUTES,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
            }
        )

    async def async_step_valve_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the valve name and default manual watering duration."""
        errors: dict[str, str] = {}
        try:
            defaults = await self._async_read_valve_settings()
        except (CharacteristicNotFound, CommunicationFailure, HomeAssistantError):
            _LOGGER.exception("Unable to read valve settings")
            defaults = {
                CONF_VALVE_NAME: "Ventil 1",
                CONF_MANUAL_WATERING_MINUTES: 30,
            }
            if user_input is None:
                errors["base"] = "cannot_read_valve_settings"

        if user_input is not None:
            try:
                duration_seconds = manual_seconds_from_minutes(
                    user_input[CONF_MANUAL_WATERING_MINUTES]
                )
            except ValueError:
                errors[CONF_MANUAL_WATERING_MINUTES] = (
                    "manual_watering_minutes_invalid"
                )
            else:
                try:
                    await self.config_entry.runtime_data.write(
                        Valve1.name, user_input[CONF_VALVE_NAME]
                    )
                    await self.config_entry.runtime_data.write(
                        Valve1.manual_watering_duration, duration_seconds
                    )
                except HomeAssistantError:
                    _LOGGER.exception("Unable to update valve settings")
                    errors["base"] = "cannot_update_valve_settings"

            if not errors:
                return self.async_create_entry(
                    title="", data=dict(self.config_entry.options)
                )
            defaults = user_input

        return self.async_show_form(
            step_id="valve_settings",
            data_schema=self._valve_settings_schema(defaults),
            errors=errors,
        )

    async def _async_get_defaults(self, slot: int) -> dict[str, Any]:
        """Read one slot and build values for the editor form."""
        if slot in self._defaults:
            return self._defaults[slot]

        decoded = await async_read_schedule(self.config_entry.runtime_data, slot)
        start = decoded.start_time
        end = decoded.end_time
        if start is None or end is None or end <= start:
            start = time(6, 0)
            end = time(6, 30)
        defaults = {
            CONF_ENABLED: decoded.active,
            CONF_START_TIME: start.isoformat(),
            CONF_END_TIME: end.isoformat(),
            CONF_WEEKDAYS: list(decoded.weekdays) or list(WEEKDAY_ORDER),
        }
        self._defaults[slot] = defaults
        return defaults

    def _schedule_schema(self, defaults: dict[str, Any]) -> vol.Schema:
        """Return the common schedule editor schema."""
        return vol.Schema(
            {
                vol.Required(
                    CONF_ENABLED, default=defaults[CONF_ENABLED]
                ): BooleanSelector(),
                vol.Required(
                    CONF_START_TIME, default=defaults[CONF_START_TIME]
                ): TimeSelector(),
                vol.Required(
                    CONF_END_TIME, default=defaults[CONF_END_TIME]
                ): TimeSelector(),
                vol.Required(
                    CONF_WEEKDAYS, default=defaults[CONF_WEEKDAYS]
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(WEEKDAY_ORDER),
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="weekday",
                    )
                ),
            }
        )

    async def _async_schedule_step(
        self, slot: int, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Edit, enable, disable, or clear one schedule slot."""
        errors: dict[str, str] = {}
        try:
            defaults = await self._async_get_defaults(slot)
        except HomeAssistantError:
            _LOGGER.exception("Unable to read watering schedule slot %s", slot)
            defaults = {
                CONF_ENABLED: False,
                CONF_START_TIME: "06:00:00",
                CONF_END_TIME: "06:30:00",
                CONF_WEEKDAYS: list(WEEKDAY_ORDER),
            }
            self._defaults[slot] = defaults
            if user_input is None:
                errors["base"] = "cannot_read_schedule"

        if user_input is not None:
            enabled = user_input[CONF_ENABLED]
            if enabled:
                start = cv.time(user_input[CONF_START_TIME])
                end = cv.time(user_input[CONF_END_TIME])
                weekdays = list(user_input[CONF_WEEKDAYS])
                if end <= start:
                    errors["base"] = "schedule_end_not_after_start"
                elif not weekdays:
                    errors[CONF_WEEKDAYS] = "weekdays_required"
                else:
                    try:
                        await async_set_schedule(
                            self.config_entry.runtime_data,
                            slot,
                            start,
                            end,
                            weekdays,
                        )
                    except HomeAssistantError:
                        _LOGGER.exception(
                            "Unable to update watering schedule slot %s", slot
                        )
                        errors["base"] = "cannot_update_schedule"
            else:
                try:
                    await async_clear_schedule(self.config_entry.runtime_data, slot)
                except HomeAssistantError:
                    _LOGGER.exception(
                        "Unable to clear watering schedule slot %s", slot
                    )
                    errors["base"] = "cannot_update_schedule"

            if not errors:
                return self.async_create_entry(
                    title="", data=dict(self.config_entry.options)
                )
            defaults = user_input

        return self.async_show_form(
            step_id=f"schedule_{slot}",
            data_schema=self._schedule_schema(defaults),
            errors=errors,
            description_placeholders={"slot": str(slot)},
        )

    async def async_step_schedule_1(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit schedule slot 1."""
        return await self._async_schedule_step(1, user_input)

    async def async_step_schedule_2(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit schedule slot 2."""
        return await self._async_schedule_step(2, user_input)

    async def async_step_schedule_3(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit schedule slot 3."""
        return await self._async_schedule_step(3, user_input)
