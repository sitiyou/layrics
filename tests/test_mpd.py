"""Unit tests for the MPD protocol client (no real MPD, no GUI needed).

Exercises endpoint resolution, the reply framing (_pairs_to_dict with
repeated tags, ACK errors) and full command round-trips against a scripted
fake server on a localhost socket.
"""

import json
import socket
import threading
from typing import Any

import pytest

from layrics.player.mpd import (
    MpdCommandError,
    MpdConnection,
    MpdUnavailable,
    _address_spec,
    _pairs_to_dict,
    _split_env_password,
    resolve_endpoint,
)


class FakeMpd:
    """Scripted MPD server: each (command, reply-lines) pair plays once."""

    def __init__(self, script: list[tuple[str, list[str] | str]]):
        self.script = script
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        conn, _ = self._sock.accept()
        with conn:
            f = conn.makefile("rwb", buffering=0)
            f.write(b"OK MPD 0.25.0\n")
            for cmd, reply in self.script:
                line = f.readline().decode().strip()
                assert line == cmd, f"expected {cmd!r}, got {line!r}"
                if isinstance(reply, str):
                    f.write(reply.encode() + b"\n")
                else:
                    for r in reply:
                        f.write(r.encode() + b"\n")
                    f.write(b"OK\n")

    def close(self):
        self._sock.close()


def _endpoint() -> tuple[str, int]:
    return ("127.0.0.1", 1)


def test_pairs_to_dict_repeated_keys():
    lines = ["Artist: A", "Artist: B", "Title: X", "file: a.flac", "Artist: C"]
    d = _pairs_to_dict(lines)
    assert d["Artist"] == ["A", "B", "C"]
    assert d["Title"] == "X"


def test_address_spec():
    assert _address_spec("localhost") == ("localhost", None, None)
    assert _address_spec("/run/mpd/socket") == (None, "/run/mpd/socket", None)
    assert _address_spec("@mpd") == (None, None, "mpd")


def test_split_env_password():
    assert _split_env_password("remote") == (None, "remote")
    assert _split_env_password("@mpd") == (None, "@mpd")
    assert _split_env_password("secret@remote") == ("secret", "remote")
    assert _split_env_password("secret@@mpd") == ("secret", "@mpd")


@pytest.fixture(autouse=True)
def _no_mpd_env(monkeypatch):
    """The MPD_* environment overrides the config, so tests pin it away."""
    for var in ("MPD_HOST", "MPD_PORT", "MPD_PASSWORD"):
        monkeypatch.delenv(var, raising=False)


def test_resolve_endpoint_defaults():
    ep = resolve_endpoint()
    assert ep.host == "127.0.0.1" and ep.port == 6600 and ep.password is None

    ep = resolve_endpoint(host="", port=0, password="pw")
    assert ep.host == "127.0.0.1" and ep.password == "pw"


def test_resolve_endpoint_config_host_is_a_pure_address():
    """The [mpd] host field never carries a password (unlike MPD_HOST)."""
    ep = resolve_endpoint(host="secret@remote", password="cfg")
    assert ep.host == "secret@remote" and ep.password == "cfg"


def test_resolve_endpoint_env_overrides_config(monkeypatch):
    monkeypatch.setenv("MPD_HOST", "@env")
    monkeypatch.setenv("MPD_PORT", "7000")
    monkeypatch.setenv("MPD_PASSWORD", "envpw")
    ep = resolve_endpoint(host="mpd.local", port=7700, password="cfgpw")
    assert ep.abstract == "env" and ep.password == "envpw"

    monkeypatch.delenv("MPD_HOST")
    monkeypatch.setenv("MPD_PORT", "0")
    ep = resolve_endpoint(host="mpd.local", port=7700)
    assert ep.display == "mpd.local:7700"  # MPD_PORT=0 is not a port


def test_resolve_endpoint_env_embedded_password(monkeypatch):
    monkeypatch.setenv("MPD_HOST", "secret@remote")
    ep = resolve_endpoint()
    assert ep.host == "remote" and ep.password == "secret"

    monkeypatch.setenv("MPD_HOST", "secret@@mpd")
    ep = resolve_endpoint()
    assert ep.abstract == "mpd" and ep.password == "secret"

    monkeypatch.setenv("MPD_HOST", "@mpd")
    ep = resolve_endpoint()
    assert ep.abstract == "mpd" and ep.password is None


