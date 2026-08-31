"""Support for switch entities."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from gardena_bluetooth.const import (
    AquaContourBattery,
    AquaContourWatering,
    Battery,
    EventHistory,
    FlowStatistics,
    HybridWaterControlDeviceConfiguration,
    Pump,
    Sensor,
    Spray,
    Valve,
    Valve1,
    Valve2,
)
from gardena_bluetooth.parse import Characteristic, ProductType
from gardena_bluetooth.schedule import SCHEDULES, decode_schedule

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
    StateType,
)
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfPressure,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import GardenaBluetoothConfigEntry, GardenaBluetoothCoordinator
from .const import CONF_PRODUCT_TYPE
from .entity import GardenaBluetoothDescriptorEntity, GardenaBluetoothEntity

type SensorRawType = StateType | datetime


def _get_timestamp(value: datetime | None):
    if value is None:
        return None
    return value.replace(tzinfo=dt_util.get_default_time_zone())


def _get_distance_percentage(value: int | None) -> float | None:
    if value is None:
        return None
    return value / 10


@dataclass(frozen=True)
class GardenaBluetoothSensorEntityDescription[T](SensorEntityDescription):
    """Description of entity."""

    char: Characteristic[T] = field(default_factory=lambda: Characteristic(""))
    connected_state: Characteristic | None = None
    get: Callable[[T | None], SensorRawType] = lambda x: x  # type: ignore[assignment, return-value]

    @property
    def context(self) -> set[str]:
        """Context needed for update coordinator."""
        data = {self.char.uuid}
        if self.connected_state:
            data.add(self.connected_state.uuid)
        return data


DESCRIPTIONS = (
    GardenaBluetoothSensorEntityDescription(
        key=Valve.activation_reason.unique_id,
        translation_key="activation_reason",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        char=Valve.activation_reason,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=Valve1.activation_reason.unique_id,
        translation_key="activation_reason_valve_1",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        char=Valve1.activation_reason,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=Valve2.activation_reason.unique_id,
        translation_key="activation_reason_valve_2",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        char=Valve2.activation_reason,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=Valve1.error.unique_id,
        translation_key="error_code_valve_1",
        entity_category=EntityCategory.DIAGNOSTIC,
        char=Valve1.error,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=Valve2.error.unique_id,
        translation_key="error_code_valve_2",
        entity_category=EntityCategory.DIAGNOSTIC,
        char=Valve2.error,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=Battery.battery_level.unique_id,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        char=Battery.battery_level,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=AquaContourBattery.battery_level.unique_id,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        char=AquaContourBattery.battery_level,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=Sensor.battery_level.unique_id,
        translation_key="sensor_battery_level",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        char=Sensor.battery_level,
        connected_state=Sensor.connected_state,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=Sensor.value.unique_id,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.MOISTURE,
        native_unit_of_measurement=PERCENTAGE,
        char=Sensor.value,
        connected_state=Sensor.connected_state,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=Sensor.type.unique_id,
        translation_key="sensor_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        char=Sensor.type,
        connected_state=Sensor.connected_state,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=Sensor.measurement_timestamp.unique_id,
        translation_key="sensor_measurement_timestamp",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        char=Sensor.measurement_timestamp,
        connected_state=Sensor.connected_state,
        get=_get_timestamp,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=FlowStatistics.overall.unique_id,
        translation_key="flow_statistics_overall",
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.WATER,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        char=FlowStatistics.overall,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=FlowStatistics.current.unique_id,
        translation_key="flow_statistics_current",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
        char=FlowStatistics.current,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=FlowStatistics.resettable.unique_id,
        translation_key="flow_statistics_resettable",
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.WATER,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        char=FlowStatistics.resettable,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=FlowStatistics.last_reset.unique_id,
        translation_key="flow_statistics_reset_timestamp",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        char=FlowStatistics.last_reset,
        get=_get_timestamp,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=Spray.current_distance.unique_id,
        translation_key="spray_current_distance",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        char=Spray.current_distance,
        get=_get_distance_percentage,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=Spray.current_sector.unique_id,
        translation_key="spray_current_sector",
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=DEGREE,
        char=Spray.current_sector,
    ),
    GardenaBluetoothSensorEntityDescription(
        key="aqua_contour_error",
        translation_key="aqua_contour_error",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        char=EventHistory.error,
        get=lambda x: (
            x.error_code.name.lower()
            if x and isinstance(x.error_code, EventHistory.error.enum)
            else None
        ),
        options=[member.name.lower() for member in EventHistory.error.enum],
    ),
    GardenaBluetoothSensorEntityDescription(
        key="aqua_contour_error_timestamp",
        translation_key="error_timestamp",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        char=EventHistory.error,
        get=lambda x: _get_timestamp(x.time_stamp) if x else None,
    ),
)

PUMP_DESCRIPTIONS = (
    GardenaBluetoothSensorEntityDescription(
        key=Pump.status.unique_id,
        translation_key="pump_status_raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        char=Pump.status,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=Pump.tank_preassure.unique_id,
        translation_key="tank_pressure",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.PRESSURE,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfPressure.MBAR,
        suggested_unit_of_measurement=UnitOfPressure.BAR,
        suggested_display_precision=2,
        char=Pump.tank_preassure,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=Pump.flow_rate.unique_id,
        translation_key="pump_flow_rate_raw",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        char=Pump.flow_rate,
    ),
    GardenaBluetoothSensorEntityDescription(
        key=Pump.ptu_mode.unique_id,
        translation_key="ptu_mode_raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        char=Pump.ptu_mode,
    ),
)

WATER_COMPUTER_DIAGNOSTIC_DESCRIPTIONS = (
    GardenaBluetoothSensorEntityDescription(
        key=HybridWaterControlDeviceConfiguration.unix_timestamp.unique_id,
        translation_key="device_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        char=HybridWaterControlDeviceConfiguration.unix_timestamp,
        get=_get_timestamp,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaBluetoothConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Gardena Bluetooth sensor based on a config entry."""
    coordinator = entry.runtime_data
    try:
        product_type = ProductType[entry.data.get(CONF_PRODUCT_TYPE, "UNKNOWN")]
    except KeyError:
        product_type = ProductType.UNKNOWN

    descriptions = DESCRIPTIONS
    if product_type == ProductType.WATER_COMPUTER:
        descriptions += WATER_COMPUTER_DIAGNOSTIC_DESCRIPTIONS
    elif product_type in {
        ProductType.PUMP,
        ProductType.PRESSURE_TANKS,
        ProductType.AUTOMATS,
    }:
        descriptions += PUMP_DESCRIPTIONS

    entities: list[GardenaBluetoothEntity] = [
        GardenaBluetoothSensor(coordinator, description, description.context)
        for description in descriptions
        if description.char.unique_id in coordinator.characteristics
    ]
    if product_type == ProductType.WATER_COMPUTER:
        entities.extend(
            GardenaBluetoothScheduleSensor(coordinator, schedule)
            for schedule in SCHEDULES
            if set(schedule.uuids).issubset(coordinator.raw_characteristics)
        )
    if Valve.remaining_open_time.unique_id in coordinator.characteristics:
        entities.append(
            GardenaBluetoothRemainSensor(
                coordinator, Valve.remaining_open_time, "remaining_open_timestamp"
            )
        )
    if Valve1.remaining_time_open.unique_id in coordinator.characteristics:
        entities.append(
            GardenaBluetoothRemainSensor(
                coordinator,
                Valve1.remaining_time_open,
                "remaining_open_timestamp_valve_1",
            )
        )
    if Valve2.remaining_time_open.unique_id in coordinator.characteristics:
        entities.append(
            GardenaBluetoothRemainSensor(
                coordinator,
                Valve2.remaining_time_open,
                "remaining_open_timestamp_valve_2",
            )
        )
    if (
        AquaContourWatering.remaining_watering_time.unique_id
        in coordinator.characteristics
    ):
        entities.append(
            GardenaBluetoothRemainSensor(
                coordinator,
                AquaContourWatering.remaining_watering_time,
                "remaining_watering_timestamp",
            )
        )
    async_add_entities(entities)


