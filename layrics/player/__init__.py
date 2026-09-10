"""Playback sources: MPRIS players and direct MPD servers.

All backends are polled at once: the overlay follows whichever source is
playing (see pick_active_source). Everything backend-specific lives under
this package; main.py only calls the helpers below.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from .base import (
    PlaybackState,
    PlayerMonitor,
    PlayerSource,
    PlayerUnavailable,
    SourceSnapshot,
    TrackMeta,
)
from .mpd import (
    Endpoint,
    MpdConnection,
    MpdError,
    MPDSource,
    MpdUnavailable,
    resolve_endpoint,
)
from .mpris import (
    MPRISPlayer,
    MprisSignalMonitor,
    MPRISSource,
    is_excluded,
    scan_players,
)

logger = logging.getLogger(__name__)


def endpoint_from_config(cfg) -> Endpoint:
    """Resolve the [mpd] section plus MPD_* environment into an Endpoint."""
    return resolve_endpoint(
        host=cfg.mpd.host, port=cfg.mpd.port, password=cfg.mpd.password
    )


def mpd_reachable(endpoint: Endpoint, timeout: float = 2.0) -> bool:
    """Probe whether an MPD server answers on this endpoint (read-only)."""
    conn = MpdConnection(endpoint, timeout=timeout)
    try:
        conn.connect()
        return True
    except MpdUnavailable:
        return False
    finally:
        conn.close()


def list_sources(cfg, *, attached: Iterable[str] = ()) -> list[dict]:
    """Selectable sources of every backend: [{id, identity, kind}].

    MPRIS players in [mpris] exclude are ignored outright. MPD counts as
    available while a server answers on its endpoint, or unconditionally
    when its id is in attached (the app is already connected to it).
    """
    sources: list[dict] = []
    for player in scan_players():
        if is_excluded(player.bus_name, cfg.mpris.exclude):
            continue
        try:
            identity = player.get_identity()
        except Exception:
            identity = player.bus_name
        sources.append({"id": player.bus_name, "identity": identity, "kind": "mpris"})
    endpoint = endpoint_from_config(cfg)
    if "mpd" in attached or mpd_reachable(endpoint):
        sources.append(
            {
                "id": "mpd",
                "identity": f"MPD ({endpoint.display})",
                "kind": "mpd",
            }
        )
    return sources


def open_source(cfg, source_id: str) -> PlayerSource:
    """Open one source by id ("mpd" or an MPRIS bus name)."""
    if source_id == "mpd":
        return MPDSource(endpoint_from_config(cfg))
    return MPRISSource(MPRISPlayer(source_id))


RANK = {PlaybackState.PLAYING: 0, PlaybackState.PAUSED: 1}


def pick_active_source(
    items, current: str | None = None, pinned: str | None = None
) -> str | None:
    """Which source the overlay should follow, or None when nothing is live.

    items maps source id -> SourceSnapshot. A pinned source wins as long as
    it is live; a playing native MPD source beats every MPRIS player.
    Otherwise the order is: playing before paused, the current source before
    an equally-ranked rival, a source with a track before one without, then
    the id.
    """
    live = {sid: snap for sid, snap in items.items() if snap.state in RANK}
    if pinned in live:
        return pinned
    if not live:
        return None
    playing = {
        sid: snap for sid, snap in live.items() if snap.state is PlaybackState.PLAYING
    }
    if playing and MPDSource.source_id in playing:
        return MPDSource.source_id
    return min(
        live,
        key=lambda sid: (
            RANK[live[sid].state],
            sid != current,
            0 if (live[sid].track and live[sid].track.title) else 1,
            sid,
        ),
    )


__all__ = [
    "Endpoint",
    "MPDSource",
    "MPRISPlayer",
    "MPRISSource",
    "MpdConnection",
    "MpdError",
    "MpdUnavailable",
    "MprisSignalMonitor",
    "PlaybackState",
    "PlayerMonitor",
    "PlayerSource",
    "PlayerUnavailable",
    "SourceSnapshot",
    "TrackMeta",
    "endpoint_from_config",
    "is_excluded",
    "list_sources",
    "mpd_reachable",
    "open_source",
    "pick_active_source",
    "scan_players",
]
