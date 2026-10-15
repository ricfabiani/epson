"""Small local Tk desktop interface; printer work runs off the UI thread."""

import asyncio
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .profile import PrinterError, validate_host
from .service import PrinterService, backup_directory
from .simulator import DemoTransport
from .transport import SnmpTransport

NAVY = "#152B3C"
GREEN = "#147568"
MUTED = "#526677"
BG = "#F0F4F6"
FONT = "Segoe UI" if sys.platform == "win32" else "Helvetica"


class App(tk.Tk):
    def __init__(self, *, demo=False, backups: Path | None = None):
        super().__init__()
        self.title("XP-530 · Waste ink reset" + (" · DEMO" if demo else ""))
        self.geometry("850x800")
        self.minsize(800, 780)
        self.configure(bg=BG)
        self.demo = demo
        self.backups = backups if backups is not None else backup_directory()
        self.simulator = DemoTransport() if demo else None
        self.snapshot = None
        self.busy = False
        self.results = queue.Queue()
        self.address = tk.StringVar(value="192.168.1.53" if demo else "")
        self.serviced = tk.BooleanVar()
        self.idle = tk.BooleanVar()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.style_widgets()
        self.build()
        self.address.trace_add("write", self.address_changed)
        self.poll_job = self.after(80, self.poll)

    def style_widgets(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TButton", font=(FONT, 10), padding=(14, 10))
        style.configure("Primary.TButton", background=GREEN, foreground="white", borderwidth=0)
        style.map("Primary.TButton", background=[("disabled", "#C7D4D4"), ("active", "#0D5F54")])
        style.configure("TCheckbutton", background="white", font=(FONT, 10), padding=(0, 4))
        style.configure("TEntry", padding=9, font=(FONT, 11))

    def label(self, parent, text, *, size=10, color=NAVY, bold=False, bg="white", **kwargs):
        return tk.Label(parent, text=text, font=(FONT, size, "bold" if bold else "normal"),
                        fg=color, bg=bg, anchor="w", **kwargs)

    def card(self, parent):
        return tk.Frame(parent, bg="white", padx=20, pady=14, highlightthickness=1,
                        highlightbackground="#DCE5EA")

    def build(self):
        header = tk.Frame(self, bg=NAVY, padx=28, pady=22)
        header.pack(fill="x")
        self.label(header, "EPSON XP-530", size=10, color="#8ED7CA", bold=True, bg=NAVY).pack(anchor="w")
        self.label(header, "Waste ink counter reset", size=24, color="white", bold=True, bg=NAVY).pack(anchor="w", pady=(3, 0))
        self.label(header, "Windows  /  Wi-Fi" + ("     •     DEMO — no printer connection" if self.demo else ""),
                   color="#BDD0DF", bg=NAVY).pack(anchor="w", pady=(5, 0))

        body = tk.Frame(self, bg=BG, padx=24, pady=18)
        body.pack(fill="both", expand=True)
        connection = self.card(body)
        connection.pack(fill="x")
        self.label(connection, "01   Connect to your printer", size=12, bold=True).pack(anchor="w")
        row = tk.Frame(connection, bg="white")
        row.pack(fill="x", pady=(12, 6))
        self.host_entry = ttk.Entry(row, textvariable=self.address, width=27)
        self.host_entry.pack(side="left", fill="x", expand=True, padx=(0, 12))
        if self.demo:
            self.host_entry.configure(state="disabled")
        self.read_button = ttk.Button(row, text="Read counters", command=self.read)
        self.read_button.pack(side="right")
        self.label(connection, "Find the IPv4 address on the printer's Wi-Fi / network status screen.", color=MUTED).pack(anchor="w")
        self.identity = self.label(connection, "No printer verified. Reading counters makes no changes.", color=MUTED)
        self.identity.pack(anchor="w", pady=(10, 0))

        counters = tk.Frame(body, bg=BG)
        counters.pack(fill="x", pady=(12, 0))
        counters.columnconfigure((0, 1), weight=1, uniform="counter")
        self.counter_values = []
        for column, (name, reference) in enumerate((("Main waste pad", 4806), ("Borderless waste pad", 2082))):
            panel = self.card(counters)
            panel.grid(row=0, column=column, sticky="ew", padx=(0, 6) if column == 0 else (6, 0))
            self.label(panel, name, bold=True).pack(anchor="w")
            value = self.label(panel, "—", size=26, bold=True)
            value.pack(anchor="w", pady=(6, 0))
            self.counter_values.append(value)
            self.label(panel, f"base units  /  {reference:,} reference", color=MUTED).pack(anchor="w")
        self.flags = self.label(body, "Base counters only. No physical ink level is measured.", color=MUTED, bg=BG)
        self.flags.pack(anchor="w", pady=(7, 12))

        maintenance = self.card(body)
        maintenance.pack(fill="x")
        self.label(maintenance, "02   Prepare for a reset", size=12, bold=True).pack(anchor="w")
        self.label(maintenance, "Resetting the counter does not empty the waste-ink pads. Service them first",
                   color="#87501B").pack(anchor="w", pady=(9, 0))
        self.label(maintenance, "to prevent ink overflow. Keep the printer powered on throughout the reset.", color="#87501B").pack(anchor="w")
        self.pads_check = ttk.Checkbutton(maintenance, text="I have serviced or replaced the waste-ink pads.",
                                         variable=self.serviced, command=self.update_controls)
        self.pads_check.pack(anchor="w", pady=(8, 0))
        self.idle_check = ttk.Checkbutton(maintenance, text="The printer is idle, with no print or cleaning job running.",
                                         variable=self.idle, command=self.update_controls)
        self.idle_check.pack(anchor="w")
        actions = tk.Frame(maintenance, bg="white")
        actions.pack(fill="x", pady=(10, 0))
        self.reset_button = ttk.Button(actions, text="Reset counters" if not self.demo else "Simulate reset",
                                       style="Primary.TButton", command=self.reset, state="disabled")
        self.reset_button.pack(side="left")
        ttk.Button(actions, text="Open backups", command=self.open_backups).pack(side="right")

        self.status = self.label(body, "Ready to read" if not self.demo else "Demo mode — all operations are simulated",
                                 bold=True, bg=BG)
        self.status.pack(anchor="w", pady=(14, 5))
        log_frame = tk.Frame(body, bg=BG)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, height=4, wrap="word", bg=BG, fg=MUTED, bd=0,
                           font=(FONT, 9), state="disabled", highlightthickness=0)
        self.log.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        scroll.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scroll.set)
        self.set_status("Ready to read" if not self.demo else "Demo mode — no network access",
                        "Enter the XP-530's IP address and read its counters. "
                        "This community tool has not been verified on your physical printer.")

    def set_status(self, title, detail, *, error=False):
        self.status.configure(text=title, fg="#AA3E32" if error else GREEN)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", detail)
        self.log.configure(state="disabled")

    def clear_snapshot(self):
        self.snapshot = None
        for label in self.counter_values:
            label.configure(text="—")
        self.identity.configure(text="No printer verified. Read counters to continue.")
        self.flags.configure(text="Base counters only. No physical ink level is measured.")

    def address_changed(self, *_):
        self.clear_snapshot()
        self.serviced.set(False)
        self.idle.set(False)
        self.update_controls()

    def update_controls(self):
        self.read_button.configure(state="disabled" if self.busy else "normal")
        self.host_entry.configure(state="disabled" if self.busy or self.demo else "normal")
        for check in (self.pads_check, self.idle_check):
            check.configure(state="disabled" if self.busy else "normal")
        allowed = bool(self.snapshot and self.serviced.get() and self.idle.get() and not self.busy)
        self.reset_button.configure(state="normal" if allowed else "disabled")

    def show_snapshot(self, snapshot):
        self.snapshot = snapshot
        self.identity.configure(text=f"Verified XP-530   ·   Serial {snapshot.serial}   ·   {snapshot.host}")
        for label, (_, value, _) in zip(self.counter_values, snapshot.counters):
            label.configure(text=f"{value:,}")
        self.flags.configure(text=f"Extended flags: 0x{snapshot.flags:02X}. Base counts exclude these flags; no full percentage is shown.")

    def run_task(self, operation, success):
        self.busy = True
        self.update_controls()

        def worker():
            try:
                result = asyncio.run(operation())
                self.results.put((success, result, None))
            except Exception as exc:
                self.results.put((success, None, exc))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            success, result, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            if error:
                self.clear_snapshot()
                self.serviced.set(False)
                self.idle.set(False)
                self.set_status("Operation could not be verified", str(error), error=True)
                messagebox.showerror("XP-530 maintenance", str(error), parent=self)
            else:
                success(result)
            self.update_controls()
        self.poll_job = self.after(80, self.poll)

    def transport(self, host):
        return self.simulator if self.demo else SnmpTransport(host)

    def read(self):
        if self.busy:
            return
        try:
            host = validate_host(self.address.get())
        except PrinterError as exc:
            messagebox.showerror("Printer address", str(exc), parent=self)
            return
        self.clear_snapshot()
        self.serviced.set(False)
        self.idle.set(False)
        self.set_status("Reading printer…", "Verifying model, serial number, and waste-counter bytes. No writes are sent.")

        async def operation():
            async with self.transport(host) as transport:
                return await PrinterService(transport).inspect(host)

        def success(snapshot):
            self.show_snapshot(snapshot)
            self.set_status("Counters read" + (" · simulated" if self.demo else ""),
                            "Service the pads before resetting. The full counter percentage is not decoded; "
                            "the app shows base EEPROM counts and extended flags separately.")

        self.run_task(operation, success)

    def reset(self):
        if self.busy or not self.snapshot or not self.serviced.get() or not self.idle.get():
            return
        expected = self.snapshot
        prompt = (f"Reset the waste-ink counters on XP-530 {expected.serial}\nat {expected.host}?\n\n"
                  "The app will save a backup, apply the XP-530 reset profile, and verify every write. "
                  "Keep the printer powered on.\n\nThis does not replace or empty the pads.")
        if self.demo:
            prompt = "DEMO — no printer will be contacted.\n\n" + prompt
        if not messagebox.askyesno("Confirm counter reset", prompt, icon="warning", default="no", parent=self):
            return
        self.set_status("Resetting and verifying…", "Rechecking printer identity, saving a backup, then verifying EEPROM writes.")

        async def operation():
            async with self.transport(expected.host) as transport:
                return await PrinterService(transport).reset(expected, self.backups, pads_serviced=True)

        def success(result):
            self.show_snapshot(result.snapshot)
            self.serviced.set(False)
            self.idle.set(False)
            if not result.changed:
                self.set_status("Already reset", "All reset-profile bytes already have their target values. No writes were sent.")
            else:
                prefix = "Simulated reset verified" if self.demo else "Reset bytes verified"
                self.set_status(prefix, f"Backup saved: {result.backup}\n"
                                "Power the printer off and on, then read the counters again to check persistence. "
                                "A successful EEPROM check does not confirm that the printer's service error has cleared.")

        self.run_task(operation, success)

    def open_backups(self):
        try:
            self.backups.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(self.backups))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self.backups)])
            else:
                subprocess.Popen(["xdg-open", str(self.backups)])
        except OSError as exc:
            messagebox.showerror("Backups", f"Could not open {self.backups}: {exc}", parent=self)

    def close(self):
        if self.busy:
            messagebox.showinfo("Operation running", "Wait for the printer operation to finish before closing.", parent=self)
            return
        self.destroy()

    def destroy(self):
        if hasattr(self, "poll_job"):
            self.after_cancel(self.poll_job)
        super().destroy()
