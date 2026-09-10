"""MPRIS (Media Player Remote Interfacing Specification) playback source.

Discovers players on the D-Bus session bus, reads track metadata/state over
org.freedesktop.DBus.Properties, and forwards change signals to the app
through a self-pipe fd (GLib main loop on a dedicated thread).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

from .base import (
    PlaybackState,
    PlayerSource,
    PlayerUnavailable,
    SourceSnapshot,
    TrackMeta,
)

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

logger = logging.getLogger(__name__)

MPRIS_PREFIX = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"


def _status_to_state(status: str) -> PlaybackState:
    if status == "Playing":
        return PlaybackState.PLAYING
    if status == "Paused":
        return PlaybackState.PAUSED
    return PlaybackState.STOPPED


class MPRISPlayer:
    """One MPRIS player on the session bus."""

    def __init__(self, bus_name: str):
        self.bus_name = bus_name
        self.bus = dbus.SessionBus()
        try:
            self.obj = self.bus.get_object(bus_name, "/org/mpris/MediaPlayer2")
            self.properties = dbus.Interface(self.obj, dbus_interface=PROPS_IFACE)
        except dbus.DBusException as e:
            raise ConnectionError(f"cannot reach player {bus_name}: {e}") from e

    def get_metadata(self) -> TrackMeta:
        metadata = self.properties.Get(PLAYER_IFACE, "Metadata")
        return self._parse_metadata(metadata)

    def get_position(self) -> int:
        return int(self.properties.Get(PLAYER_IFACE, "Position"))

    def get_playback_status(self) -> str:
        return str(self.properties.Get(PLAYER_IFACE, "PlaybackStatus"))

    def get_identity(self) -> str:
        """The player's human-readable name (falls back to the bus name)."""
        try:
            return str(self.properties.Get("org.mpris.MediaPlayer2", "Identity"))
        except dbus.DBusException as e:
            logger.debug("identity lookup failed for %s: %s", self.bus_name, e)
            return self.bus_name

    @staticmethod
    def _parse_metadata(metadata: dict[str, Any]) -> TrackMeta:
        """Map MPRIS metadata keys to TrackMeta.

        mpris:trackid, xesam:title, xesam:album, xesam:artist, mpris:length
        (microseconds).
        """

        def get_str(key: str) -> str | None:
            val = metadata.get(key)
            return str(val) if val is not None else None

        def get_list_str(key: str) -> list[str] | None:
            val = metadata.get(key)
            return [str(v) for v in val] if val else None

        track_id = get_str("mpris:trackid")
        if track_id and "/" in track_id:
            track_id = track_id.split("/")[-1]

        length: int | None = None
        length_val = metadata.get("mpris:length")
        if length_val is not None:
            try:
                length = int(length_val)
            except ValueError, TypeError:
                length = None

        return TrackMeta(
            unique_song_id=track_id,
            title=get_str("xesam:title"),
            album=get_str("xesam:album"),
            artists=get_list_str("xesam:artist"),
            length=length,
        )


def scan_players() -> list[MPRISPlayer]:
    """Every MPRIS player currently owning a name on the session bus."""
    players: list[MPRISPlayer] = []
    try:
        bus = dbus.SessionBus()
        dbus_obj = bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
        names = dbus.Interface(
            dbus_obj, dbus_interface="org.freedesktop.DBus"
        ).ListNames()
    except dbus.DBusException as e:
        logger.warning("cannot list D-Bus services: %s", e)
        return players

    for name in names:
        if not name.startswith(MPRIS_PREFIX + "."):
            continue
        try:
            players.append(MPRISPlayer(str(name)))
        except ConnectionError as e:
            logger.warning("%s", e)
    return players


def is_excluded(bus_name: str, exclude: list[str]) -> bool:
    """Whether a bus name matches the configured exclude list.

    Accepts the full bus name, the name without the MPRIS prefix, or the
    bare application name before a ".instance..." suffix: browsers append
    one per instance (org.mpris.MediaPlayer2.firefox.instance_1_3634).
    """
    short = bus_name.removeprefix(MPRIS_PREFIX + ".")
    base = short.split(".instance", 1)[0]
    return any(name in (bus_name, short, base) for name in exclude if name)


class MprisSignalMonitor:
    """Player change signals via a GLib thread; wakes a self-pipe per event.

    Emits ``{"type": "sync"}`` per relevant change (playback status, metadata
    or seek). The app-level sync is a full delta comparison, so the payload
    carries no information.
    """

    def __init__(self, bus_name: str):
        self.bus_name = bus_name
        self._r_fd, self._w_fd = os.pipe()
        self._loop: GLib.MainLoop | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> MprisSignalMonitor:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def _run(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._loop = GLib.MainLoop()
        bus = dbus.SessionBus()
        try:
            obj = bus.get_object(self.bus_name, "/org/mpris/MediaPlayer2")
        except dbus.DBusException as e:
            logger.warning("mpris monitor: player %s unavailable: %s", self.bus_name, e)
            return
        obj.connect_to_signal(
            "PropertiesChanged",
            self._on_properties_changed,
            dbus_interface=PROPS_IFACE,
        )
        obj.connect_to_signal("Seeked", self._on_seeked, dbus_interface=PLAYER_IFACE)
        self._loop.run()

    def _emit(self) -> None:
        try:
            os.write(self._w_fd, b'{"type": "sync"}\n')
        except OSError:
            pass

    def _on_properties_changed(self, interface: str, changed: dict, invalidated: dict):
        if interface == PLAYER_IFACE and (
            "PlaybackStatus" in changed or "Metadata" in changed
        ):
            self._emit()

    def _on_seeked(self, position: dbus.Int64):
        self._emit()

    def fileno(self) -> int:
        return self._r_fd

    def read_events(self) -> list[Any]:
        events: list[Any] = []
        try:
            raw = os.read(self._r_fd, 65536)
        except OSError:
            return events
        for line in raw.decode().strip().split("\n"):
            if line:
                events.append(json.loads(line))
        return events

    def stop(self):
        if self._loop is not None:
            self._loop.quit()
            self._loop = None
        if self._thread is not None:
            self._thread = None
        for fd in (self._r_fd, self._w_fd):
            try:
                os.close(fd)
            except OSError:
                pass


class MPRISSource(PlayerSource):
    """A single MPRIS player bound to one D-Bus bus name."""

    kind = "mpris"

    def __init__(self, player: MPRISPlayer):
        self._player = player
        self._monitor: MprisSignalMonitor | None = None
        self.source_id = player.bus_name

    def identity(self) -> str:
        return self._player.get_identity()

    def start(self) -> MprisSignalMonitor:
        if self._monitor is None:
            self._monitor = MprisSignalMonitor(self.bus_name).start()
        return self._monitor

    @property
    def bus_name(self) -> str:
        return self._player.bus_name

    def snapshot(self) -> SourceSnapshot:
        try:
            meta = self._player.get_metadata()
            status = self._player.get_playback_status()
            position = self._player.get_position()
        except Exception as e:
            raise PlayerUnavailable(str(e)) from e
        return SourceSnapshot(
            state=_status_to_state(status),
            position_us=position,
            track=meta,
            song_key=meta.unique_song_id,
        )

    def close(self) -> None:
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None
