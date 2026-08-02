"""Integration tests for the C++ overlay render-loop state machine.

These tests drive the real Wayland client (ApplicationController) against a
running compositor that supports wlr-layer-shell (Sway/Hyprland/...). They are
skipped when no Wayland display is available.

Notes:
- Commands are processed asynchronously on the render thread (16ms poll
  cadence), so assertions wait for the state change to take effect.

Run:
    uv run python -m unittest tests.test_wayland_state
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
import unittest

from layrics.core import ApplicationController

ASS = """\
[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK JP,48,&H00FCDD1C,&H00FFFFFF,&H005C3317,&H4C000000,0,0,0,0,100,100,0,0,1,3,1,2,480,480,64,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:30.00,Default,,0,0,0,,{\\kf80}千{\\kf80}本{\\kf80}桜
"""


def wayland_available() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY"))


@unittest.skipUnless(wayland_available(), "no Wayland display available")
class StateMachineTest(unittest.TestCase):
    """Paused/hidden/locked transitions against a live compositor."""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(level=logging.ERROR)
        cls.ctrl = ApplicationController()
        cls.ctrl.start()
        cls.ctrl.set_ass_input(ASS)
        time.sleep(1.0)  # let the first frame render

    @classmethod
    def tearDownClass(cls):
        cls.ctrl.stop()
        cls.ctrl.join()

    def setUp(self):
        # Reset to normal state and wait for the commands to take effect.
        self.ctrl.set_status(paused=False, hidden=False, locked=False)
        time.sleep(0.4)

    def test_normal(self):
        s = self.ctrl.state
        self.assertFalse(s.paused)
        self.assertFalse(s.hidden)
        self.assertFalse(s.locked)

    def test_pause_cycle(self):
        self.ctrl.set_status(paused=True)
        time.sleep(0.3)
        self.assertTrue(self.ctrl.state.paused)
        self.ctrl.set_status(paused=False)
        time.sleep(0.4)
        self.assertFalse(self.ctrl.state.paused)

    def test_hide_cycle(self):
        self.ctrl.set_status(hidden=True)
        time.sleep(0.3)
        self.assertTrue(self.ctrl.state.hidden)
        self.ctrl.set_status(hidden=False)
        time.sleep(0.4)
        self.assertFalse(self.ctrl.state.hidden)

    def test_lock_cycle(self):
        self.ctrl.set_status(locked=True)
        time.sleep(0.3)
        self.assertTrue(self.ctrl.state.locked)
        self.ctrl.set_status(locked=False)
        time.sleep(0.3)
        self.assertFalse(self.ctrl.state.locked)

    def test_paused_hidden_combo(self):
        self.ctrl.set_status(paused=True, hidden=True)
        time.sleep(0.3)
        self.assertTrue(self.ctrl.state.paused)
        self.assertTrue(self.ctrl.state.hidden)
        self.ctrl.set_status(hidden=False)
        time.sleep(0.3)
        self.assertTrue(self.ctrl.state.paused, "unhide must not clear pause")
        self.ctrl.set_status(paused=False)
        time.sleep(0.4)
        s = self.ctrl.state
        self.assertFalse(s.paused)
        self.assertFalse(s.hidden)

    def test_back_to_back_transitions(self):
        for _ in range(3):
            self.ctrl.set_status(paused=True)
            time.sleep(0.15)
            self.ctrl.set_status(paused=False)
            time.sleep(0.15)
        self.assertFalse(self.ctrl.state.paused)

        # unhide + pause issued back-to-back (crosses poll rounds)
        self.ctrl.set_status(hidden=True)
        time.sleep(0.2)
        self.ctrl.set_status(hidden=False, paused=True)
        time.sleep(0.3)
        s = self.ctrl.state
        self.assertFalse(s.hidden)
        self.assertTrue(s.paused)
        self.ctrl.set_status(paused=False)
        time.sleep(0.3)

    def test_repeated_hide_cycle(self):
        for _ in range(3):
            self.ctrl.set_status(hidden=True)
            time.sleep(0.15)
            self.ctrl.set_status(hidden=False)
            time.sleep(0.15)
        self.assertFalse(self.ctrl.state.hidden)


@unittest.skipUnless(wayland_available(), "no Wayland display available")
@unittest.skipUnless(shutil.which("strace"), "strace not available")
class ZeroCommitTest(unittest.TestCase):
    """Verifies that no Wayland requests are sent while paused or hidden.

    The render thread must stop the frame chain (no attach/commit) in those
    states; Wayland client requests go out via sendmsg() on the display
    socket. The probe writes M1..M4 markers to a file; with ``strace -r``
    those writes and the sendmsg calls share one relative-timestamp axis,
    so each sendmsg can be bucketed into the phase it belongs to.
    """

    PROBE = """\
import logging, time
logging.basicConfig(level=logging.ERROR)
from layrics.core import ApplicationController

ASS = %r
MARKER = %r

def mark(tag):
    with open(MARKER, "a") as f:
        f.write(tag + "\\n")

ctrl = ApplicationController()
ctrl.start()
ctrl.set_ass_input(ASS)
time.sleep(2.0)
mark("M1")
ctrl.set_status(paused=True)
time.sleep(2.0)
mark("M2")
ctrl.set_status(hidden=True)
time.sleep(2.0)
mark("M3")
ctrl.set_status(hidden=False, paused=False)
time.sleep(2.0)
mark("M4")
ctrl.stop()
ctrl.join()
"""

    @staticmethod
    def _rel_ts(line: str) -> float | None:
        """Relative timestamp from an strace -r line.

        Format is ``PID 0.000123 syscall(...)`` (thread id when -f); the
        timestamp always contains a dot, the pid never does.
        """
        for tok in line.split()[:3]:
            if "." in tok:
                try:
                    return float(tok)
                except ValueError:
                    continue
        return None

    def test_no_commits_while_paused_or_hidden(self):
        import re

        marker = "/tmp/layrics_test_markers.txt"
        strace_log = "/tmp/layrics_test_strace.log"
        for path in (marker, strace_log):
            if os.path.exists(path):
                os.unlink(path)
        try:
            probe = self.PROBE % (ASS, marker)
            subprocess.run(
                ["strace", "-f", "-r", "-e", "trace=sendmsg,write", "-o",
                 strace_log, sys.executable, "-c", probe],
                timeout=40,
                check=True,
                capture_output=True,
            )
            with open(strace_log) as f:
                lines = f.readlines()
        finally:
            for path in (marker, strace_log):
                if os.path.exists(path):
                    os.unlink(path)

        # The probe's marker writes define phase boundaries on the same
        # relative-timestamp axis as the sendmsg calls. strace -r timestamps
        # are deltas between successive calls, so accumulate them.
        bounds: dict[str, float] = {}
        cum = 0.0
        for line in lines:
            delta = self._rel_ts(line)
            if delta is None:
                continue
            cum += delta
            m = re.search(r'write\(\d+, "(M[1-4])', line)
            if m:
                bounds[m.group(1)] = cum
        self.assertEqual(len(bounds), 4, "probe must write 4 markers")

        def phase(ts: float) -> str:
            if ts < bounds["M1"]:
                return "render1"
            if ts < bounds["M2"]:
                return "paused"
            if ts < bounds["M3"]:
                return "hidden"
            return "render2"

        counts = {"render1": 0, "paused": 0, "hidden": 0, "render2": 0}
        cum = 0.0
        for line in lines:
            delta = self._rel_ts(line)
            if delta is None:
                continue
            cum += delta
            if "sendmsg(" in line:
                counts[phase(cum)] += 1

        self.assertGreater(counts["render1"], 50, "expected rendering in phase 1")
        # A couple of boundary commits are expected (the last frame submitted
        # before the pause/hide command takes effect asynchronously); the
        # point is that the frame chain must stop, not keep committing.
        self.assertLessEqual(counts["paused"], 2, "paused must not keep committing")
        self.assertLessEqual(counts["hidden"], 2, "hidden must not keep committing")
        self.assertGreater(counts["render2"], 50, "expected rendering after resume")
        self.assertGreater(
            counts["render1"], max(counts["paused"], counts["hidden"]) * 10,
            "paused/hidden commits should be far below normal rendering",
        )
