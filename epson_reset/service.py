"""Read-only inspection and a backed-up, checked XP-530 counter reset."""

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .profile import (
    COUNTERS, DEVICE_ID_OID, MODEL_OID, RESET_SEQUENCE, RESET_VALUES, SERIAL_ADDRESSES,
    PrinterError, is_xp530, read_oid, validate_host, write_oid,
)


@dataclass(frozen=True)
class Snapshot:
    host: str
    model: str
    serial: str
    memory: tuple[tuple[int, int], ...]

    @property
    def counters(self):
        cells = dict(self.memory)
        return tuple(
            (label, int.from_bytes(bytes(cells[a] for a in addresses), "little"), maximum)
            for label, addresses, maximum in COUNTERS
        )

    @property
    def flags(self):
        return dict(self.memory)[0x06]

    @property
    def already_reset(self):
        return dict(self.memory) == RESET_VALUES


@dataclass(frozen=True)
class ResetResult:
    snapshot: Snapshot
    backup: Path | None
    changed: bool


def backup_directory() -> Path:
    base = Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else Path.home()
    return base / "EpsonXP530Reset" / "backups"


class PrinterService:
    def __init__(self, transport):
        self.transport = transport

    async def identify(self) -> str:
        try:
            model = (await self.transport.get(MODEL_OID)).decode("ascii").strip("\x00 \r\n")
        except (PrinterError, UnicodeDecodeError):
            # Some firmware exposes identification only via the IEEE 1284 device ID.
            try:
                device_id = (await self.transport.get(DEVICE_ID_OID)).decode("ascii")
                fields = dict(
                    field.split(":", 1) for field in device_id.split(";") if ":" in field
                )
                manufacturer = fields.get("MFG", fields.get("MANUFACTURER", "")).strip()
                if manufacturer.upper() != "EPSON":
                    raise PrinterError("This device does not identify itself as an Epson printer.")
                model = fields.get("MDL", fields.get("MODEL", "")).strip()
            except UnicodeDecodeError as exc:
                raise PrinterError("The printer's model response is unreadable.") from exc
        if not is_xp530(model):
            raise PrinterError(f"This app supports only the Epson XP-530. Device reported: {model!r}.")
        return model

    async def read_byte(self, address: int) -> int:
        response = await self.transport.get(read_oid(address))
        match = re.search(rb"(?:^|[\r\n;])EE:([0-9A-Fa-f]{4})([0-9A-Fa-f]{2});", response)
        if not response.endswith(b"\x0c") or match is None:
            raise PrinterError(
                f"EEPROM read refused or malformed at 0x{address:04X}. This firmware may block "
                "maintenance over Wi-Fi. No access-key scan or firmware change will be attempted."
            )
        if int(match[1], 16) != address:
            raise PrinterError(f"EEPROM address mismatch while reading 0x{address:04X}.")
        return int(match[2], 16)

    async def inspect(self, host: str) -> Snapshot:
        host = validate_host(host)
        model = await self.identify()
        serial_bytes = bytes([await self.read_byte(a) for a in SERIAL_ADDRESSES])
        try:
            serial = serial_bytes.decode("ascii")
        except UnicodeDecodeError as exc:
            raise PrinterError("The printer's serial number could not be verified.") from exc
        if not re.fullmatch(r"[A-Za-z0-9]{10}", serial):
            raise PrinterError("The printer did not return a valid 10-character serial number.")
        memory = tuple([(a, await self.read_byte(a)) for a in RESET_VALUES])
        return Snapshot(host, model, serial, memory)

    def save_backup(self, snapshot: Snapshot, directory: Path) -> Path:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc)
            path = directory / f"{stamp:%Y%m%dT%H%M%S}_{snapshot.serial}_{uuid.uuid4().hex[:8]}.json"
            payload = {
                "schema": 1, "profile": "Epson XP-530", "timestamp_utc": stamp.isoformat(),
                "host": snapshot.host, "model": snapshot.model, "serial": snapshot.serial,
                "eeprom_before": {f"0x{a:04X}": v for a, v in snapshot.memory},
                "reset_sequence": [[f"0x{a:04X}", v] for a, v in RESET_SEQUENCE],
            }
            # Exclusive creation and fsync: do not begin writes without a saved backup.
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            return path
        except OSError as exc:
            raise PrinterError(f"Could not save the backup. No reset was started: {exc}") from exc

    async def reset(self, expected: Snapshot, directory: Path, *, pads_serviced: bool) -> ResetResult:
        if not pads_serviced:
            raise PrinterError("Service or replace the waste-ink pads before resetting their counter.")
        current = await self.inspect(expected.host)
        if (current.serial, current.memory) != (expected.serial, expected.memory):
            raise PrinterError("The printer or its counter values changed. Read the counters again before resetting.")
        if current.already_reset:
            return ResetResult(current, None, False)
        backup = self.save_backup(current, directory)
        attempted = 0
        try:
            for address, value in RESET_SEQUENCE:
                attempted += 1
                response = await self.transport.get(write_oid(address, value))
                # OK is necessary, but not sufficient: verify the actual EEPROM byte too.
                if not re.search(rb"\|\|:(?:42:)?OK;\x0c$", response):
                    raise PrinterError(f"Printer refused or did not confirm the write at 0x{address:04X}.")
                if await self.read_byte(address) != value:
                    raise PrinterError(f"Read-back verification failed at 0x{address:04X}; firmware may ignore Wi-Fi writes.")
            after = await self.inspect(expected.host)
            if after.serial != expected.serial or not after.already_reset:
                raise PrinterError("Final identity or full reset verification failed.")
        except Exception as exc:
            raise PrinterError(
                f"Reset incomplete after {attempted} write attempt(s). Some values may have changed. "
                f"{exc}\nBackup: {backup}\nKeep the printer powered on; read its counters again. "
                "Do not repeat resets blindly or restore EEPROM automatically."
            ) from exc
        return ResetResult(after, backup, True)
