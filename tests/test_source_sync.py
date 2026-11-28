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


def test_cached_fetch_timeout_preserves_binding_and_delay(monkeypatch):
    from unittest.mock import AsyncMock

    from httpx import ReadTimeout

    app = make_app({})
    cache = main.SongCache(":memory:")
    song = track("song")
    key = main.make_cache_key(song)
    cache.set(key, "123", "NE")
    cache.set_lyrics_delay(key, "123", "NE", 280)
    monkeypatch.setattr(main, "SongCache", lambda: cache)
    monkeypatch.setattr(main, "_fetch_lyrics", AsyncMock(side_effect=ReadTimeout("offline")))
    search = AsyncMock()
    monkeypatch.setattr(main, "_search_songs", search)
    asyncio.run(LayricsApp._auto_fetch_lyrics(app, song, 0))
    assert cache.get(key).lyrics_song_id == "123"
    assert cache.get_lyrics_delay(key, "123", "NE") == 280
    search.assert_not_awaited()


def test_editing_another_tracks_binding_keeps_current_playback(monkeypatch):
    from unittest.mock import AsyncMock

    app = make_app({})
    app._last_track = track("playing")
    app._last_track_key = main.make_cache_key(app._last_track)
    app._pending_bindings = {}
    cache = main.SongCache(":memory:")
    monkeypatch.setattr(main, "SongCache", lambda: cache)
    monkeypatch.setattr(main, "_fetch_lyrics", AsyncMock(return_value="other lyrics"))
    asyncio.run(app.apply_cache_set("NE123", key="other"))
    assert cache.get("other").lyrics_song_id == "123"
    assert app.ctrl.ass is None
    assert app._fetch_gen == 0


def test_playing_track_resumes_after_mpd_reconnect(monkeypatch):
    app = make_app({"mpd": FakeSource("mpd", playing(track("song")))})

    async def run():
        await sync(app)
        with monkeypatch.context() as patch:
            patch.setattr(app, "_collect_snapshots", lambda: ({}, {"mpd"}))
            await sync(app)
            assert app.ctrl.state.paused
        await sync(app)
        assert not app.ctrl.state.paused
        assert app.fetched == ["song"]

    asyncio.run(run())


def test_missing_bound_lyrics_try_another_source_with_same_id(monkeypatch):
    from unittest.mock import AsyncMock

    app = make_app({})
    cache = main.SongCache(":memory:")
    song = track("song")
    key = main.make_cache_key(song)
    cache.set(key, "123", "NE")
    cache.set_lyrics_delay(key, "123", "NE", 280)
    monkeypatch.setattr(main, "SongCache", lambda: cache)
    matches = [
        {"title": "song", "artist": ["a"], "source": source, "id": "123"}
        for source in ("NE", "QM")
    ]
    monkeypatch.setattr(main, "_search_songs", AsyncMock(return_value=matches))
    fetch = AsyncMock(side_effect=[main.LyricsNotFoundError("missing"), "lyrics"])
    monkeypatch.setattr(main, "_fetch_lyrics", fetch)

    assert asyncio.run(app._fetch_ass_for_track(song)) == ("lyrics", key, "123", "QM")
    assert [call.args[0].source.name for call in fetch.await_args_list] == ["NE", "QM"]
    assert cache.get(key).lyrics_source == "QM"
    assert cache.get_lyrics_delay(key, "123", "NE") == 280


def test_track_change_clears_before_uncached_search_finishes():
    from unittest.mock import Mock

    async def run():
        mpd = FakeSource("mpd", playing(track("old")))
        unrelated = Mock()
        app = make_app({"browser": unrelated, "mpd": mpd})
        await sync(app)
        app.ctrl.ass = "previous lyrics"
        app.ctrl.clear_input = lambda: setattr(app.ctrl, "ass", None)
        release = asyncio.Event()

        async def slow_fetch(track, gen):
            await release.wait()
            app.ctrl.set_ass_input("new lyrics")

        app._auto_fetch_lyrics = slow_fetch
        mpd._snapshot = playing(track("new"))
        await sync(app)
        assert app.ctrl.ass is None
        unrelated.snapshot.assert_not_called()
        release.set()
        await asyncio.sleep(0)
        assert app.ctrl.ass == "new lyrics"

    asyncio.run(run())
