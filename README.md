# XP-530 waste ink reset

A small desktop app for **Windows + Wi-Fi**, specifically for the **Epson XP-530**. Enter the printer's IP address, read the counters, and reset them after servicing the waste-ink pads.

**Hardware validation is still required.** The reset profile comes from a community XP-530 device database. The software is tested with a simulated printer and real local SNMP packets; it has not been tested against a physical XP-530 here. Some firmware refuses EEPROM maintenance over Wi-Fi. The app reports that failure rather than claiming a successful reset.

Resetting a counter does **not** empty the pads. Service or replace them first to prevent ink overflow. This app does not reset ink cartridges, change firmware, or bypass cartridge authentication.

## Run on Windows

1. Install [Python 3.11 or newer](https://www.python.org/downloads/windows/), including **Tcl/Tk** and the **Python launcher**. A normal python.org installation includes both.
2. Download/extract this project to a writable folder, then double-click **Start.bat**. On first launch it creates a local Python environment and downloads two pinned dependencies from PyPI. It checks their hashes and keeps TLS verification enabled.
3. Power on the printer and connect the computer to the same local network. Find the printer's IPv4 address on its network status screen/sheet. Avoid a guest Wi-Fi network that isolates devices.
4. Enter the address and click **Read counters**. The app verifies that the device reports XP-530, reads its serial number, and displays the base counters. This step sends no EEPROM writes.
5. After servicing the pads and stopping print/cleaning jobs, tick both confirmations and click **Reset counters**. Confirm the displayed IP and serial number.
6. Wait for the result. After a verified reset, power the printer off and on, read the counters again, and check its display. Byte verification alone does not establish that the service error has cleared or that values persisted across a reboot.

SNMPv1 (`public`, UDP port 161) must be enabled and reachable on the local network. The app sends Epson maintenance commands through vendor OIDs. No Epson account or paid reset key is used. Keep SNMP on a trusted local network.

### Try it without a printer

Open a terminal in the project folder and run:

```bat
Start.bat --demo
```

The demo uses in-memory counters and makes **no network connections**. Its title and reset button identify it as a simulation. Demo resets also create backup files, marked by serial `DEMO000053`.

### Backups and failures

Before the first write, the app saves the original bytes, model, serial, IP, and ordered reset plan in:

```text
%LOCALAPPDATA%\EpsonXP530Reset\backups\
```

Use **Open backups** to find them, or `--backup-dir PATH` to choose a different location. These files contain the printer's serial number and local IP; handle them accordingly. Backup files are diagnostic records, not full EEPROM images. There is deliberately no automatic restore operation.

Every write must receive an acknowledgement and pass an immediate read-back check. The app then rechecks the entire profile and serial number. A reset spans several writes and is **not atomic**. If the connection fails or a write is refused, some bytes may already have changed. The error includes the backup path. Keep power on, read again, and seek service help rather than repeatedly resetting or restoring bytes blindly. If EEPROM reads or writes are blocked by firmware, this app cannot perform the reset over Wi-Fi; use a suitable USB maintenance tool or an Epson service provider. It will not scan access keys or alter firmware.

The XP-530 stores extra counter flags at EEPROM `0x06`. Their complete interpretation is not implemented, so the app displays the two **base counts** and flags separately, with no claimed full percentage or physical ink measurement. The reset uses the model-specific full reset sequence, including the flags and auxiliary bytes, rather than merely zeroing the displayed counts. See [THIRD_PARTY.md](THIRD_PARTY.md) for the exact source and profile.

## Development

Use the existing checkout; cloud tasks are already isolated and need no extra Git worktree.

```sh
cd /workspace/epson
python -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m epson_reset --demo --backup-dir /tmp/epson-demo-backups
```

On Windows substitute `.venv\Scripts\python.exe` for `.venv/bin/python`. Tk needs a graphical desktop. GUI tests skip explicitly if no display is available; protocol, service, failure-path, and local UDP integration tests still run headlessly. No physical printer is contacted by the tests.

The app runs on the user's computer, not as a cloud web service: browsers and cloud machines cannot directly reach a home printer's local SNMP interface. There is no server or database to start. GUI dependencies are Python's standard Tkinter plus the two packages in `requirements.txt`.

To build a Windows executable locally (requires a Windows machine):

```bat
.venv\Scripts\python.exe -m pip install pyinstaller==6.20.0
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --collect-all pysnmp --name XP530Reset run_app.py
```

The resulting `dist\XP530Reset.exe` is unsigned. Building a Windows executable was not verified in the Linux cloud environment; source launch is the primary delivery.
