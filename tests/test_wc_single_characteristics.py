"""Regression tests for the Smart Water Control ValveX characteristics."""

import asyncio
from datetime import datetime, time
import importlib.util
from pathlib import Path
import sys
import types
import unittest


def _load_vendored_library() -> None:
    """Make the vendored package importable without installing HA requirements."""
    if "bleak" not in sys.modules:
        def _register_uuids(values: object) -> None:
            """Stub Bleak's UUID registration during isolated tests."""
            del values

        bleak = types.ModuleType("bleak")
        bleak_uuids = types.ModuleType("bleak.uuids")
        bleak_uuids.register_uuids = _register_uuids
        setattr(bleak, "uuids", bleak_uuids)
        sys.modules["bleak"] = bleak
        sys.modules["bleak.uuids"] = bleak_uuids

    vendored = (
        Path(__file__).parents[1]
        / "custom_components"
        / "gardena_bluetooth"
        / "_vendored"
    )
    sys.path.insert(0, str(vendored))


_load_vendored_library()

from gardena_bluetooth.const import (  # noqa: E402
    HybridWaterControlDeviceConfiguration,
    Pump,
    Valve1,
    Valve2,
)
from gardena_bluetooth.parse import ProductType, Service  # noqa: E402
from gardena_bluetooth.schedule import (  # noqa: E402
    SCHEDULES,
    decode_schedule,
    decode_weekdays,
    encode_fixed_schedule,
    encode_weekdays,
)


def _load_schedule_manager():
    """Load schedule manager with minimal HA stubs for isolated tests."""
    homeassistant = types.ModuleType("homeassistant")
    homeassistant_exceptions = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        """Stub Home Assistant service error."""

    homeassistant_exceptions.HomeAssistantError = HomeAssistantError
    homeassistant.exceptions = homeassistant_exceptions
    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.exceptions", homeassistant_exceptions)

    path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "gardena_bluetooth"
        / "schedule_manager.py"
    )
    spec = importlib.util.spec_from_file_location("schedule_manager_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load schedule manager")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, HomeAssistantError


SCHEDULE_MANAGER, HomeAssistantError = _load_schedule_manager()


class FakeScheduleClient:
    """In-memory raw characteristic client with optional write failure."""

    def __init__(self, values: dict[str, bytes], fail_uuid: str | None = None):
        self.values = dict(values)
        self.fail_uuid = fail_uuid
        self.failed = False
        self.writes: list[tuple[str, bytes]] = []

    async def read_char_raw(self, uuid: str) -> bytes:
        return self.values[uuid]

    async def write_char_raw(self, uuid: str, value: bytes) -> None:
        self.writes.append((uuid, value))
        if uuid == self.fail_uuid and not self.failed:
            self.failed = True
            raise RuntimeError("simulated write failure")
        self.values[uuid] = value


class FakeScheduleCoordinator:
    """Minimum coordinator surface required by schedule transactions."""

    def __init__(self, client: FakeScheduleClient):
        self.client = client
        self.raw_characteristics = set(client.values)
        self.operation_lock = asyncio.Lock()
        self.cached_snapshot: dict[str, bytes] | None = None

    def cache_schedule_snapshot(self, snapshot: dict[str, bytes]) -> None:
        self.cached_snapshot = dict(snapshot)


def _empty_schedule_values(slot: int) -> dict[str, bytes]:
    schedule = SCHEDULES[slot - 1]
    return {
        schedule.start_reference: bytes(1),
        schedule.start_offset: bytes(4),
        schedule.end_reference: bytes(1),
        schedule.end_offset: bytes(4),
        schedule.repetition_type: bytes(1),
        schedule.repetition_value: bytes(4),
        schedule.actuator: bytes(1),
        schedule.pre_offset: bytes(2),
    }


