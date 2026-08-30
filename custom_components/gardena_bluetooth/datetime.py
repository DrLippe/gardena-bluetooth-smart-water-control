"""Support for datetime entities."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from gardena_bluetooth.const import Valve1, Valve2
from gardena_bluetooth.parse import CharacteristicTime

from homeassistant.components.datetime import DateTimeEntity, DateTimeEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import GardenaBluetoothConfigEntry
from .entity import GardenaBluetoothDescriptorEntity


@dataclass(frozen=True)
class GardenaBluetoothDateTimeEntityDescription(DateTimeEntityDescription):
    """Description of a Gardena Bluetooth datetime entity."""

    char: CharacteristicTime = field(default_factory=lambda: CharacteristicTime(""))

    @property
    def context(self) -> set[str]:
        """Context needed for update coordinator."""
        return {self.char.uuid}


DESCRIPTIONS = (
    GardenaBluetoothDateTimeEntityDescription(
        key=Valve1.paused_until.unique_id,
        translation_key="paused_until_valve_1",
        entity_category=EntityCategory.CONFIG,
        char=Valve1.paused_until,
    ),
    GardenaBluetoothDateTimeEntityDescription(
        key=Valve2.paused_until.unique_id,
        translation_key="paused_until_valve_2",
        entity_category=EntityCategory.CONFIG,
        char=Valve2.paused_until,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaBluetoothConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up datetime entities based on a config entry."""
    coordinator = entry.runtime_data
    entities = [
        GardenaBluetoothDateTimeEntity(
            coordinator, description, description.context
        )
        for description in DESCRIPTIONS
        if description.char.unique_id in coordinator.characteristics
    ]
    async_add_entities(entities)


class GardenaBluetoothDateTimeEntity(
    GardenaBluetoothDescriptorEntity, DateTimeEntity
):
    """Representation of a Gardena Bluetooth datetime."""

    entity_description: GardenaBluetoothDateTimeEntityDescription

    @property
    def native_value(self) -> datetime | None:
        """Return the pause end as a timezone-aware UTC datetime."""
        value = self.coordinator.get_cached(self.entity_description.char)
        if value is None or value <= datetime(1970, 1, 1):
            return None
        return value.replace(tzinfo=UTC)

    async def async_set_value(self, value: datetime) -> None:
        """Set the pause end timestamp."""
        value_utc = dt_util.as_utc(value).replace(tzinfo=None)
        await self.coordinator.write(self.entity_description.char, value_utc)
