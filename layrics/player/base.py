"""Playback source interface shared by all player backends.

A PlayerSource reports the current track and playback state (track metadata,
play/pause/stop, position in microseconds) and notifies about changes through
a self-pipe file descriptor, so an asyncio loop can watch it with
add_reader(). LayricsApp only talks to this interface; each backend
(mpris.py, mpd.py) implements it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class PlayerUnavailable(Exception):
    """The playback source is unreachable or got disconnected."""


class PlaybackState(Enum):
    PLAYING = "Playing"
    PAUSED = "Paused"
    STOPPED = "Stopped"


@dataclass
class TrackMeta:
    """Track metadata as reported by a playback source."""

    unique_song_id: str | None = None
    title: str | None = None
    album: str | None = None
    artists: list[str] | None = None
    length: int | None = None  # microseconds

    def __repr__(self) -> str:
        return (
            "TrackMeta("
            f"title={self.title!r}, "
            f"album={self.album!r}, "
            f"artists={self.artists!r}, "
            f"length={self.length}us, "
            f"song_id={self.unique_song_id!r})"
        )


@dataclass(frozen=True)
class SourceSnapshot:
    """One consistent view of a playback source."""

    state: PlaybackState
    position_us: int
    track: TrackMeta | None = None
    # Identifies the current play instance (MPRIS track id, MPD playlist
    # songid); None when nothing is loaded. Track changes must be derived
    # from this key, not from track identity: the same song can start twice
    # in a row (e.g. an MPD queue entry repeated) without metadata changing.
    song_key: str | None = None


@runtime_checkable
class PlayerMonitor(Protocol):
    """Change-notification channel read through an event-loop fd."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def fileno(self) -> int: ...
    def read_events(self) -> list[Any]: ...


class PlayerSource(ABC):
    """One selectable playback source (a player or an MPD server)."""

    kind: str
    source_id: str

    @abstractmethod
    def identity(self) -> str:
        """Human-readable name shown in menus and status output."""

    @abstractmethod
    def snapshot(self) -> SourceSnapshot:
        """Return the current playback state; raises PlayerUnavailable."""

    @abstractmethod
    def start(self) -> PlayerMonitor:
        """Bring up the change monitor; raises PlayerUnavailable."""

    @abstractmethod
    def close(self) -> None:
        """Stop the monitor and release connections."""
