"""Playback-source reconciliation (main.py::_sync) with fake sources.

Covers the multi-backend paths: one fetch per track even when two backends
publish the same song, following the playing source, and clearing when every
source stops.
"""

import asyncio

from layrics import main
from layrics.main import LayricsApp
from layrics.player import PlaybackState, SourceSnapshot, TrackMeta


def track(title: str) -> TrackMeta:
    return TrackMeta(unique_song_id=title, title=title, artists=["a"], length=1000000)


class FakeSource:
    def __init__(self, kind: str, snapshot: SourceSnapshot):
        self.kind = kind
        self.source_id = kind
        self._snapshot = snapshot

    def identity(self) -> str:
        return self.kind

    def snapshot(self) -> SourceSnapshot:
        return self._snapshot

    def start(self):
        raise AssertionError("not used by _sync")

    def close(self) -> None:
        pass


class FakeState:
    def __init__(self):
        self.paused = False


class FakeCtrl:
    def __init__(self):
        self.state = FakeState()
        self.ass: str | None = None

    def set_status(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self.state, key, value)

    def set_ass_input(self, content: str) -> None:
        self.ass = content


def make_app(sources: dict[str, FakeSource]) -> LayricsApp:
    app = object.__new__(LayricsApp)
    app._config = None
    app._sources = sources
    app._monitors = {}
    app._active_id = None
    app._pinned_id = None
    app._last_track = None
    app._last_track_key = None
    app._last_state = None
    app._last_position_us = 0
    app._fetch_gen = 0
    app._lyrics_delay_ms = 0
    app.ctrl = FakeCtrl()
    app.fetched: list[str] = []

    async def fake_fetch(track, gen):
        app.fetched.append(track.title or "")

    app._auto_fetch_lyrics = fake_fetch
    return app


async def sync(app: LayricsApp) -> None:
    app._sync()
    await asyncio.sleep(0)  # let the created fetch task run


def playing(t: TrackMeta | None) -> SourceSnapshot:
    return SourceSnapshot(
        state=PlaybackState.PLAYING,
        position_us=0,
        track=t,
        song_key=t.title if t else None,
    )


def paused(t: TrackMeta | None) -> SourceSnapshot:
    return SourceSnapshot(
        state=PlaybackState.PAUSED,
        position_us=0,
        track=t,
        song_key=t.title if t else None,
    )


def stopped() -> SourceSnapshot:
    return SourceSnapshot(state=PlaybackState.STOPPED, position_us=0, song_key=None)


def test_duplicate_backends_fetch_once():
    song = track("same")
    mpris = FakeSource("mpris", playing(song))
    mpd = FakeSource("mpd", playing(song))
    app = make_app({"org.mpris.MediaPlayer2.mpd": mpris, "mpd": mpd})

    async def run():
        await sync(app)  # mpd (playing, same track) becomes active
        assert app.fetched == ["same"]
        await sync(app)  # switching between the two must not re-fetch

    asyncio.run(run())
    assert app.fetched == ["same"]


def test_follows_playing_source_and_switches_on_stop():
    app = make_app(
        {
            "a": FakeSource("mpris", paused(track("one"))),
            "mpd": FakeSource("mpd", playing(track("two"))),
        }
    )

    async def run():
        await sync(app)
        assert app._active_id == "mpd"
        assert app.fetched == ["two"]

        app._sources["mpd"]._snapshot = stopped()
        await sync(app)
        assert app._active_id == "a"
        assert app.fetched == ["two", "one"]

    asyncio.run(run())


def test_all_stopped_clears_overlay():
    app = make_app({"mpd": FakeSource("mpd", playing(track("one")))})

    async def run():
        await sync(app)
        assert app.ctrl.ass is not None
        app._sources["mpd"]._snapshot = stopped()
        await sync(app)
        assert app.ctrl.ass == main.EMPTY_ASS
        assert app.ctrl.state.paused is True

    asyncio.run(run())


def test_pin_selects_and_auto_releases():
    app = make_app(
        {
            "a": FakeSource("mpris", playing(track("one"))),
            "mpd": FakeSource("mpd", paused(track("two"))),
        }
    )

    async def run():
        app._pinned_id = "mpd"
        await sync(app)
        assert app._active_id == "mpd"

        app._pinned_id = None
        await sync(app)
        assert app._active_id == "a"

    asyncio.run(run())
