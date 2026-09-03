# Gardena Bluetooth — Smart Water Control patch (G-19033 / G-19034)

**Stopgap custom integration that overrides the built-in `gardena_bluetooth`
component in Home Assistant with support for the newer Smart Water Control
family of devices (G-19033-20 `wc_single`, G-19034-20 `wc_dual`, G-19050-20
pipeline, …).**

These devices have been on sale since 2025 and are the direct successors of
the now-EOL Bluetooth-only 01889-20. The current built-in integration does
not discover or control them at all (home-assistant/core#167291,
home-assistant/discussions/3056).

## What this fork fixes

1. **Discovery** — The new family advertises only manufacturer data, no
   service UUIDs. Adds a second BT matcher with `manufacturer_id: 1062`
   only and relaxes the scanner / config-flow filters.
2. **Valve actuation** — Implements the LWM2M-Execute protocol the new
   devices expect (`0='18',1='<duration>'`), reverse-engineered from
   cloudless-garden/gardena-smart-local-api and verified live.
3. **Battery** — Exposes the standard BLE Battery Service (`0x180f`) for
   the Valve1/Valve2 family.
4. **Entities** — Adds `GardenaBluetoothValveX` (open/close), switch
   alias, manual-watering-duration number, remaining-time sensor,
   activation-reason sensor, valve-available binary sensor.
5. **Valve diagnostics** — Exposes the Valve1/Valve2 error code, a
   configurable `paused until` timestamp, and a button that resets the
   actuator error using the parameterless LWM2M Execute command.
6. **Valve settings** — Exposes the Gen-2 actuator name as a writable text
   entity (`98bda005` for valve 1 and `98bda105` for valve 2) and in the
   integration's Configure flow. Manual watering duration is presented as
   whole minutes from 1 to 90 and converted to device seconds when written.
7. **Device clock** — Synchronizes the G-1903x Unix clock (`98bd0101`) when
   Home Assistant connects and exposes it as diagnostic device time. Gardena's
   Android library confirms the value is a 32-bit little-endian Unix timestamp;
   without synchronization it restarts at zero after a battery change and
   prevents weekly schedules from running at the expected local time.
8. **Watering schedules** — Exposes all three Gen-2 schedule slots as sensors
   and adds `gardena_bluetooth.set_schedule` and
   `gardena_bluetooth.clear_schedule` actions. Fixed local start/end times and
   arbitrary weekday combinations are supported. Updates are transactional:
   recurrence is disabled first, enabled last, verified after every write, and
   the previous snapshot is restored after a failure.
9. **Schedule diagnostics** — The integration diagnostics still read the raw
   Gen-2 `98bdd...` blocks on demand for troubleshooting. Schedule masks are
   monitored every five minutes; full slot data is read only for active slots
   to keep BLE traffic and battery use low.
10. **Seasonal reduction** — Adds a 0–100% slider for the G-1903x seasonal
    watering reduction. The device stores the remaining runtime percentage,
    so the integration transparently maps a reduction of 80% to device value
    20.
11. **Schedule editor** — Adds a graphical editor under the integration's
    **Configure** button. Each of the three slots can be enabled, edited, or
    cleared without using Developer Tools. The existing actions remain
    available for automations.
12. **Device identity** — Reads the serial number from Gardena manufacturer
    data (TLV field 4) and displays it next to the firmware version in Home
    Assistant's device information.

## Watering schedule actions

For interactive editing, open **Settings → Devices & services → Gardena
Bluetooth → Configure**, choose a plan, then set its start time, end time and
weekdays. Turning **Enabled** off safely clears that slot.

Use **Developer Tools → Actions** or an automation to call
`gardena_bluetooth.set_schedule`. Select the Gardena config entry, a slot from
1 to 3, start/end time, and one or more weekdays. Calling
`gardena_bluetooth.clear_schedule` disables and clears the selected slot.

Schedules spanning midnight are intentionally rejected. Split them into two
slots instead. The device's actuator assignment and internal `pre_offset`
metadata are never overwritten.

## Status

* Verified live on a G-19033-20 (firmware 1.1.1).
* The upstream fixes are in flight:
  * Library — https://github.com/elupus/gardena-bluetooth/pull/49
  * HA component — https://github.com/home-assistant/core/pull/171759

Delete this custom integration once the official component picks up the
changes.

## Install via HACS

This repo is already structured for HACS: **HACS → Integrations → ⋮ →
Custom repositories → add `DrLippe/gardena-bluetooth-smart-water-control`
(category: Integration) → Install → Restart Home Assistant.**

Then **Settings → Devices & Services → Add Integration → Gardena Bluetooth**,
or wait for auto-discovery once the device is in BLE range.

## Pairing checklist

1. Power-cycle / factory-reset the device (hold Man. button while
   inserting the battery for ~10s — all 3 LEDs flash).
2. Ensure HA can reach the device via BLE (host adapter or an ESPHome
   Bluetooth proxy in range).
3. Watch Settings → Devices & Services — `G-19033` (or `G-19034`) should
   appear within ~30s.
