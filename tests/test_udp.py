"""Exercise the actual PySNMP client against a local UDP printer simulator."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from pyasn1.codec.ber import decoder, encoder
from pysnmp.proto import api

from epson_reset.profile import MODEL_OID, RESET_SEQUENCE, PrinterError
from epson_reset.service import PrinterService
from epson_reset.simulator import DemoTransport
from epson_reset.transport import SnmpTransport

V1 = api.PROTOCOL_MODULES[api.SNMP_VERSION_1]


class Agent(asyncio.DatagramProtocol):
    def __init__(self):
        self.printer = DemoTransport("127.0.0.1")
        self.requests = []
        self.drop = False
        self.bad_object = False
        self.error = False
        self.tasks = set()

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, address):
        task = asyncio.create_task(self.respond(data, address))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def respond(self, data, address):
        request, remainder = decoder.decode(data, asn1Spec=V1.Message())
        assert not remainder
        assert str(V1.apiMessage.get_community(request)) == "public"
        pdu = V1.apiMessage.get_pdu(request)
        oid = str(V1.apiPDU.get_varbinds(pdu)[0][0])
        self.requests.append(oid)
        if self.drop:
            return
        response = V1.apiMessage.get_response(request)
        response_pdu = V1.apiMessage.get_pdu(response)
        value = await self.printer.get(oid)
        V1.apiPDU.set_varbinds(response_pdu, [
            (MODEL_OID if self.bad_object else oid, V1.OctetString(value)),
        ])
        if self.error:
            V1.apiPDU.set_error_status(response_pdu, 2)
            V1.apiPDU.set_error_index(response_pdu, 1)
        self.transport.sendto(encoder.encode(response), address)


class WireTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.agent = Agent()
        self.server, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: self.agent, local_addr=("127.0.0.1", 0),
        )
        self.port = self.server.get_extra_info("sockname")[1]

    async def asyncTearDown(self):
        self.server.close()
        if self.agent.tasks:
            await asyncio.gather(*self.agent.tasks)

    async def test_real_snmp_read_reset_and_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            async with SnmpTransport("127.0.0.1", port=self.port, timeout=0.5) as transport:
                service = PrinterService(transport)
                snapshot = await service.inspect("127.0.0.1")
                self.assertEqual(snapshot.serial, "DEMO000053")
                self.assertEqual(self.agent.printer.writes, [])
                result = await service.reset(snapshot, Path(directory), pads_serviced=True)
                self.assertTrue(result.snapshot.already_reset)
                self.assertEqual(self.agent.printer.writes, list(RESET_SEQUENCE))
                again = await service.reset(result.snapshot, Path(directory), pads_serviced=True)
                self.assertFalse(again.changed)

    async def test_network_timeout_does_not_retry_vendor_commands(self):
        self.agent.drop = True
        async with SnmpTransport("127.0.0.1", port=self.port, timeout=0.1) as transport:
            with self.assertRaisesRegex(PrinterError, "No usable SNMP response"):
                await transport.get(MODEL_OID)
        self.assertEqual(self.agent.requests, [MODEL_OID])

    async def test_snmp_error_propagates(self):
        self.agent.error = True
        async with SnmpTransport("127.0.0.1", port=self.port, timeout=0.5) as transport:
            with self.assertRaisesRegex(PrinterError, "rejected the SNMP request"):
                await transport.get(MODEL_OID)