class ValveXCharacteristicTests(unittest.TestCase):
    """Validate diagnostic characteristic UUIDs and encodings."""

    def test_valve1_diagnostic_characteristic_uuids(self) -> None:
        """Valve 1 uses the G-19033 actuator resource UUIDs."""
        self.assertTrue(Valve1.error.uuid.startswith("98bda003"))
        self.assertTrue(Valve1.paused_until.uuid.startswith("98bda004"))
        self.assertTrue(Valve1.name.uuid.startswith("98bda005"))
        self.assertTrue(Valve1.reset_error.uuid.startswith("98bda022"))

    def test_valve2_diagnostic_characteristic_uuids(self) -> None:
        """Valve 2 follows the corresponding second-instance UUID layout."""
        self.assertTrue(Valve2.error.uuid.startswith("98bda103"))
        self.assertTrue(Valve2.paused_until.uuid.startswith("98bda104"))
        self.assertTrue(Valve2.name.uuid.startswith("98bda105"))
        self.assertTrue(Valve2.reset_error.uuid.startswith("98bda122"))

    def test_valve_name_utf8_round_trip(self) -> None:
        """Actuator names preserve UTF-8 characters."""
        value = "Garten Süd"
        self.assertEqual(Valve1.name.decode(Valve1.name.encode(value)), value)

    def test_pause_timestamp_round_trip(self) -> None:
        """Pause timestamps use the eight-byte Gen-2 BLE encoding."""
        value = datetime(2026, 8, 30, 18, 42, 19)
        encoded = Valve1.paused_until.encode(value)
        self.assertEqual(len(encoded), 8)
        self.assertEqual(Valve1.paused_until.decode(encoded), value)

    def test_reset_error_has_empty_execute_payload(self) -> None:
        """A parameterless LwM2M Execute is represented by an empty payload."""
        self.assertEqual(Valve1.reset_error.encode({}), b"")

    def test_water_diagnostic_characteristic_uuids(self) -> None:
        """The optional pump telemetry block uses UUIDs 0101 through 0104."""
        self.assertTrue(Pump.status.uuid.startswith("98bd0101"))
        self.assertTrue(Pump.tank_preassure.uuid.startswith("98bd0102"))
        self.assertTrue(Pump.flow_rate.uuid.startswith("98bd0103"))
        self.assertTrue(Pump.ptu_mode.uuid.startswith("98bd0104"))

    def test_water_computer_timestamp_characteristic(self) -> None:
        """The G-19033 0101 value is its four-byte Unix device clock."""
        timestamp = HybridWaterControlDeviceConfiguration.unix_timestamp
        self.assertTrue(timestamp.uuid.startswith("98bd0101"))
        value = datetime(2026, 8, 31, 12, 34, 56)
        encoded = timestamp.encode(value)
        self.assertEqual(len(encoded), 4)
        self.assertEqual(timestamp.decode(encoded), value)

    def test_0100_service_has_product_specific_meaning(self) -> None:
        """Water controls must not decode their clock with pump semantics."""
        service = Service.find_service(
            "98bd0100-0b0e-421a-84e5-ddbf75dc6de4",
            ProductType.WATER_COMPUTER,
        )
        self.assertIs(service, HybridWaterControlDeviceConfiguration)

    def test_water_diagnostic_uint16_decoding(self) -> None:
        """Pressure and flow raw values are unsigned little-endian integers."""
        self.assertEqual(Pump.tank_preassure.decode(bytes.fromhex("e803")), 1000)
        self.assertEqual(Pump.flow_rate.decode(bytes.fromhex("1500")), 21)

    def test_schedule_uuid_layout(self) -> None:
        """The three slots use Gen-2 instances 0, 1 and 2."""
        self.assertTrue(SCHEDULES[0].start_reference.startswith("98bdd001"))
        self.assertTrue(SCHEDULES[1].repetition_value.startswith("98bdd107"))
        self.assertTrue(SCHEDULES[2].pre_offset.startswith("98bdd209"))

    def test_weekday_mask_round_trip(self) -> None:
        """Weekday names use Gardena's documented bit representation."""
        weekdays = ["monday", "wednesday", "friday"]
        self.assertEqual(encode_weekdays(weekdays), 0x15)
        self.assertEqual(decode_weekdays(0x15), tuple(weekdays))

    def test_fixed_schedule_round_trip(self) -> None:
        """Fixed-time schedules encode field widths and values correctly."""
        schedule = SCHEDULES[2]
        encoded = encode_fixed_schedule(
            schedule,
            time(6, 15),
            time(6, 45),
            ["monday", "wednesday", "friday"],
        )
        raw = {
            **encoded,
            schedule.actuator: b"\x00",
            schedule.pre_offset: b"\x00\x00",
        }
        decoded = decode_schedule(schedule, raw)
        self.assertEqual(encoded[schedule.end_reference], b"\x04")
        self.assertEqual(
            encoded[schedule.end_offset], bytes.fromhex("08070000")
        )
        self.assertEqual(decoded.start_time, time(6, 15))
        self.assertEqual(decoded.end_time, time(6, 45))
        self.assertEqual(decoded.duration_seconds, 30 * 60)
        self.assertEqual(decoded.weekdays, ("monday", "wednesday", "friday"))
        self.assertTrue(decoded.supported)

    def test_legacy_absolute_end_time_is_still_decoded(self) -> None:
        """Schedules previously written with an absolute end remain readable."""
        schedule = SCHEDULES[0]
        raw = {
            schedule.start_reference: b"\x00",
            schedule.start_offset: (6 * 3600).to_bytes(4, "little"),
            schedule.end_reference: b"\x00",
            schedule.end_offset: (6 * 3600 + 900).to_bytes(4, "little"),
            schedule.repetition_type: b"\x02",
            schedule.repetition_value: bytes.fromhex("7f000000"),
            schedule.actuator: b"\x00",
            schedule.pre_offset: b"\x00\x00",
        }
        decoded = decode_schedule(schedule, raw)
        self.assertEqual(decoded.end_time, time(6, 15))
        self.assertEqual(decoded.duration_seconds, 900)
        self.assertTrue(decoded.supported)

    def test_fixed_schedule_rejects_invalid_ranges(self) -> None:
        """Empty weekday lists and overnight ranges are rejected."""
        schedule = SCHEDULES[0]
        with self.assertRaises(ValueError):
            encode_fixed_schedule(schedule, time(6), time(7), [])
        with self.assertRaises(ValueError):
            encode_fixed_schedule(
                schedule, time(23), time(1), ["monday"]
            )


