"""Source selection policy and MPRIS bus-name exclusion (no D-Bus needed)."""

from layrics.player import PlaybackState, SourceSnapshot, TrackMeta, pick_active_source
from layrics.player.mpris import is_excluded

TRACK = TrackMeta(unique_song_id="1", title="song", artists=["a"])


def snap(state: PlaybackState, track: TrackMeta | None = TRACK) -> SourceSnapshot:
    return SourceSnapshot(state=state, position_us=0, track=track, song_key="1")


def test_pick_prefers_playing_over_paused():
    items = {
        "org.mpris.MediaPlayer2.a": snap(PlaybackState.PAUSED),
        "org.mpris.MediaPlayer2.b": snap(PlaybackState.PLAYING),
    }
    assert pick_active_source(items) == "org.mpris.MediaPlayer2.b"


def test_pick_prefers_track_over_no_metadata():
    items = {
        "org.mpris.MediaPlayer2.a": snap(PlaybackState.PLAYING, track=None),
        "org.mpris.MediaPlayer2.b": snap(PlaybackState.PLAYING),
    }
    assert pick_active_source(items) == "org.mpris.MediaPlayer2.b"


def test_pick_keeps_current_on_tie():
    items = {
        "org.mpris.MediaPlayer2.a": snap(PlaybackState.PLAYING),
        "org.mpris.MediaPlayer2.b": snap(PlaybackState.PLAYING),
    }
    assert pick_active_source(items, current="org.mpris.MediaPlayer2.b") == (
        "org.mpris.MediaPlayer2.b"
    )


def test_paused_current_yields_to_playing_source():
    items = {
        "org.mpris.MediaPlayer2.a": snap(PlaybackState.PAUSED),
        "org.mpris.MediaPlayer2.b": snap(PlaybackState.PLAYING),
    }
    assert pick_active_source(items, current="org.mpris.MediaPlayer2.a") == (
        "org.mpris.MediaPlayer2.b"
    )


def test_playing_current_is_not_displaced_by_another_playing_with_track():
    items = {
        "org.mpris.MediaPlayer2.a": snap(PlaybackState.PLAYING, track=None),
        "org.mpris.MediaPlayer2.b": snap(PlaybackState.PLAYING),
    }
    assert pick_active_source(items, current="org.mpris.MediaPlayer2.a") == (
        "org.mpris.MediaPlayer2.a"
    )


def test_pick_falls_back_to_first_id():
    items = {
        "org.mpris.MediaPlayer2.b": snap(PlaybackState.PAUSED),
        "mpd": snap(PlaybackState.PAUSED),
    }
    assert pick_active_source(items) == "mpd"


def test_playing_mpd_beats_playing_mpris_even_if_mpris_is_current():
    items = {
        "mpd": snap(PlaybackState.PLAYING),
        "org.mpris.MediaPlayer2.a": snap(PlaybackState.PLAYING),
    }
    assert pick_active_source(items, current="org.mpris.MediaPlayer2.a") == "mpd"


def test_playing_mpd_beats_playing_mpris_without_track():
    items = {
        "mpd": snap(PlaybackState.PLAYING, track=None),
        "org.mpris.MediaPlayer2.a": snap(PlaybackState.PLAYING),
    }
    assert pick_active_source(items) == "mpd"


def test_paused_mpd_does_not_beat_playing_mpris():
    items = {
        "mpd": snap(PlaybackState.PAUSED),
        "org.mpris.MediaPlayer2.a": snap(PlaybackState.PLAYING),
    }
    assert pick_active_source(items) == "org.mpris.MediaPlayer2.a"


def test_pinned_source_wins_while_live():
    items = {
        "org.mpris.MediaPlayer2.a": snap(PlaybackState.PLAYING),
        "mpd": snap(PlaybackState.PAUSED),
    }
    assert pick_active_source(items, pinned="mpd") == "mpd"


def test_pinned_source_loses_when_stopped():
    items = {
        "org.mpris.MediaPlayer2.a": snap(PlaybackState.PLAYING),
        "mpd": snap(PlaybackState.STOPPED, track=None),
    }
    assert pick_active_source(items, pinned="mpd") == "org.mpris.MediaPlayer2.a"


def test_nothing_live_returns_none():
    items = {
        "mpd": snap(PlaybackState.STOPPED, track=None),
        "org.mpris.MediaPlayer2.a": snap(PlaybackState.STOPPED, track=None),
    }
    assert pick_active_source(items) is None
    assert pick_active_source({}) is None


def test_is_excluded_matches_bus_name_forms():
    bus = "org.mpris.MediaPlayer2.firefox.instance_1_3634"
    assert is_excluded(bus, ["firefox"])
    assert is_excluded(bus, ["firefox.instance_1_3634"])
    assert is_excluded(bus, [bus])
    assert is_excluded("org.mpris.MediaPlayer2.mpd", ["mpd"])


def test_is_excluded_ignores_others():
    bus = "org.mpris.MediaPlayer2.mpd"
    assert not is_excluded(bus, [])
    assert not is_excluded(bus, ["firefox"])
    assert not is_excluded(bus, [""])
    assert not is_excluded(bus, ["org.mpris.MediaPlayer2.mp"])
