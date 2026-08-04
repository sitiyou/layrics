"""Keyboard input handling: KeyEvent wrapper, hotkey binding and dispatch.

Key events arrive from the C++ core as (keycode, state, mods) tuples via
ApplicationController.poll_key_events(); this module wraps them in KeyEvent
and matches them against hotkeys registered through KeyManager.register().
"""

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

# wl_keyboard modifier masks (xkb modifier order)
MOD_SHIFT = 0x01
MOD_CAPS = 0x02
MOD_CTRL = 0x04
MOD_ALT = 0x08
MOD_NUM = 0x10
MOD_SUPER = 0x40
_MOD_MASK = MOD_SHIFT | MOD_CTRL | MOD_ALT | MOD_SUPER

# key states (wl_keyboard key_state)
KEY_STATE_PRESSED = 0
KEY_STATE_RELEASED = 1

# Modifier keycodes (evdev KEY_*), invalid as a hotkey's main key.
_MOD_KEYCODES = frozenset((29, 42, 54, 56, 97, 100, 125, 126))

# evdev keycodes (linux/input-event-codes.h KEY_*) -> friendly name.
# Letters/digits map to themselves; special keys use semantic names.
_KEYCODES: dict[int, str] = {
    1: "ESC",
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5",
    7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
    12: "MINUS", 13: "EQUAL", 14: "BACKSPACE",
    15: "TAB",
    16: "Q", 17: "W", 18: "E", 19: "R", 20: "T",
    21: "Y", 22: "U", 23: "I", 24: "O", 25: "P",
    26: "LEFTBRACE", 27: "RIGHTBRACE", 28: "ENTER",
    29: "LEFTCTRL",
    30: "A", 31: "S", 32: "D", 33: "F", 34: "G",
    35: "H", 36: "J", 37: "K", 38: "L",
    39: "SEMICOLON", 40: "APOSTROPHE", 41: "GRAVE",
    42: "LEFTSHIFT",
    43: "BACKSLASH",
    44: "Z", 45: "X", 46: "C", 47: "V", 48: "B", 49: "N", 50: "M",
    51: "COMMA", 52: "DOT", 53: "SLASH",
    54: "RIGHTSHIFT",
    55: "KPASTERISK",
    56: "LEFTALT",
    57: "SPACE",
    58: "CAPSLOCK",
    59: "F1", 60: "F2", 61: "F3", 62: "F4", 63: "F5",
    64: "F6", 65: "F7", 66: "F8", 67: "F9", 68: "F10",
    69: "NUMLOCK", 70: "SCROLLLOCK",
    71: "KP7", 72: "KP8", 73: "KP9", 74: "KPMINUS",
    75: "KP4", 76: "KP5", 77: "KP6", 78: "KPPLUS",
    79: "KP1", 80: "KP2", 81: "KP3", 82: "KP0", 83: "KPDOT",
    87: "F11", 88: "F12",
    96: "KPENTER",
    97: "RIGHTCTRL",
    98: "KPSLASH",
    99: "SYSRQ",
    100: "RIGHTALT",
    102: "HOME", 103: "UP", 104: "PAGEUP",
    105: "LEFT", 106: "RIGHT",
    107: "END", 108: "DOWN", 109: "PAGEDOWN",
    110: "INSERT", 111: "DELETE",
    113: "MUTE", 114: "VOLUMEDOWN", 115: "VOLUMEUP",
    119: "PAUSE",
    125: "LEFTSUPER", 126: "RIGHTSUPER",
    127: "MENU",
    163: "NEXT", 164: "PLAYPAUSE", 165: "PREVIOUS", 166: "STOP",
}

_NAME_TO_KEYCODE = {name: code for code, name in _KEYCODES.items()}

# Modifier aliases accepted in hotkey specs.
_MOD_ALIASES = {
    "CTRL": MOD_CTRL, "CONTROL": MOD_CTRL,
    "SHIFT": MOD_SHIFT,
    "ALT": MOD_ALT, "OPT": MOD_ALT,
    "SUPER": MOD_SUPER, "META": MOD_SUPER,
    "WIN": MOD_SUPER, "LOGO": MOD_SUPER,
}


@dataclass(frozen=True)
class KeyEvent:
    """A single key event reported by the wl_keyboard listener."""

    keycode: int
    state: int  # KEY_STATE_PRESSED / KEY_STATE_RELEASED
    mods: int   # wl_keyboard modifier mask

    @property
    def name(self) -> str:
        return _KEYCODES.get(self.keycode, f"KEY_{self.keycode}")

    @property
    def is_pressed(self) -> bool:
        return self.state == KEY_STATE_PRESSED


