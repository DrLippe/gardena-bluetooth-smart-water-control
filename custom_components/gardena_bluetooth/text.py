"""Support for text entities."""

from dataclasses import dataclass

from gardena_bluetooth.const import (
    AquaContourContours,
    AquaContourPosition,
    Valve1,
    Valve2,
)
from gardena_bluetooth.parse import Characteristic

from homeassistant.components.text import TextEntity, TextEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GardenaBluetoothConfigEntry
from .entity import GardenaBluetoothDescriptorEntity


@dataclass(frozen=True, kw_only=True)
class GardenaBluetoothTextEntityDescription(TextEntityDescription):
    """Description of entity."""

    char: Characteristic[str]

    @property
    def context(self) -> set[str]:
        """Context needed for update coordinator."""
        return {self.char.uuid}


DESCRIPTIONS = (
    GardenaBluetoothTextEntityDescription(
        key=Valve1.name.unique_id,
        translation_key="valve_name_1",
        char=Valve1.name,
        native_max=20,
        entity_category=EntityCategory.CONFIG,
    ),
    GardenaBluetoothTextEntityDescription(
        key=Valve2.name.unique_id,
        translation_key="valve_name_2",
        char=Valve2.name,
        native_max=20,
        entity_category=EntityCategory.CONFIG,
    ),
    *(
        GardenaBluetoothTextEntityDescription(
            key=f"position_{i}_name",
            translation_key="position_name",
            translation_placeholders={"number": str(i)},
            has_entity_name=True,
            char=getattr(AquaContourPosition, f"position_name_{i}"),
            native_max=20,
            entity_category=EntityCategory.CONFIG,
        )
        for i in range(1, 6)
    ),
    *(
        GardenaBluetoothTextEntityDescription(
            key=f"contour_{i}_name",
            translation_key="contour_name",
            translation_placeholders={"number": str(i)},
            has_entity_name=True,
            char=getattr(AquaContourContours, f"contour_name_{i}"),
            native_max=20,
            entity_category=EntityCategory.CONFIG,
        )
        for i in range(1, 6)
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaBluetoothConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up text based on a config entry."""
    coordinator = entry.runtime_data
    entities = [
        GardenaBluetoothTextEntity(coordinator, description, description.context)
        for description in DESCRIPTIONS
        if description.char.unique_id in coordinator.characteristics
    ]
    async_add_entities(entities)


class GardenaBluetoothTextEntity(GardenaBluetoothDescriptorEntity, TextEntity):
    """Representation of a text entity."""

    entity_description: GardenaBluetoothTextEntityDescription

    @property
    def native_value(self) -> str | None:
        """Return the value reported by the text."""
        char = self.entity_description.char
        return self.coordinator.get_cached(char)

    async def async_set_value(self, value: str) -> None:
        """Change the text."""
        char = self.entity_description.char
        await self.coordinator.write(char, value)
