# Protocol and device-profile provenance

The application is an independent implementation of Epson's community-documented EEPROM-over-SNMP mechanism. It does not bundle another maintenance application's source or device database.

- SNMP Epson control OID and command framing were checked against [Ircama/epson_print_conf](https://github.com/Ircama/epson_print_conf/tree/6873e9e2ebf73530a5a2e32f7485a0292e4d2d83) (`epson_print_conf.py`, EUPL-1.2). That project's documentation describes SNMP restrictions on some firmware and the need to verify writes by reading them back.
- Model-specific numeric parameters come from the `XP530` section in [CiRIP/ez-reset's devices.xml](https://github.com/CiRIP/ez-reset/blob/82fa560dc6b3f7f9b018441821d2bf9d7909ebcd/src/ez_reset/devices.xml). Its XP-530 device maps to `EPSON,XP530,EP13,ESXX`. No firmware, executable, XML database, or access-key discovery logic is included here.
- Runtime dependencies: [PySNMP](https://pypi.org/project/pysnmp/) (BSD-2-Clause) and [pyasn1](https://pypi.org/project/pyasn1/) (BSD-2-Clause). Their distributions carry their licenses.

The XP530 profile specifies factory/read bytes `28 09`, literal write-key bytes `4A 73 6A 74 68 62 73 6E`, and serial addresses `0xD8` through `0xE1`. The first base counter is little-endian at `0x10, 0x11`, reference maximum 4806; the second is at `0x12, 0x13`, reference maximum 2082. Extra filtered fields at `0x06` are shown as flags rather than being misinterpreted as an unfiltered third counter byte.

The ordered reset writes are:

```text
0010=00  0011=00  0006=00  0034=5E  0014=00  0015=00
0012=00  0013=00  0006=00  0035=5E  01ED=00
```

These are community-sourced parameters, not an Epson guarantee of compatibility with every XP-530 firmware revision. Local simulation and byte-level tests do not substitute for physical hardware validation.
