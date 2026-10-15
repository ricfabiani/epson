"""XP-530 protocol constants; provenance and limits are in THIRD_PARTY.md."""

import ipaddress
import re

CONTROL_OID = "1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1"
MODEL_OID = "1.3.6.1.2.1.25.3.2.1.3.1"
DEVICE_ID_OID = "1.3.6.1.4.1.1248.1.2.2.1.1.1.1.1"
READ_KEY = bytes.fromhex("28 09")
WRITE_KEY = bytes.fromhex("4A 73 6A 74 68 62 73 6E")
SERIAL_ADDRESSES = tuple(range(0xD8, 0xE2))

# Preserve the database's ordered reset, including the repeated 0x06 write.
RESET_SEQUENCE = (
    (0x10, 0), (0x11, 0), (0x06, 0), (0x34, 0x5E),
    (0x14, 0), (0x15, 0), (0x12, 0), (0x13, 0),
    (0x06, 0), (0x35, 0x5E), (0x1ED, 0),
)
RESET_VALUES = dict(RESET_SEQUENCE)
COUNTERS = (
    ("Main waste pad", (0x10, 0x11), 4806),
    ("Borderless waste pad", (0x12, 0x13), 2082),
)


class PrinterError(Exception):
    """An actionable printer, transport, or validation failure."""


def validate_host(value: str) -> str:
    try:
        address = ipaddress.IPv4Address(value.strip())
    except ipaddress.AddressValueError as exc:
        raise PrinterError("Enter the printer's IPv4 address, for example 192.168.1.53.") from exc
    if address.is_multicast or address.is_unspecified or str(address) == "255.255.255.255":
        raise PrinterError("Enter an individual printer's IPv4 address.")
    return str(address)


def is_xp530(model: str) -> bool:
    return re.fullmatch(r"(?:EPSON\s+)?XP-530(?:\s+Series)?", model.strip(), re.I) is not None


def control_oid(payload: bytes) -> str:
    packet = b"||" + len(payload).to_bytes(2, "little") + payload
    return CONTROL_OID + "." + ".".join(map(str, packet))


def read_oid(address: int) -> str:
    return control_oid(READ_KEY + bytes.fromhex("41 BE A0") + address.to_bytes(2, "little"))


def write_oid(address: int, value: int) -> str:
    # This app deliberately exposes only the XP-530 waste-reset writes.
    if (address, value) not in RESET_SEQUENCE:
        raise PrinterError("The requested write is outside the XP-530 reset profile.")
    return control_oid(
        READ_KEY + bytes.fromhex("42 BD 21")
        + address.to_bytes(2, "little") + bytes([value]) + WRITE_KEY
    )
