import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(sys.platform == "win32" or os.environ.get("DISPLAY"), "GUI requires a desktop/display")
class GuiTests(unittest.TestCase):
    def setUp(self):
        from epson_reset.gui import App

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = App(demo=True, backups=Path(self.temp.name))
        self.app.withdraw()
        self.addCleanup(self.app.destroy)

    def finish_task(self):
        deadline = time.monotonic() + 10
        while self.app.busy and time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.01)
        self.assertFalse(self.app.busy, "UI worker did not finish")
        self.app.update()

    def test_read_confirm_reset_and_invalidate(self):
        self.assertTrue(self.app.reset_button.instate(["disabled"]))
        self.app.read()
        self.finish_task()
        self.assertIsNotNone(self.app.snapshot)
        self.assertEqual(self.app.simulator.writes, [])
        self.assertTrue(self.app.reset_button.instate(["disabled"]))
        self.app.serviced.set(True)
        self.app.idle.set(True)
        self.app.update_controls()
        self.assertTrue(self.app.reset_button.instate(["!disabled"]))
        with patch("epson_reset.gui.messagebox.askyesno", return_value=False):
            self.app.reset()
        self.assertEqual(self.app.simulator.writes, [])
        with patch("epson_reset.gui.messagebox.askyesno", return_value=True):
            self.app.reset()
        self.finish_task()
        self.assertTrue(self.app.snapshot.already_reset)
        self.assertEqual(len(list(Path(self.temp.name).glob("*.json"))), 1)
        self.assertIn("Simulated reset verified", self.app.status.cget("text"))
        self.assertTrue(self.app.reset_button.instate(["disabled"]))
        self.app.address.set("192.168.1.54")
        self.assertIsNone(self.app.snapshot)

    def test_failure_clears_readiness_and_preserves_error(self):
        async def refused(_):
            raise ValueError("Simulated transport failure")

        self.app.simulator.get = refused
        with patch("epson_reset.gui.messagebox.showerror") as error:
            self.app.read()
            self.finish_task()
        error.assert_called_once()
        self.assertIsNone(self.app.snapshot)
        self.assertTrue(self.app.reset_button.instate(["disabled"]))
        self.assertIn("Simulated transport failure", self.app.log.get("1.0", "end"))
        self.assertTrue(self.app.read_button.instate(["!disabled"]))
