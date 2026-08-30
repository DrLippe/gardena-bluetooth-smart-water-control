"""Regression tests for the Smart Water Control ValveX characteristics."""

from datetime import datetime
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

from gardena_bluetooth.const import Valve1, Valve2  # noqa: E402


class ValveXCharacteristicTests(unittest.TestCase):
    """Validate diagnostic characteristic UUIDs and encodings."""

    def test_valve1_diagnostic_characteristic_uuids(self) -> None:
        """Valve 1 uses the G-19033 actuator resource UUIDs."""
        self.assertTrue(Valve1.error.uuid.startswith("98bda003"))
        self.assertTrue(Valve1.paused_until.uuid.startswith("98bda004"))
        self.assertTrue(Valve1.reset_error.uuid.startswith("98bda022"))

    def test_valve2_diagnostic_characteristic_uuids(self) -> None:
        """Valve 2 follows the corresponding second-instance UUID layout."""
        self.assertTrue(Valve2.error.uuid.startswith("98bda103"))
        self.assertTrue(Valve2.paused_until.uuid.startswith("98bda104"))
        self.assertTrue(Valve2.reset_error.uuid.startswith("98bda122"))

    def test_pause_timestamp_round_trip(self) -> None:
        """Pause timestamps use the eight-byte Gen-2 BLE encoding."""
        value = datetime(2026, 8, 30, 18, 42, 19)
        encoded = Valve1.paused_until.encode(value)
        self.assertEqual(len(encoded), 8)
        self.assertEqual(Valve1.paused_until.decode(encoded), value)

    def test_reset_error_has_empty_execute_payload(self) -> None:
        """A parameterless LwM2M Execute is represented by an empty payload."""
        self.assertEqual(Valve1.reset_error.encode({}), b"")


if __name__ == "__main__":
    unittest.main()