class GardenaBluetoothSensor(GardenaBluetoothDescriptorEntity, SensorEntity):
    """Representation of a sensor."""

    entity_description: GardenaBluetoothSensorEntityDescription

    def _handle_coordinator_update(self) -> None:
        value = self.coordinator.get_cached(self.entity_description.char)
        value = self.entity_description.get(value)
        self._attr_native_value = value

        if char := self.entity_description.connected_state:
            self._attr_available = bool(self.coordinator.get_cached(char))
        else:
            self._attr_available = True

        super()._handle_coordinator_update()


class GardenaBluetoothScheduleSensor(GardenaBluetoothEntity, SensorEntity):
    """Representation of one Gen-2 watering schedule."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["disabled", "active", "unsupported"]

    def __init__(self, coordinator, schedule) -> None:
        """Initialize the schedule sensor."""
        super().__init__(coordinator, {schedule.repetition_value})
        self._schedule = schedule
        self._attr_unique_id = (
            f"{coordinator.address}-watering-schedule-{schedule.slot}"
        )
        self._attr_translation_key = "watering_schedule"
        self._attr_translation_placeholders = {"slot": str(schedule.slot)}

    def _handle_coordinator_update(self) -> None:
        mask = self.coordinator.data.get(self._schedule.repetition_value)
        if mask is None:
            self._attr_available = False
            self._attr_native_value = None
            self._attr_extra_state_attributes = None
            super()._handle_coordinator_update()
            return

        repetition_value = int.from_bytes(mask, "little")
        if repetition_value == 0:
            self._attr_available = True
            self._attr_native_value = "disabled"
            self._attr_extra_state_attributes = {"slot": self._schedule.slot}
            super()._handle_coordinator_update()
            return

        try:
            schedule = decode_schedule(self._schedule, self.coordinator.data)
        except ValueError:
            self._attr_available = False
            self._attr_native_value = None
            self._attr_extra_state_attributes = None
            super()._handle_coordinator_update()
            return

        self._attr_available = True
        self._attr_native_value = "active" if schedule.supported else "unsupported"
        self._attr_extra_state_attributes = {
            "slot": self._schedule.slot,
            "start_time": (
                schedule.start_time.isoformat() if schedule.start_time else None
            ),
            "end_time": schedule.end_time.isoformat() if schedule.end_time else None,
            "weekdays": list(schedule.weekdays),
            "start_reference": schedule.start_reference,
            "start_offset": schedule.start_offset,
            "end_reference": schedule.end_reference,
            "end_offset": schedule.end_offset,
            "repetition_type": schedule.repetition_type,
            "repetition_value": schedule.repetition_value,
            "actuator": schedule.actuator,
        }
        super()._handle_coordinator_update()


class GardenaBluetoothRemainSensor(GardenaBluetoothEntity, SensorEntity):
    """Representation of a sensor."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_native_value: datetime | None = None

    def __init__(
        self,
        coordinator: GardenaBluetoothCoordinator,
        char: Characteristic[int],
        key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, {char.uuid})
        self._attr_unique_id = f"{coordinator.address}-{key}"
        self._attr_translation_key = key
        self._char = char

    def _handle_coordinator_update(self) -> None:
        value = self.coordinator.get_cached(self._char)
        if not value:
            self._attr_native_value = None
            super()._handle_coordinator_update()
            return

        time = datetime.now(UTC) + timedelta(seconds=value)
        if not self._attr_native_value:
            self._attr_native_value = time
            super()._handle_coordinator_update()
            return

        error = time - self._attr_native_value
        if abs(error.total_seconds()) > 10:
            self._attr_native_value = time
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        """Sensor only available when open."""
        return super().available and self._attr_native_value is not None
