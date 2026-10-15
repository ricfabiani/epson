import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from epson_reset.profile import (
    CONTROL_OID, MODEL_OID, RESET_SEQUENCE, RESET_VALUES, SERIAL_ADDRESSES,
    PrinterError, is_xp530, read_oid, validate_host, write_oid,
)
from epson_reset.service import PrinterService
from epson_reset.simulator import DemoTransport


class FaultyPrinter(DemoTransport):
    model = b"EPSON XP-530 Series"
    bad_read = None
    wrong_address = False
    ignore_writes = False
    refuse_writes = False
    lose_write_reply = False

    async def get(self, oid):
        if oid == MODEL_OID:
            return self.model
        if oid.startswith(CONTROL_OID + "."):
            packet = bytes(map(int, oid[len(CONTROL_OID) + 1:].split(".")))
            address = int.from_bytes(packet[9:11], "little")
            if packet[6] == 0x41:
                if address == self.bad_read:
                    return b"||:41:NA;\x0c"
                if self.wrong_address:
                    return b"@BDC PS\r\nEE:FFFF00;\x0c"
            if packet[6] == 0x42:
                if self.refuse_writes:
                    return b"||:42:NA;\x0c"
                if self.ignore_writes:
                    return b"||:42:OK;\x0c"
                if self.lose_write_reply:
                    await super().get(oid)
                    raise PrinterError("Lost reply")
        return await super().get(oid)