def test_resolve_endpoint_password_precedence(monkeypatch):
    monkeypatch.setenv("MPD_HOST", "embedded@remote")
    assert resolve_endpoint(password="cfgpw").password == "embedded"

    monkeypatch.setenv("MPD_PASSWORD", "envpw")
    assert resolve_endpoint(password="cfgpw").password == "envpw"


def test_resolve_endpoint_explicit():
    ep = resolve_endpoint(host="mpd.local", port=7700, password="pw")
    assert ep.display == "mpd.local:7700"
    assert ep.abstract is None and ep.path is None

    ep = resolve_endpoint(host="/run/mpd/socket")
    assert ep.path == "/run/mpd/socket" and ep.host is None

    ep = resolve_endpoint(host="@mpd")
    assert ep.abstract == "mpd" and ep.display == "@mpd"


def test_connect_greeting_and_command(monkeypatch):
    fakes = FakeMpd(
        [
            ("status", ["state: play", "songid: 9", "elapsed: 12.5"]),
            (
                "currentsong",
                [
                    "file: song.flac",
                    "Title: T",
                    "Artist: A",
                    "Artist: B",
                    "duration: 200",
                ],
            ),
        ]
    )
    try:
        ep = resolve_endpoint(host="127.0.0.1", port=fakes.port)
        conn = MpdConnection(ep)
        conn.connect()
        assert conn.version == "0.25.0"
        st = conn.command("status")
        assert st["songid"] == "9"
        assert st["elapsed"] == "12.5"
        cs = conn.command("currentsong")
        assert cs["Artist"] == ["A", "B"]
        conn.close()
    finally:
        fakes.close()


def test_password_auth_roundtrip(monkeypatch):
    fakes = FakeMpd(
        [
            ("password secret", "OK"),
            ("status", ["state: pause"]),
        ]
    )
    try:
        ep = resolve_endpoint(host="127.0.0.1", port=fakes.port, password="secret")
        conn = MpdConnection(ep)
        conn.connect()
        assert conn.command("status")["state"] == "pause"
        conn.close()
    finally:
        fakes.close()


def test_ack_becomes_command_error():
    fakes = FakeMpd([("status", "ACK [3@0] {status} permission denied")])
    try:
        ep = resolve_endpoint(host="127.0.0.1", port=fakes.port)
        conn = MpdConnection(ep)
        conn.connect()
        with pytest.raises(MpdCommandError):
            conn.command("status")
        conn.close()
    finally:
        fakes.close()


def test_bad_greeting_fails():
    class BadServer:
        def __init__(self):
            self._sock = socket.socket()
            self._sock.bind(("127.0.0.1", 0))
            self._sock.listen(1)
            self.port = self._sock.getsockname()[1]
            threading.Thread(target=self._serve, daemon=True).start()

        def _serve(self):
            conn, _ = self._sock.accept()
            with conn:
                conn.sendall(b"HTTP/1.1 400 Bad Request\n")

    srv = BadServer()
    ep = resolve_endpoint(host="127.0.0.1", port=srv.port)
    conn = MpdConnection(ep)
    with pytest.raises(MpdUnavailable):
        conn.connect()
    conn.close()
    srv._sock.close()


def test_idle_roundtrip():
    """idle holds until the server answers; events come back as lines."""
    fakes = FakeMpd([("idle player", ["changed: player"])])
    try:
        ep = resolve_endpoint(host="127.0.0.1", port=fakes.port)
        conn = MpdConnection(ep)
        conn.connect()
        assert conn.idle() == ["changed: player"]
        conn.close()
    finally:
        fakes.close()


def test_monitor_emits_sync_on_idle_event():
    from layrics.player.mpd import Endpoint, MpdMonitor

    fakes = FakeMpd([("idle player", ["changed: player"])])
    try:
        mon = MpdMonitor(Endpoint(display="fake", host="127.0.0.1", port=fakes.port))
        mon.start()
        # The idle reply arrives once; poll the pipe until it shows up.
        import time

        deadline = time.monotonic() + 3
        events: list[Any] = []
        while time.monotonic() < deadline:
            events = mon.read_events()
            if events:
                break
            time.sleep(0.05)
        assert events == [json.loads('{"type": "sync"}')]
        mon.stop()
    finally:
        fakes.close()