class ScheduleTransactionTests(unittest.IsolatedAsyncioTestCase):
    """Validate safety ordering and rollback of raw schedule writes."""

    async def test_actuator_assignment_commits_enabled_schedule(self) -> None:
        schedule = SCHEDULES[2]
        client = FakeScheduleClient(_empty_schedule_values(3))
        coordinator = FakeScheduleCoordinator(client)

        await SCHEDULE_MANAGER.async_set_schedule(
            coordinator,
            3,
            time(6, 15),
            time(6, 45),
            ["monday"],
        )

        self.assertEqual(client.writes[0], (schedule.repetition_value, bytes(4)))
        self.assertEqual(client.writes[-1], (schedule.actuator, b"\x00"))
        self.assertEqual(
            client.writes[-2],
            (schedule.repetition_value, bytes.fromhex("01000000")),
        )
        self.assertEqual(
            coordinator.cached_snapshot[schedule.repetition_value],
            bytes.fromhex("01000000"),
        )

    async def test_failed_update_restores_previous_schedule(self) -> None:
        schedule = SCHEDULES[2]
        original = {
            **_empty_schedule_values(3),
            **encode_fixed_schedule(
                schedule,
                time(5, 0),
                time(5, 30),
                ["tuesday"],
            ),
        }
        client = FakeScheduleClient(original, fail_uuid=schedule.end_offset)
        coordinator = FakeScheduleCoordinator(client)

        with self.assertRaises(HomeAssistantError):
            await SCHEDULE_MANAGER.async_set_schedule(
                coordinator,
                3,
                time(6, 15),
                time(6, 45),
                ["monday"],
            )

        self.assertEqual(client.values, original)
        self.assertEqual(
            client.writes[-1],
            (schedule.repetition_value, original[schedule.repetition_value]),
        )

    async def test_clear_preserves_actuator_and_backend_metadata(self) -> None:
        schedule = SCHEDULES[2]
        original = {
            **_empty_schedule_values(3),
            **encode_fixed_schedule(
                schedule,
                time(5, 0),
                time(5, 30),
                ["tuesday"],
            ),
            schedule.pre_offset: bytes.fromhex("3412"),
        }
        client = FakeScheduleClient(original)
        coordinator = FakeScheduleCoordinator(client)

        await SCHEDULE_MANAGER.async_clear_schedule(coordinator, 3)

        self.assertEqual(client.writes[0], (schedule.repetition_value, bytes(4)))
        self.assertEqual(client.values[schedule.repetition_value], bytes(4))
        self.assertEqual(client.values[schedule.actuator], original[schedule.actuator])
        self.assertEqual(
            client.values[schedule.pre_offset], original[schedule.pre_offset]
        )


if __name__ == "__main__":
    unittest.main()
