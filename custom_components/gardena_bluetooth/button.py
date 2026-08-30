"""Support for button entities."""

from dataclasses import dataclass, field

from gardena_bluetooth.const import Reset, Valve1, Valve2
from gardena_bluetooth.parse import CharacteristicBool, CharacteristicIntKeys

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GardenaBluetoothConfigEntry
from .entity import GardenaBluetoothDescriptorEntity


@dataclass(frozen=True)
class GardenaBluetoothButtonEntityDescription(ButtonEntityDescription):
    """Description of entity."""

    char: CharacteristicBool | CharacteristicIntKeys = field(
        default_factory=lambda: CharacteristicBool("")
    )

    @property
    def context(self) -> set[str]:
        """Context needed for update coordinator."""
        # Execute-only LwM2M characteristics cannot be read and therefore must
        # not be included in the coordinator's polling context.
        if isinstance(self.char, CharacteristicIntKeys):
            return set()
        return {self.char.uuid}


DESCRIPTIONS = (
    GardenaBluetoothButtonEntityDescription(
        key=Reset.factory_reset.unique_id,
        translation_key="factory_reset",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        char=Reset.factory_reset,
    ),
    GardenaBluetoothButtonEntityDescription(
        key=Valve1.reset_error.unique_id,
        translation_key="reset_error_valve_1",
        entity_category=EntityCategory.DIAGNOSTIC,
        char=Valve1.reset_error,
    ),
    GardenaBluetoothButtonEntityDescription(
        key=Valve2.reset_error.unique_id,
        translation_key="reset_error_valve_2",
        entity_category=EntityCategory.DIAGNOSTIC,
        char=Valve2.reset_error,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaBluetoothConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up button based on a config entry."""
    coordinator = entry.runtime_data
    entities = [
        GardenaBluetoothButton(coordinator, description, description.context)
        for description in DESCRIPTIONS
        if description.char.unique_id in coordinator.characteristics
    ]
    async_add_entities(entities)


class GardenaBluetoothButton(GardenaBluetoothDescriptorEntity, ButtonEntity):
    """Representation of a button."""

    entity_description: GardenaBluetoothButtonEntityDescription

    async def async_press(self) -> None:
        """Trigger button action."""
        char = self.entity_description.char
        if isinstance(char, CharacteristicIntKeys):
            # LwM2M Execute without arguments is encoded as an empty payload.
            await self.coordinator.client.write_char(char, {})
            await self.coordinator.async_refresh()
            return
        await self.coordinator.write(char, True)
