"""Support for button entities."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import logging

from gardena_bluetooth.const import Reset, Valve1, Valve2
from gardena_bluetooth.exceptions import GardenaBluetoothException
from gardena_bluetooth.parse import CharacteristicBool, CharacteristicIntKeys

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GardenaBluetoothConfigEntry, DeviceUnavailable
from .entity import GardenaBluetoothDescriptorEntity, GardenaBluetoothEntity

LOGGER = logging.getLogger(__name__)

SCHEDULE_3_UUIDS = (
    "98bdd201-0b0e-421a-84e5-ddbf75dc6de4",
    "98bdd202-0b0e-421a-84e5-ddbf75dc6de4",
    "98bdd203-0b0e-421a-84e5-ddbf75dc6de4",
    "98bdd204-0b0e-421a-84e5-ddbf75dc6de4",
    "98bdd206-0b0e-421a-84e5-ddbf75dc6de4",
    "98bdd207-0b0e-421a-84e5-ddbf75dc6de4",
    "98bdd208-0b0e-421a-84e5-ddbf75dc6de4",
    "98bdd209-0b0e-421a-84e5-ddbf75dc6de4",
)
SCHEDULE_3_START_UUID = SCHEDULE_3_UUIDS[1]
SCHEDULE_3_END_UUID = SCHEDULE_3_UUIDS[3]
SCHEDULE_3_START_REFERENCE_UUID = SCHEDULE_3_UUIDS[0]
SCHEDULE_3_END_REFERENCE_UUID = SCHEDULE_3_UUIDS[2]
SCHEDULE_3_REPETITION_UUID = SCHEDULE_3_UUIDS[4]
TEST_START_SECONDS = 6 * 3600 + 17 * 60
TEST_END_SECONDS = TEST_START_SECONDS + 13 * 60
FULL_TEST_START_OFFSET = 17 * 60
FULL_TEST_END_OFFSET = 30 * 60
FULL_TEST_REFERENCE = 1
FULL_TEST_REPETITION = 0x02


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
    try:
        raw_characteristics = await coordinator.client.get_all_characteristics_uuid()
    except (GardenaBluetoothException, DeviceUnavailable, TimeoutError) as exception:
        LOGGER.debug("Unable to discover schedule test characteristics: %s", exception)
    else:
        if set(SCHEDULE_3_UUIDS).issubset(raw_characteristics):
            entities.append(GardenaBluetoothScheduleWriteTestButton(coordinator))
            entities.append(GardenaBluetoothScheduleFullWriteTestButton(coordinator))
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


class GardenaBluetoothScheduleWriteTestButton(GardenaBluetoothEntity, ButtonEntity):
    """Safely test writes to an inactive Gen-2 schedule slot."""

    _attr_translation_key = "test_schedule_write"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator) -> None:
        """Initialize the schedule write test button."""
        super().__init__(coordinator, set())
        self._attr_unique_id = f"{coordinator.address}-schedule-write-test"

    async def async_press(self) -> None:
        """Write two harmless offsets, verify them, and restore the slot."""
        paused_until = await self.coordinator.client.read_char(Valve1.paused_until)
        minimum_pause = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10)
        if paused_until <= minimum_pause:
            raise HomeAssistantError(
                "Set 'Valve 1 paused until' to at least 10 minutes in the future "
                "before running the schedule write test"
            )

        originals = {
            uuid: await self.coordinator.client.read_char_raw(uuid)
            for uuid in SCHEDULE_3_UUIDS
        }
        if any(any(value) for value in originals.values()):
            raise HomeAssistantError(
                "Schedule slot 3 is no longer empty; refusing to modify it"
            )

        test_values = {
            SCHEDULE_3_START_UUID: TEST_START_SECONDS.to_bytes(
                4, "little", signed=True
            ),
            SCHEDULE_3_END_UUID: TEST_END_SECONDS.to_bytes(4, "little", signed=True),
        }
        written: dict[str, str] = {}
        restored_values: dict[str, str] = {}
        result: dict[str, object] = {
            "status": "running",
            "pause_until": paused_until.isoformat(),
            "original": {
                uuid.split("-", 1)[0]: value.hex()
                for uuid, value in originals.items()
            },
            "written": written,
            "restored": restored_values,
        }
        test_error: Exception | None = None

        try:
            for uuid, value in test_values.items():
                await self.coordinator.client.write_char_raw(uuid, value)
                readback = await self.coordinator.client.read_char_raw(uuid)
                written[uuid.split("-", 1)[0]] = readback.hex()
                if readback != value:
                    raise HomeAssistantError(
                        f"Schedule write verification failed for {uuid}"
                    )
            result["status"] = "verified"
        except Exception as exception:  # Cleanup must run for every write failure.
            test_error = exception
            result["status"] = "write_failed"
            result["error"] = type(exception).__name__
        finally:
            restore_errors: list[str] = []
            for uuid in test_values:
                try:
                    await self.coordinator.client.write_char_raw(uuid, originals[uuid])
                    restored = await self.coordinator.client.read_char_raw(uuid)
                    restored_values[uuid.split("-", 1)[0]] = restored.hex()
                    if restored != originals[uuid]:
                        restore_errors.append(uuid)
                except Exception:  # Report restoration failure in diagnostics.
                    restore_errors.append(uuid)

            if restore_errors:
                result["status"] = "restore_failed"
                result["restore_errors"] = restore_errors
            elif test_error is None:
                result["status"] = "verified_and_restored"

            self.coordinator.schedule_write_test_result = result

        if result["status"] == "restore_failed":
            raise HomeAssistantError(
                "Schedule write test could not restore all original values; "
                "keep watering paused and download diagnostics"
            )
        if test_error is not None:
            raise HomeAssistantError(
                f"Schedule write test failed: {type(test_error).__name__}"
            ) from test_error


class GardenaBluetoothScheduleFullWriteTestButton(
    GardenaBluetoothEntity, ButtonEntity
):
    """Temporarily create and then remove a paused Gen-2 schedule."""

    _attr_translation_key = "test_full_schedule_write"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator) -> None:
        """Initialize the full schedule write test button."""
        super().__init__(coordinator, set())
        self._attr_unique_id = f"{coordinator.address}-schedule-full-write-test"

    async def async_press(self) -> None:
        """Create a paused test schedule, inspect it, and restore the slot."""
        paused_until = await self.coordinator.client.read_char(Valve1.paused_until)
        minimum_pause = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=8)
        if paused_until <= minimum_pause:
            raise HomeAssistantError(
                "Set 'Valve 1 paused until' to at least 8 days in the future "
                "before running the full schedule write test"
            )

        originals = {
            uuid: await self.coordinator.client.read_char_raw(uuid)
            for uuid in SCHEDULE_3_UUIDS
        }
        if any(any(value) for value in originals.values()):
            raise HomeAssistantError(
                "Schedule slot 3 is no longer empty; refusing to modify it"
            )

        # Insertion order is safety-relevant: recurrence is written last.
        test_values = {
            SCHEDULE_3_START_REFERENCE_UUID: FULL_TEST_REFERENCE.to_bytes(1, "little"),
            SCHEDULE_3_START_UUID: FULL_TEST_START_OFFSET.to_bytes(
                4, "little", signed=True
            ),
            SCHEDULE_3_END_REFERENCE_UUID: FULL_TEST_REFERENCE.to_bytes(1, "little"),
            SCHEDULE_3_END_UUID: FULL_TEST_END_OFFSET.to_bytes(
                4, "little", signed=True
            ),
            SCHEDULE_3_REPETITION_UUID: FULL_TEST_REPETITION.to_bytes(1, "little"),
        }
        written: dict[str, str] = {}
        active_snapshot: dict[str, str] = {}
        restored_values: dict[str, str] = {}
        result: dict[str, object] = {
            "status": "running",
            "pause_until": paused_until.isoformat(),
            "original": {
                uuid.split("-", 1)[0]: value.hex()
                for uuid, value in originals.items()
            },
            "written": written,
            "active_snapshot": active_snapshot,
            "restored": restored_values,
        }
        test_error: Exception | None = None

        try:
            for uuid, value in test_values.items():
                await self.coordinator.client.write_char_raw(uuid, value)
                readback = await self.coordinator.client.read_char_raw(uuid)
                written[uuid.split("-", 1)[0]] = readback.hex()
                if readback != value:
                    raise HomeAssistantError(
                        f"Full schedule write verification failed for {uuid}"
                    )

            await asyncio.sleep(1)
            for uuid in SCHEDULE_3_UUIDS:
                value = await self.coordinator.client.read_char_raw(uuid)
                active_snapshot[uuid.split("-", 1)[0]] = value.hex()
            result["status"] = "verified"
        except Exception as exception:  # Cleanup must run for every write failure.
            test_error = exception
            result["status"] = "write_failed"
            result["error"] = type(exception).__name__
        finally:
            restore_errors: list[str] = []
            # Disable recurrence first, before restoring any timing fields.
            restore_order = (
                SCHEDULE_3_REPETITION_UUID,
                SCHEDULE_3_START_REFERENCE_UUID,
                SCHEDULE_3_START_UUID,
                SCHEDULE_3_END_REFERENCE_UUID,
                SCHEDULE_3_END_UUID,
            )
            for uuid in restore_order:
                try:
                    await self.coordinator.client.write_char_raw(uuid, originals[uuid])
                    restored = await self.coordinator.client.read_char_raw(uuid)
                    restored_values[uuid.split("-", 1)[0]] = restored.hex()
                    if restored != originals[uuid]:
                        restore_errors.append(uuid)
                except Exception:  # Report restoration failure in diagnostics.
                    restore_errors.append(uuid)

            final_snapshot: dict[str, bytes] = {}
            final_snapshot_result: dict[str, str] = {}
            for uuid in SCHEDULE_3_UUIDS:
                try:
                    value = await self.coordinator.client.read_char_raw(uuid)
                except Exception as exception:
                    final_snapshot_result[uuid.split("-", 1)[0]] = (
                        f"error:{type(exception).__name__}"
                    )
                    if uuid not in restore_errors:
                        restore_errors.append(uuid)
                else:
                    final_snapshot[uuid] = value
                    final_snapshot_result[uuid.split("-", 1)[0]] = value.hex()
            result["final_snapshot"] = final_snapshot_result
            restore_errors.extend(
                uuid
                for uuid, value in final_snapshot.items()
                if value != originals[uuid] and uuid not in restore_errors
            )

            if restore_errors:
                result["status"] = "restore_failed"
                result["restore_errors"] = restore_errors
            elif test_error is None:
                result["status"] = "verified_and_restored"

            self.coordinator.schedule_full_write_test_result = result

        if result["status"] == "restore_failed":
            raise HomeAssistantError(
                "Full schedule write test could not restore all original values; "
                "keep watering paused and download diagnostics"
            )
        if test_error is not None:
            raise HomeAssistantError(
                f"Full schedule write test failed: {type(test_error).__name__}"
            ) from test_error
