"""Support for number entities."""

from dataclasses import dataclass, field

from gardena_bluetooth.const import (
    AquaContourWatering,
    DeviceConfiguration,
    HybridWaterControlDeviceConfiguration,
    Sensor,
    Spray,
    Valve,
    Valve1,
    Valve2,
)
from gardena_bluetooth.parse import (
    Characteristic,
    CharacteristicInt,
    CharacteristicLong,
    CharacteristicUInt16,
)

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import DEGREE, PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GardenaBluetoothConfigEntry, GardenaBluetoothCoordinator
from .entity import GardenaBluetoothDescriptorEntity, GardenaBluetoothEntity
from .seasonal import reduction_from_runtime, runtime_from_reduction


@dataclass(frozen=True)
class GardenaBluetoothNumberEntityDescription(NumberEntityDescription):
    """Description of entity."""

    char: CharacteristicInt | CharacteristicUInt16 | CharacteristicLong = field(
        default_factory=lambda: CharacteristicInt("")
    )
    connected_state: Characteristic | None = None
    scale: float = 1.0

    @property
    def context(self) -> set[str]:
        """Context needed for update coordinator."""
        data = {self.char.uuid}
        if self.connected_state:
            data.add(self.connected_state.uuid)
        return data


DESCRIPTIONS = (
    GardenaBluetoothNumberEntityDescription(
        key=Valve.manual_watering_time.unique_id,
        translation_key="manual_watering_time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        native_min_value=0.0,
        native_max_value=24 * 60 * 60,
        native_step=60,
        entity_category=EntityCategory.CONFIG,
        char=Valve.manual_watering_time,
        device_class=NumberDeviceClass.DURATION,
    ),
    GardenaBluetoothNumberEntityDescription(
        key=AquaContourWatering.manual_watering_time.unique_id,
        translation_key="manual_watering_time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        native_min_value=0.0,
        native_max_value=24 * 60 * 60,
        native_step=60,
        entity_category=EntityCategory.CONFIG,
        char=AquaContourWatering.manual_watering_time,
        device_class=NumberDeviceClass.DURATION,
    ),
    # Smart Water Control family (Valve1/Valve2) — newer manual duration
    # characteristic, accepts the same uint32 LE seconds format.
    GardenaBluetoothNumberEntityDescription(
        key=Valve1.manual_watering_duration.unique_id,
        translation_key="manual_watering_duration_valve_1",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        native_min_value=0.0,
        native_max_value=24 * 60 * 60,
        native_step=60,
        entity_category=EntityCategory.CONFIG,
        char=Valve1.manual_watering_duration,
        device_class=NumberDeviceClass.DURATION,
    ),
    GardenaBluetoothNumberEntityDescription(
        key=Valve2.manual_watering_duration.unique_id,
        translation_key="manual_watering_duration_valve_2",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        native_min_value=0.0,
        native_max_value=24 * 60 * 60,
        native_step=60,
        entity_category=EntityCategory.CONFIG,
        char=Valve2.manual_watering_duration,
        device_class=NumberDeviceClass.DURATION,
    ),
    GardenaBluetoothNumberEntityDescription(
        key=Valve.remaining_open_time.unique_id,
        translation_key="remaining_open_time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=0.0,
        native_max_value=24 * 60 * 60,
        native_step=60.0,
        entity_category=EntityCategory.DIAGNOSTIC,
        char=Valve.remaining_open_time,
        device_class=NumberDeviceClass.DURATION,
    ),
    GardenaBluetoothNumberEntityDescription(
        key=DeviceConfiguration.rain_pause.unique_id,
        translation_key="rain_pause",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode=NumberMode.BOX,
        native_min_value=0.0,
        native_max_value=7 * 24 * 60,
        native_step=6 * 60.0,
        entity_category=EntityCategory.CONFIG,
        char=DeviceConfiguration.rain_pause,
        device_class=NumberDeviceClass.DURATION,
    ),
    GardenaBluetoothNumberEntityDescription(
        key=DeviceConfiguration.seasonal_adjust.unique_id,
        translation_key="seasonal_adjust",
        native_unit_of_measurement=UnitOfTime.DAYS,
        mode=NumberMode.BOX,
        native_min_value=-128.0,
        native_max_value=127.0,
        native_step=1.0,
        entity_category=EntityCategory.CONFIG,
        char=DeviceConfiguration.seasonal_adjust,
        device_class=NumberDeviceClass.DURATION,
    ),
    GardenaBluetoothNumberEntityDescription(
        key=Sensor.threshold.unique_id,
        translation_key="sensor_threshold",
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.BOX,
        native_min_value=0.0,
        native_max_value=100.0,
        native_step=1.0,
        entity_category=EntityCategory.CONFIG,
        char=Sensor.threshold,
        connected_state=Sensor.connected_state,
    ),
    GardenaBluetoothNumberEntityDescription(
        key="spray_sector",
        translation_key="spray_sector",
        native_unit_of_measurement=DEGREE,
        mode=NumberMode.BOX,
        native_min_value=0.0,
        native_max_value=359.0,
        native_step=1.0,
        entity_category=EntityCategory.CONFIG,
        char=Spray.sector,
    ),
    GardenaBluetoothNumberEntityDescription(
        key="spray_distance",
        translation_key="spray_distance",
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        native_min_value=0.0,
        native_max_value=100.0,
        native_step=0.1,
        char=Spray.distance,
        entity_category=EntityCategory.CONFIG,
        scale=10.0,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaBluetoothConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up entity based on a config entry."""
    coordinator = entry.runtime_data
    entities: list[NumberEntity] = [
        GardenaBluetoothNumber(coordinator, description, description.context)
        for description in DESCRIPTIONS
        if description.char.unique_id in coordinator.characteristics
    ]
    if Valve.remaining_open_time.unique_id in coordinator.characteristics:
        entities.append(GardenaBluetoothRemainingOpenSetNumber(coordinator))
    if (
        HybridWaterControlDeviceConfiguration.seasonal_runtime.unique_id
        in coordinator.characteristics
    ):
        entities.append(GardenaBluetoothSeasonalReductionNumber(coordinator))
    async_add_entities(entities)


class GardenaBluetoothNumber(GardenaBluetoothDescriptorEntity, NumberEntity):
    """Representation of a number."""

    entity_description: GardenaBluetoothNumberEntityDescription

    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.get_cached(self.entity_description.char)
        if data is None:
            self._attr_native_value = None
        else:
            self._attr_native_value = float(data) / self.entity_description.scale

        if char := self.entity_description.connected_state:
            self._attr_available = bool(self.coordinator.get_cached(char))
        else:
            self._attr_available = True

        super()._handle_coordinator_update()

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self.coordinator.write(
            self.entity_description.char, int(value * self.entity_description.scale)
        )
        self.async_write_ha_state()


class GardenaBluetoothRemainingOpenSetNumber(GardenaBluetoothEntity, NumberEntity):
    """Representation of a entity with remaining time."""

    _attr_translation_key = "remaining_open_set"
    _attr_native_unit_of_measurement = "min"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.0
    _attr_native_max_value = 24 * 60
    _attr_native_step = 1.0
    _attr_device_class = NumberDeviceClass.DURATION

    def __init__(
        self,
        coordinator: GardenaBluetoothCoordinator,
    ) -> None:
        """Initialize the remaining time entity."""
        super().__init__(coordinator, {Valve.remaining_open_time.uuid})
        self._attr_unique_id = f"{coordinator.address}-remaining_open_set"

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self.coordinator.write(Valve.remaining_open_time, int(value * 60))
        self.async_write_ha_state()


class GardenaBluetoothSeasonalReductionNumber(GardenaBluetoothEntity, NumberEntity):
    """User-facing seasonal reduction for the Smart Water Control."""

    _attr_translation_key = "seasonal_reduction"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: GardenaBluetoothCoordinator) -> None:
        """Initialize the seasonal reduction entity."""
        char = HybridWaterControlDeviceConfiguration.seasonal_runtime
        super().__init__(coordinator, {char.uuid})
        self._attr_unique_id = f"{coordinator.address}-seasonal-reduction"

    def _handle_coordinator_update(self) -> None:
        """Convert the remaining-runtime value reported by the device."""
        char = HybridWaterControlDeviceConfiguration.seasonal_runtime
        runtime = self.coordinator.get_cached(char)
        if runtime is None:
            self._attr_native_value = None
        else:
            try:
                self._attr_native_value = reduction_from_runtime(runtime)
            except ValueError:
                self._attr_native_value = None
        super()._handle_coordinator_update()

    async def async_set_native_value(self, value: float) -> None:
        """Set the seasonal reduction percentage."""
        char = HybridWaterControlDeviceConfiguration.seasonal_runtime
        await self.coordinator.write(char, runtime_from_reduction(value))
        self.async_write_ha_state()
