"""Native MPD protocol support (no mpDris2/MPRIS indirection).

Implements only the command surface layrics needs: greeting + optional
password, ``status``, ``currentsong`` and an ``idle player`` event loop.
Design notes (lessons from https://github.com/Mic92/python-mpd2/issues/31,
where long-lived python-mpd2 clients were silently dropped by the server):

- Two separate connections. While a connection waits in ``idle`` the server
  disables its inactivity timeout, but it closes any *other* connection that
  stays silent for ``connection_timeout`` seconds (default 60). The query
  connection is therefore exercised every second by the app's poller, and
  the idle connection never issues other commands.
- Reconnects are transparent. Every request re-establishes the connection
  on failure, and because all issued commands are read-only, a response lost
  to a dropped connection is always safe to retry.
- The query socket is only touched from the event-loop thread and the idle
  socket only from its own daemon thread; no socket is shared across threads
  (python-mpd2 was additionally not thread-safe).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from dataclasses import dataclass
from typing import Any

from .base import (
    PlaybackState,
    PlayerSource,
    PlayerUnavailable,
    SourceSnapshot,
    TrackMeta,
)

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6600
GREETING_PREFIX = "OK MPD "
SUCCESS = "OK"
ERROR_PREFIX = "ACK "


class MpdError(Exception):
    pass


class MpdUnavailable(MpdError):
    """Connection-level failure (unreachable, dropped, broken stream)."""


class MpdCommandError(MpdError):
    """The server replied with an ``ACK`` error."""


class MpdProtocolError(MpdError):
    """The server sent something that is not valid MPD."""


@dataclass(frozen=True)
class Endpoint:
    """Resolved MPD address: TCP host:port or a (abstract) unix socket."""

    display: str
    password: str | None = None
    # Exactly one of these describes how to reach the server:
    host: str | None = None
    port: int = 0
    path: str | None = None  # unix socket path; None for TCP
    abstract: str | None = None  # abstract socket name (without leading NUL)


def _address_spec(spec: str) -> tuple[str | None, str | None, str | None]:
    """Split a plain address into (host, socket path, abstract name)."""
    if spec.startswith("/"):
        return None, spec, None
    if spec.startswith("@"):
        return None, None, spec[1:]
    return spec, None, None


def _split_env_password(spec: str) -> tuple[str | None, str]:
    """Split the mpc/rmpc ``MPD_HOST`` form ``password@host``.

    A leading ``@`` means an abstract socket, not an empty password; a
    double ``@`` (``password@@abstract``) separates the two.
    """
    if spec.startswith("@"):
        return None, spec
    password, sep, rest = spec.partition("@")
    if not sep:
        return None, spec
    return password, rest


def resolve_endpoint(
    host: str | None = None,
    port: int | None = None,
    password: str | None = None,
) -> Endpoint:
    """Resolve the [mpd] section + MPD_* environment into an Endpoint.

    The [mpd] ``host`` is always a pure address (hostname, ``/path`` or
    ``@abstract``) with the password in its own field; only the ``MPD_HOST``
    environment variable follows the mpc/rmpc convention of embedding it as
    ``password@host``. Each field resolves environment > config > default:
    MPD_HOST / MPD_PORT / MPD_PASSWORD override the config value they name,
    then 127.0.0.1:6600. Password precedence: MPD_PASSWORD, the MPD_HOST
    prefix, then [mpd] password.
    """
    env_host = os.environ.get("MPD_HOST") or ""
    embedded: str | None = None
    if env_host:
        embedded, spec = _split_env_password(env_host)
        host_part, path, abstract = _address_spec(spec)
    elif host:
        host_part, path, abstract = _address_spec(host)
    else:
        host_part, path, abstract = DEFAULT_HOST, None, None

    port_num = DEFAULT_PORT
    env_port = os.environ.get("MPD_PORT", "")
    if env_port.isdigit() and int(env_port) > 0:
        port_num = int(env_port)
    elif port and port > 0:
        port_num = port

    pwd = os.environ.get("MPD_PASSWORD") or embedded or password or None

    if abstract is not None:
        return Endpoint(
            display=f"@{abstract}", password=pwd, abstract=abstract, port=port_num
        )
    if path is not None:
        return Endpoint(display=path, password=pwd, path=path)
    return Endpoint(
        display=f"{host_part}:{port_num}", password=pwd, host=host_part, port=port_num
    )


def _pairs_to_dict(lines: list[str]) -> dict[str, str | list[str]]:
    """Turn ``key: value`` reply lines into a dict; repeated keys become lists.

    MPD emits one line per tag value (e.g. several ``Artist:`` lines), and a
    duplicate key either extends an existing list or turns a single value
    into a two-element list.
    """
    out: dict[str, str | list[str]] = {}
    for line in lines:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key in out:
            existing = out[key]
            if isinstance(existing, list):
                existing.append(value)
            else:
                out[key] = [existing, value]
        else:
            out[key] = value
    return out


def _get_str(mapping: dict[str, str | list[str]], key: str) -> str | None:
    val = mapping.get(key)
    if isinstance(val, list):
        return val[0] if val else None
    return val


def _get_list(mapping: dict[str, str | list[str]], key: str) -> list[str] | None:
    val = mapping.get(key)
    if val is None:
        return None
    if isinstance(val, list):
        return val
    return [val]


class MpdConnection:
    """Blocking connection to one MPD endpoint; owned by a single thread."""

    def __init__(self, endpoint: Endpoint, timeout: float = 3.0):
        self.endpoint = endpoint
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._file: Any = None
        self.version: str | None = None

    def _open_socket(self) -> socket.socket:
        if self.endpoint.abstract is not None:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect("\0" + self.endpoint.abstract)
        elif self.endpoint.path is not None:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self.endpoint.path)
        else:
            sock = socket.create_connection(
                (self.endpoint.host, self.endpoint.port), timeout=self.timeout
            )
        sock.settimeout(self.timeout)
        return sock

    def connect(self) -> None:
        """Connect and authenticate; raises MpdUnavailable on any failure."""
        try:
            self._sock = self._open_socket()
            self._file = self._sock.makefile("rb", buffering=0)
            greeting = self._read_line()
            if not greeting.startswith(GREETING_PREFIX):
                raise MpdProtocolError(f"bad greeting: {greeting!r}")
            self.version = greeting[len(GREETING_PREFIX) :]
            if self.endpoint.password:
                resp = self._roundtrip_raw(f"password {self.endpoint.password}")
                if resp.startswith(ERROR_PREFIX):
                    raise MpdProtocolError(f"authentication rejected: {resp}")
        except MpdProtocolError as e:
            self.close()
            raise MpdUnavailable(str(e)) from e
        except OSError as e:
            self.close()
            raise MpdUnavailable(
                f"cannot connect to {self.endpoint.display}: {e}"
            ) from e

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def abort(self) -> None:
        """Unblock a pending read from another thread (socket is unusable after)."""
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _read_line(self) -> str:
        assert self._file is not None
        try:
            raw = self._file.readline()
        except (OSError, ValueError) as e:
            raise MpdUnavailable(f"read failed: {e}") from e
        if not raw:
            raise MpdUnavailable("connection closed by server")
        return raw.decode("utf-8", "replace").rstrip("\r\n")

    def _send_raw(self, command: str) -> None:
        assert self._sock is not None
        try:
            self._sock.sendall((command + "\n").encode("utf-8"))
        except OSError as e:
            raise MpdUnavailable(f"write failed: {e}") from e

    def _roundtrip_raw(self, command: str) -> str:
        """Send one command; return its trailing OK/ACK line."""
        self._send_raw(command)
        while True:
            line = self._read_line()
            if line == SUCCESS or line.startswith(ERROR_PREFIX):
                return line

    def _fetch_lines(self, command: str) -> list[str]:
        """Run a command and return the reply body lines (ACK becomes an error)."""
        self._send_raw(command)
        lines: list[str] = []
        while True:
            line = self._read_line()
            if line == SUCCESS:
                return lines
            if line.startswith(ERROR_PREFIX):
                raise MpdCommandError(line)
            lines.append(line)

    def command(self, name: str, *args: str) -> dict[str, str | list[str]]:
        """Run a plain command; transparently reconnect on a dropped connection."""
        raw = " ".join([name, *args]).rstrip()
        try:
            lines = self._fetch_lines(raw)
        except MpdUnavailable:
            self.close()
            # Read-only commands are safe to re-run after a reconnect.
            self.connect()
            lines = self._fetch_lines(raw)
        return _pairs_to_dict(lines)

    def idle(
        self, subsystems: str = "player", timeout: float | None = None
    ) -> list[str]:
        """Wait for events; return the changed subsystems (e.g. ["player"]).

        The server holds the reply until something changes, so the read is
        blocking unless the caller passes a timeout. A reconnected idle
        returns immediately only if an event happened while disconnected.
        """
        self._send_raw(f"idle {subsystems}")
        if timeout is not None and self._sock is not None:
            self._sock.settimeout(timeout)
        try:
            lines: list[str] = []
            while True:
                line = self._read_line()
                if line == SUCCESS:
                    return lines
                lines.append(line)
        finally:
            if timeout is not None and self._sock is not None:
                self._sock.settimeout(self.timeout)


class MpdMonitor:
    """``idle player`` loop on a daemon thread; wakes a self-pipe per event.

    Emits ``{"type": "sync"}`` per wakeup: the app-level sync is a full
    delta comparison, so the payload carries no information. The thread
    reconnects with a short backoff until stop().
    """

    RETRY_DELAY = 1.0

    def __init__(self, endpoint: Endpoint):
        self.endpoint = endpoint
        self._r_fd, self._w_fd = os.pipe()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._active: MpdConnection | None = None

    def start(self) -> MpdMonitor:
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="mpd-idle", daemon=True
            )
            self._thread.start()
        return self

    def _emit(self, data: str) -> None:
        try:
            os.write(self._w_fd, (data + "\n").encode())
        except OSError:
            pass

    def _run(self) -> None:
        while not self._stop.is_set():
            conn = MpdConnection(self.endpoint)
            self._active = conn
            try:
                conn.connect()
                while not self._stop.is_set():
                    try:
                        changed = conn.idle()
                    except MpdUnavailable:
                        break
                    logger.debug("mpd idle: %s", ",".join(changed))
                    self._emit('{"type": "sync"}')
            except MpdUnavailable as e:
                logger.debug("mpd idle: connect failed: %s", e)
            finally:
                self._active = None
                conn.close()
            if not self._stop.is_set():
                self._stop.wait(self.RETRY_DELAY)

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

    def stop(self) -> None:
        self._stop.set()
        if self._active is not None:
            self._active.abort()
        if self._thread is not None:
            self._thread = None
        for fd in (self._r_fd, self._w_fd):
            try:
                os.close(fd)
            except OSError:
                pass


class MPDSource(PlayerSource):
    """A single MPD server; connects lazily and reconnects transparently."""

    kind = "mpd"
    source_id = "mpd"

    def __init__(self, endpoint: Endpoint):
        self._endpoint = endpoint
        self._monitor: MpdMonitor | None = None
        self._conn: MpdConnection | None = None
        self._last_song_id: str | None = None
        self._last_meta: TrackMeta | None = None

    def identity(self) -> str:
        return f"MPD ({self._endpoint.display})"

    def start(self) -> MpdMonitor:
        if self._monitor is None:
            self._monitor = MpdMonitor(self._endpoint).start()
        return self._monitor

    def close(self) -> None:
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _get_conn(self) -> MpdConnection:
        if self._conn is None:
            conn = MpdConnection(self._endpoint)
            conn.connect()
            self._conn = conn
        return self._conn

    def snapshot(self) -> SourceSnapshot:
        try:
            conn = self._get_conn()
            st = conn.command("status")
        except MpdUnavailable as e:
            self._conn = None
            raise PlayerUnavailable(str(e)) from e
        except MpdCommandError as e:
            self._conn = None
            raise PlayerUnavailable(f"status failed: {e}") from e

        state = _get_str(st, "state") or "stop"
        if state == "play":
            pstate = PlaybackState.PLAYING
        elif state == "pause":
            pstate = PlaybackState.PAUSED
        else:
            pstate = PlaybackState.STOPPED

        elapsed = _get_str(st, "elapsed") or _get_str(st, "time") or "0"
        try:
            position_us = int(float(elapsed) * 1_000_000)
        except ValueError:
            position_us = 0

        if pstate is PlaybackState.STOPPED:
            self._last_song_id = None
            self._last_meta = None
            return SourceSnapshot(state=pstate, position_us=position_us)

        song_id = _get_str(st, "songid")
        if song_id != self._last_song_id or self._last_meta is None:
            try:
                cs = conn.command("currentsong")
            except (MpdUnavailable, MpdCommandError) as e:
                self._conn = None
                raise PlayerUnavailable(str(e)) from e
            self._last_meta = MPDSource._meta_from_song(cs)
            self._last_song_id = song_id
        return SourceSnapshot(
            state=pstate,
            position_us=position_us,
            track=self._last_meta,
            song_key=song_id,
        )

    @staticmethod
    def _meta_from_song(cs: dict[str, str | list[str]]) -> TrackMeta:
        file_path = _get_str(cs, "file") or ""
        title = _get_str(cs, "Title")
        if not title and file_path:
            title = os.path.splitext(os.path.basename(file_path.rstrip("/")))[0]
        artists = _get_list(cs, "Artist")
        if not artists:
            artists = _get_list(cs, "AlbumArtist")
        duration = _get_str(cs, "duration") or _get_str(cs, "Time")
        length: int | None = None
        if duration:
            try:
                length = int(float(duration) * 1_000_000)
            except ValueError:
                length = None
        return TrackMeta(
            unique_song_id=file_path or None,
            title=title,
            album=_get_str(cs, "Album"),
            artists=artists,
            length=length,
        )
