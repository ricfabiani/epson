"""An in-memory demo printer. It never opens a network connection."""

import asyncio

from .profile import (
    CONTROL_OID, DEVICE_ID_OID, MODEL_OID, RESET_VALUES, SERIAL_ADDRESSES, WRITE_KEY,
)


class DemoTransport:
    def __init__(self, host="192.168.1.53"):
        self.host = host
        self.memory = dict.fromkeys(RESET_VALUES, 0)
        self.memory.update({0x10: 0xC6, 0x11: 0x12, 0x12: 0x26, 0x13: 0x08})
        self.memory.update(dict(zip(SERIAL_ADDRESSES, b"DEMO000053")))
        self.writes = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def get(self, oid):
        await asyncio.sleep(0.002)
        if oid == MODEL_OID:
            return b"EPSON XP-530 Series"
        if oid == DEVICE_ID_OID:
            return b"MFG:EPSON;MDL:XP-530 Series;"
        packet = bytes(map(int, oid.removeprefix(CONTROL_OID + ".").split(".")))
        address = int.from_bytes(packet[9:11], "little")
        if packet[6] == 0x41:
            return f"@BDC PS\r\nEE:{address:04X}{self.memory[address]:02X};\x0c".encode()
        if packet[6] == 0x42 and packet[-8:] == WRITE_KEY:
            self.memory[address] = packet[11]
            self.writes.append((address, packet[11]))
            return b"||:42:OK;\x0c"
        raise ValueError("Unexpected demo command")