class Hotkey:
    """A parsed hotkey binding: modifier mask + main keycode + callback."""

    __slots__ = ("spec", "mods", "keycode", "callback")

    def __init__(self, spec: str, callback: Callable[[KeyEvent], Any]):
        parts = [p.strip().upper() for p in spec.split("+")]
        mods = 0
        key = None
        for part in parts:
            if part in _MOD_ALIASES:
                mods |= _MOD_ALIASES[part]
            elif key is None:
                key = part
            else:
                raise ValueError(
                    f"hotkey '{spec}': multiple main keys ('{key}' and '{part}')"
                )
        if key is None:
            raise ValueError(f"hotkey '{spec}': no main key")
        keycode = _NAME_TO_KEYCODE.get(key)
        if keycode is None:
            raise ValueError(f"hotkey '{spec}': unknown key '{key}'")
        if keycode in _MOD_KEYCODES:
            raise ValueError(f"hotkey '{spec}': '{key}' is a modifier key")
        self.spec = spec
        self.mods = mods
        self.keycode = keycode
        self.callback = callback

    def matches(self, event: KeyEvent) -> bool:
        """Match on press, requiring an exact modifier combination.

        Only the four primary modifiers are considered, so Ctrl+K never
        fires while Ctrl+Shift is also held.
        """
        return (
            event.is_pressed
            and event.keycode == self.keycode
            and (event.mods & _MOD_MASK) == self.mods
        )


class KeyManager:
    """Polls key events from the core and dispatches registered hotkeys."""

    POLL_INTERVAL = 0.01
    # Temporary: lyric delay step per key press, in milliseconds.
    LYRIC_DELAY_STEP_MS = 100

    def __init__(self, app):
        self._app = app
        self._ctrl = app.ctrl
        self._hotkeys: list[Hotkey] = []
        self._register_defaults()

    def _register_defaults(self):
        """Built-in bindings; business logic lives here, not in main.py."""
        # Z: lyrics later, X: lyrics earlier, C: reset to player position.
        self.register("Z", lambda ev: self._adjust_lyric_delay(self.LYRIC_DELAY_STEP_MS))
        self.register("X", lambda ev: self._adjust_lyric_delay(-self.LYRIC_DELAY_STEP_MS))
        self.register("C", self._reset_lyric_delay)

    def _adjust_lyric_delay(self, delta_ms: int) -> None:
        start = self._ctrl.state.start_time_ms
        self._ctrl.set_status(start_time_ms=start + delta_ms)
        logger.info("lyric delay %+dms -> start_time_ms=%d", delta_ms, start + delta_ms)

    def _reset_lyric_delay(self, ev) -> None:
        """Re-align the lyric timeline to the player's current position."""
        if self._app.resync_start_time():
            logger.info("lyric delay reset")
        else:
            logger.debug("lyric delay reset skipped (paused or no player)")

    def register(self, spec: str, callback: Callable[[KeyEvent], Any]) -> Hotkey:
        """Bind a hotkey (e.g. "Ctrl+Shift+K") to a callback.

        The callback receives the KeyEvent; it may be sync or async. Keep it
        fast: heavy work should be scheduled with asyncio.create_task().
        Registering the same spec again replaces the previous binding.
        """
        hotkey = Hotkey(spec, callback)
        for i, existing in enumerate(self._hotkeys):
            if existing.spec == spec:
                self._hotkeys[i] = hotkey
                break
        else:
            self._hotkeys.append(hotkey)
        logger.info("hotkey registered: %s", spec)
        return hotkey

    def unregister(self, spec: str) -> bool:
        """Remove a hotkey binding; returns True if it existed."""
        for i, existing in enumerate(self._hotkeys):
            if existing.spec == spec:
                del self._hotkeys[i]
                logger.info("hotkey unregistered: %s", spec)
                return True
        return False

    async def poller(self) -> None:
        """Drain key events from the core and dispatch matched hotkeys.

        Runs as an asyncio task; cancel it to stop processing.
        """
        while True:
            try:
                for key, state, mods in self._ctrl.poll_key_events():
                    event = KeyEvent(key, state, mods)
                    logger.debug(
                        "key: keycode=%d state=%d mods=0x%x", key, state, mods
                    )
                    for hotkey in self._hotkeys:
                        if hotkey.matches(event):
                            logger.debug("hotkey matched: %s", hotkey.spec)
                            await self._invoke(hotkey.callback, event)
                            break
            except Exception:
                logger.exception("key event polling failed")
            await asyncio.sleep(self.POLL_INTERVAL)

    @staticmethod
    async def _invoke(callback: Callable[[KeyEvent], Any], event: KeyEvent) -> None:
        result = callback(event)
        if inspect.isawaitable(result):
            await result
