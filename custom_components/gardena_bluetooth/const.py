"""Constants for the Gardena Bluetooth integration."""

DOMAIN = "gardena_bluetooth"

# Product type stored in the config entry at pairing time. AquaPrecise /
# Aqua Contours devices only advertise their product TLV while in pairing
# mode, so setup must NOT depend on a live advertisement scan - after a
# restart that scan can never succeed until someone physically presses the
# pairing button. Entries created before this key existed are migrated on
# their first successful scan (see __init__.async_setup_entry).
CONF_PRODUCT_TYPE = "product_type"

# Serial number decoded from field 4 of the Gardena manufacturer-data TLV.
# Newer Smart Water Control devices do not expose the standard Bluetooth
# Device Information serial-number characteristic (0x2A25), but they do
# advertise the same identity as an integer.
CONF_SERIAL_NUMBER = "serial_number"
