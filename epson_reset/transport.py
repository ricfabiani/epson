"""SNMPv1 Epson control channel. Some firmware blocks this over Wi-Fi."""

from pysnmp.hlapi.v1arch.asyncio import (
    CommunityData, ObjectIdentity, ObjectType, SnmpDispatcher, UdpTransportTarget, get_cmd,
)
from pyasn1.type.univ import OctetString

from .profile import PrinterError, validate_host


class SnmpTransport:
    def __init__(self, host: str, *, port: int = 161, timeout: float = 2.0):
        self.host = validate_host(host)
        self.port = port
        self.timeout = timeout
        self.dispatcher = None

    async def __aenter__(self):
        self.dispatcher = SnmpDispatcher()
        try:
            # No automatic retries: vendor writes are carried by SNMP GETs.
            self.target = await UdpTransportTarget.create(
                (self.host, self.port), timeout=self.timeout, retries=0,
            )
        except Exception:
            self.dispatcher.close()
            raise
        return self

    async def __aexit__(self, *_):
        self.dispatcher.close()

    async def get(self, oid: str) -> bytes:
        try:
            indication, status, _, bindings = await get_cmd(
                self.dispatcher, CommunityData("public", mpModel=0), self.target,
                ObjectType(ObjectIdentity(oid)),
            )
        except Exception as exc:
            raise PrinterError(f"Could not communicate with {self.host}: {exc}") from exc
        if indication:
            raise PrinterError(
                f"No usable SNMP response from {self.host}. Check the IP, power, same Wi-Fi "
                "network, and SNMP/UDP 161 access. Guest Wi-Fi may isolate devices."
            )
        if status:
            raise PrinterError(f"Printer rejected the SNMP request: {status.prettyPrint()}.")
        if len(bindings) != 1 or str(bindings[0][0]) != oid:
            raise PrinterError("The printer returned an unexpected SNMP object.")
        value = bindings[0][1]
        if not isinstance(value, OctetString):
            raise PrinterError("The printer did not return the expected byte response.")
        return value.asOctets()