class ProfileTests(unittest.TestCase):
    def test_exact_xp530_identity_only(self):
        for name in ("XP-530", "EPSON XP-530 Series", "xp-530 series"):
            self.assertTrue(is_xp530(name), name)
        for name in ("XP-5300", "XP-535", "XP-530 Series other", "Some XP-530", "XP-520"):
            self.assertFalse(is_xp530(name), name)

    def test_ip_validation(self):
        self.assertEqual(validate_host(" 192.168.1.53 "), "192.168.1.53")
        for address in ("", "printer.local", "::1", "0.0.0.0", "224.0.0.1", "255.255.255.255"):
            with self.assertRaises(PrinterError):
                validate_host(address)

    def test_wire_commands_match_xp530_profile(self):
        self.assertEqual(read_oid(0x1ED), CONTROL_OID + ".124.124.7.0.40.9.65.190.160.237.1")
        self.assertEqual(write_oid(0x34, 0x5E), CONTROL_OID + ".124.124.16.0.40.9.66.189.33.52.0.94.74.115.106.116.104.98.115.110")
        self.assertEqual(RESET_SEQUENCE, (
            (16, 0), (17, 0), (6, 0), (52, 94), (20, 0), (21, 0),
            (18, 0), (19, 0), (6, 0), (53, 94), (493, 0),
        ))
        with self.assertRaises(PrinterError):
            write_oid(0xD8, 0)


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.printer = FaultyPrinter()
        self.service = PrinterService(self.printer)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "backups"

    async def inspect(self):
        return await self.service.inspect(self.printer.host)

    async def test_inspect_reads_correct_counters_without_writes(self):
        snapshot = await self.inspect()
        self.assertEqual(snapshot.serial, "DEMO000053")
        self.assertEqual([c[1] for c in snapshot.counters], [4806, 2086])
        self.assertFalse(snapshot.already_reset)
        self.assertEqual(self.printer.writes, [])
        self.assertFalse(self.directory.exists())

    async def test_unknown_model_stops_before_eeprom(self):
        self.printer.model = b"EPSON XP-5300 Series"
        self.printer.bad_read = SERIAL_ADDRESSES[0]
        with self.assertRaisesRegex(PrinterError, "only the Epson XP-530"):
            await self.inspect()
        self.assertEqual(self.printer.writes, [])

    async def test_device_id_fallback(self):
        original = self.printer.get

        async def get(oid):
            if oid == MODEL_OID:
                raise PrinterError("noSuchName")
            return await original(oid)

        self.printer.get = get
        self.assertEqual((await self.inspect()).model, "XP-530 Series")

    async def test_locked_read_does_not_become_zero(self):
        self.printer.bad_read = 0x10
        with self.assertRaisesRegex(PrinterError, "EEPROM read refused"):
            await self.inspect()
        self.assertEqual(self.printer.writes, [])

    async def test_wrong_eeprom_address_is_rejected(self):
        self.printer.wrong_address = True
        with self.assertRaisesRegex(PrinterError, "address mismatch"):
            await self.inspect()

    async def test_invalid_serial_is_rejected(self):
        self.printer.memory[SERIAL_ADDRESSES[0]] = 0
        with self.assertRaisesRegex(PrinterError, "serial number"):
            await self.inspect()

    async def test_servicing_is_required_before_any_network_or_write(self):
        snapshot = await self.inspect()
        with patch.object(self.service, "inspect", side_effect=AssertionError("Should not query")):
            with self.assertRaisesRegex(PrinterError, "Service or replace"):
                await self.service.reset(snapshot, self.directory, pads_serviced=False)
        self.assertEqual(self.printer.writes, [])

    async def test_changed_counters_abort_without_writes(self):
        snapshot = await self.inspect()
        self.printer.memory[0x10] += 1
        with self.assertRaisesRegex(PrinterError, "counter values changed"):
            await self.service.reset(snapshot, self.directory, pads_serviced=True)
        self.assertEqual(self.printer.writes, [])
        self.assertFalse(self.directory.exists())

    async def test_different_device_at_same_ip_aborts(self):
        snapshot = await self.inspect()
        self.printer.memory[SERIAL_ADDRESSES[-1]] = ord("4")
        with self.assertRaisesRegex(PrinterError, "printer or its counter values changed"):
            await self.service.reset(snapshot, self.directory, pads_serviced=True)
        self.assertEqual(self.printer.writes, [])

    async def test_backup_failure_aborts_without_writes(self):
        snapshot = await self.inspect()
        self.directory.write_text("a file is not a backup directory")
        with self.assertRaisesRegex(PrinterError, "No reset was started"):
            await self.service.reset(snapshot, self.directory, pads_serviced=True)
        self.assertEqual(self.printer.writes, [])

    async def test_reset_saves_original_bytes_before_first_write_and_verifies(self):
        snapshot = await self.inspect()
        original = self.printer.get

        async def get(oid):
            # The backup is already on disk whenever the first write is sent.
            if oid.startswith(CONTROL_OID + ".") and oid.split(".")[len(CONTROL_OID.split(".")) + 6] == "66":
                files = list(self.directory.glob("*.json"))
                self.assertEqual(len(files), 1)
                self.assertEqual(json.loads(files[0].read_text())["serial"], snapshot.serial)
            return await original(oid)

        self.printer.get = get
        result = await self.service.reset(snapshot, self.directory, pads_serviced=True)
        self.assertTrue(result.changed)
        self.assertTrue(result.snapshot.already_reset)
        self.assertEqual(self.printer.writes, list(RESET_SEQUENCE))
        backup = json.loads(result.backup.read_text())
        self.assertEqual(backup["eeprom_before"]["0x0010"], 0xC6)
        self.assertEqual(len(backup["eeprom_before"]), len(RESET_VALUES))
        self.assertEqual(backup["reset_sequence"].count(["0x0006", 0]), 2)
        before = len(self.printer.writes)
        again = await self.service.reset(result.snapshot, self.directory, pads_serviced=True)
        self.assertFalse(again.changed)
        self.assertIsNone(again.backup)
        self.assertEqual(len(self.printer.writes), before)

    async def test_ok_but_ignored_write_is_not_success(self):
        snapshot = await self.inspect()
        self.printer.ignore_writes = True
        with self.assertRaisesRegex(PrinterError, "Read-back verification failed"):
            await self.service.reset(snapshot, self.directory, pads_serviced=True)
        self.assertEqual(len(list(self.directory.glob("*.json"))), 1)

    async def test_refused_write_stops_without_blind_retry(self):
        snapshot = await self.inspect()
        self.printer.refuse_writes = True
        with self.assertRaisesRegex(PrinterError, "1 write attempt.*Some values may have changed"):
            await self.service.reset(snapshot, self.directory, pads_serviced=True)
        self.assertEqual(self.printer.writes, [])

    async def test_lost_reply_warns_of_partial_reset_without_rollback(self):
        snapshot = await self.inspect()
        self.printer.lose_write_reply = True
        with self.assertRaisesRegex(PrinterError, "Reset incomplete") as caught:
            await self.service.reset(snapshot, self.directory, pads_serviced=True)
        self.assertEqual(self.printer.writes, [RESET_SEQUENCE[0]])
        self.assertIn("Backup:", str(caught.exception))
        self.assertEqual(self.printer.memory[0x10], 0)
        self.assertEqual(self.printer.memory[0x11], 0x12)

    async def test_extended_flags_preserved_on_read_and_reset_with_full_profile(self):
        self.printer.memory[0x06] = 0xA3
        snapshot = await self.inspect()
        self.assertEqual(snapshot.flags, 0xA3)
        self.assertEqual(snapshot.counters[0][1], 4806)
        result = await self.service.reset(snapshot, self.directory, pads_serviced=True)
        self.assertEqual(result.snapshot.flags, 0)
