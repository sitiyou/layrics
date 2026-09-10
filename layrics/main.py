"""
layrics - desktop lyrics overlay (wlr-layer-shell + libass)
Provides JSON-based IPC control over a Unix domain socket.

Protocol:
  Request:  {"id": <int>, "method": "<str>", "params": {<opt>}}
  Response: {"id": <int>, "type": "result", "data": <any>}
  Error:    {"id": <int>, "type": "error", "data": {"code": <int>, "message": "<str>"}}

Methods:
  list_players                         -> [{id, identity}]        (sources of every backend)
  select_player  {id}                  -> {selected}    (id = bus name, "mpd", or "auto")
  search_songs   {keyword, limit?}     -> [{id (composite), name, artists, album, source}]
   fetch_lyrics   {song_id?}            -> {ass}  (song_id e.g. "QM248672467", omit for current track)
   load_ass       {path}                -> {loaded}
   hide                                 -> {hidden}
   unhide                               -> {hidden}
   lock                                 -> {locked}
   unlock                               -> {locked}
   set_fps      {fps}                   -> {target_fps}
   stop                                 -> {status}
   start                                -> {status}
   get_status                           -> {player, overlay}
   cache_list                           -> [{key, song_id, lyrics_title, lyrics_artists, updated_at}]
   cache_set     {song_id, key?}       -> {cached}  (key defaults to current track)
   cache_remove  {key?}                -> {removed}  (key defaults to current track)
   ass_set       {key, value}          -> {key, value}
"""

import asyncio
import fcntl
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from typing import Any

from layrics.LDDC.common.exceptions import LyricsNotFoundError
from layrics.LDDC.common.models import SongInfo, Source

from . import menu
from .cache import SongCache, make_cache_key
from .config import get_config
from .core import ApplicationController
from .keys import KeyManager
from .lyricsource import (
    fetch_lyrics as _fetch_lyrics,
)
from .lyricsource import (
    parse_composite_id,
)
from .lyricsource import (
    search_songs as _search_songs,
)
from .matching import clean_search_keyword, match_song
from .player import (
    PlaybackState,
    PlayerSource,
    PlayerUnavailable,
    SourceSnapshot,
    TrackMeta,
    list_sources,
    open_source,
    pick_active_source,
)
from .uimanager import UIManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("layrics.main")

# LAYRICS_DEBUG=lyrics,match  → module-level DEBUG; =core  → C++ DEBUG
for name in os.environ.get("LAYRICS_DEBUG", "").split(","):
    name = name.strip()
    if name and name != "core":
        logging.getLogger(f"layrics.{name}").setLevel(logging.DEBUG)


def _acquire_instance_lock() -> int:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    lock_path = os.path.join(runtime_dir, "layrics.lock")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError as e:
        print(f"Error: Cannot create lock file {lock_path}: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        print("Error: Another instance of layrics is already running.", file=sys.stderr)
        sys.exit(1)
    return fd


ASS_CONFIG_KEYS = {"karaoke", "line_mode", "secondary"}

EMPTY_ASS = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 384
PlayResY: 288

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Sans,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _parse_bool(raw: str) -> bool | None:
    v = raw.lower().strip()
    if v in ("true", "on", "1", "yes"):
        return True
    if v in ("false", "off", "0", "no"):
        return False
    if v == "toggle":
        return None
    raise ValueError(f"invalid boolean: {raw!r}")


class LayricsApp:
    """Orchestrates overlay, playback source, lyric fetching, and IPC."""

    def __init__(self, socket_path: str = ""):
        self.ctrl = ApplicationController()
        self.key_manager = KeyManager(self)
        self.ui_manager = UIManager(self)
        self._config = get_config()
        self._sources: dict[str, PlayerSource] = {}
        self._monitors: dict[str, Any] = {}  # source id -> change monitor (has an fd)
        self._active_id: str | None = None
        self._pinned_id: str | None = None
        self._last_track: TrackMeta | None = None
        self._last_track_key: str | None = None
        self._last_state: PlaybackState | None = None

        self.socket_path = (
            socket_path
            or os.environ.get("LAYRICS_SOCK")
            or os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "layrics.sock")
        )

        self._server: asyncio.AbstractServer | None = None
        self._last_position_us: int = 0
        self._fetch_gen: int = 0
        self._lyrics_delay_ms: int = 0

    @property
    def current_track(self) -> TrackMeta | None:
        """The track currently being displayed (public read for companion modules)."""
        return self._last_track

    @property
    def player(self) -> PlayerSource | None:
        """The source currently being followed (public read for companion modules)."""
        if self._active_id is None:
            return None
        return self._sources.get(self._active_id)

    def quit(self) -> None:
        """Close the IPC server; the event loop then exits run()."""
        if self._server is not None:
            self._server.close()

    # ── overlay control ───────────────────────────────────────────

    def start_overlay(self):
        self.ctrl.start()
        logger.info("overlay started")

    def stop_overlay(self):
        self.ctrl.stop()
        logger.info("overlay stopped")

    def load_ass(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.ctrl.set_ass_input(content)
        logger.info("loaded ass: %s", path)

    async def ui_action(self, action: str) -> None:
        """Dispatch a right-click menu action (handling lives in menu.py)."""
        await menu.handle_action(self, action)

    async def refresh_menu(self) -> None:
        """Rebuild the menu items from current state and push them to the core.

        Triggered on every right-click (menu_requested); the running C++ menu
        swaps to the fresh items on the next frame.
        """
        items = await menu.build_menu(self)
        self.ctrl.set_ui_menu(items)

    # ── shared actions (IPC + right-click menu) ───────────────────

    def apply_target_fps(self, fps: int) -> None:
        """Set the target frame rate and persist it in the config."""
        self.ctrl.set_status(target_fps=fps)
        self._config.overlay.target_fps = fps

    async def apply_ass_config(self, key: str, raw_value: str) -> tuple[str, Any]:
        """Apply an ASS renderer config update; reloads lyrics when available.

        Accepts the same values as the ass_set IPC method (incl. "toggle").
        Returns (key, parsed_value); raises on invalid input.
        """
        if key not in ASS_CONFIG_KEYS:
            raise ValueError(f"unknown config key: {key}")
        if key == "line_mode":
            v = raw_value.lower().strip()
            if v == "single":
                parsed = "single"
            elif v == "double":
                parsed = "double"
            elif v == "toggle":
                parsed = None
            else:
                raise ValueError(
                    f"invalid line_mode: {raw_value!r} (expected single/double/toggle)"
                )
        else:
            parsed = _parse_bool(raw_value)
        if parsed is None:
            current = self._config._provider_config.get("default", {}).get(key)
            if key == "line_mode":
                parsed = "double" if current == "single" else "single"
            else:
                parsed = not bool(current)
        self._config._provider_config.setdefault("default", {})[key] = parsed
        logger.info("ass config: %s = %r", key, parsed)

        if self._last_track is not None:
            try:
                ass, ass_key, song_id, source = await self._fetch_ass_for_track(
                    self._last_track
                )
                self.ctrl.set_ass_input(ass)
                self._restore_lyrics_delay(ass_key, song_id, source)
                logger.info("ass config: lyrics reloaded with new %s = %r", key, parsed)
            except Exception as e:
                logger.warning(
                    "ass config: reload failed for %s = %r: %s", key, parsed, e
                )
        return key, parsed

    async def apply_cache_set(self, song_id: str, key: str = "") -> None:
        """Fetch lyrics for song_id, store the mapping and display them."""
        if not song_id:
            raise RuntimeError("song_id required")
        if not key:
            if self._last_track is None:
                raise RuntimeError("no current track")
            key = make_cache_key(self._last_track)

        cache = SongCache()
        src, raw_id = parse_composite_id(song_id)
        si = cache.lookup_song_info(raw_id, src.name)
        song_info = si or SongInfo.from_dict({"source": src.name, "id": raw_id})
        ass = await _fetch_lyrics(song_info)
        cache.set(key, raw_id, src.name)

        self.ctrl.set_ass_input(ass)
        self._restore_lyrics_delay(key, raw_id, src.name)
        logger.info("cache set: %s -> %s%s", key, src.name, raw_id)

    def apply_cache_remove(self, key: str = "") -> None:
        """Remove a cached song-to-lyrics mapping (defaults to current track)."""
        if not key:
            if self._last_track is None:
                raise RuntimeError("no current track")
            key = make_cache_key(self._last_track)
        SongCache().remove(key)
        logger.info("cache removed: %s", key)

    # ── auto-fetch ────────────────────────────────────────────────

    async def _fetch_ass_for_track(self, meta: TrackMeta) -> tuple[str, str, str, str]:
        """Fetch ASS lyrics for the track; returns (ass, cache_key, song_id, source)."""
        keyword = meta.title or ""
        if meta.artists:
            keyword += " " + " ".join(meta.artists)
        keyword = clean_search_keyword(keyword.strip())
        if not keyword:
            raise RuntimeError(f"empty keyword for track {meta.unique_song_id}")

        cache = SongCache()
        key = make_cache_key(meta)
        cached = cache.get(key)
        if cached is not None:
            logger.info(
                "fetch: cache hit %s -> %s%s",
                keyword,
                cached.lyrics_source,
                cached.lyrics_song_id,
            )
            si = cache.lookup_song_info(cached.lyrics_song_id, cached.lyrics_source)
            if si is None:
                try:
                    src = Source[cached.lyrics_source]
                except KeyError:
                    logger.warning(
                        "fetch: invalid source in cache %s", cached.lyrics_source
                    )
                    cache.remove(key)
                    si = None
                else:
                    si = SongInfo.from_dict(
                        {"source": src.name, "id": cached.lyrics_song_id}
                    )
            if si is not None:
                try:
                    ass = await _fetch_lyrics(si)
                    logger.info("fetch: cache hit %s (%d bytes)", keyword, len(ass))
                    return ass, key, cached.lyrics_song_id, cached.lyrics_source
                except Exception as e:
                    logger.warning("fetch: error fetch lyrics: %s", e)
                    logger.warning("fetch: stale cache entry, removing: %s", key)
                    cache.remove(key)

        logger.info("fetch: searching %s", keyword)
        results = await _search_songs(keyword, 20)
        if not results:
            raise RuntimeError(f"no search results for {keyword!r}")

        cache.store_search_results(results)

        matched = match_song(meta, results)
        if not matched:
            logger.info(
                "fetch: no match for %s in %d candidates", keyword, len(results)
            )
            raise RuntimeError(f"no match found for {keyword!r}")

        src = Source[matched["source"]]
        raw_id = matched["id"]
        song_info = SongInfo.from_dict(matched)
        ass = await _fetch_lyrics(song_info)
        logger.info("fetch: %s -> %s (%d bytes)", keyword, matched["id"], len(ass))

        cache.set_if_missing(key, raw_id, src.name)

        return ass, key, raw_id, src.name

    async def _auto_fetch_lyrics(self, meta: TrackMeta, gen: int) -> None:
        try:
            ass_content, key, song_id, source = await self._fetch_ass_for_track(meta)
        except (RuntimeError, LyricsNotFoundError, json.JSONDecodeError) as e:
            logger.error("auto-fetch: %s", e)
            return
        else:
            if self._fetch_gen != gen:
                return
            self.ctrl.set_ass_input(ass_content)

        if self._fetch_gen != gen:
            return
        self._restore_lyrics_delay(key, song_id, source)

    # ── playback sources (MPRIS players / direct MPD) ─────────────

    def list_players(self) -> list[tuple[str, str]]:
        """Available sources of every backend: [(id, identity)]."""
        sources = list_sources(self._config, attached=self._sources)
        return [(s["id"], s["identity"]) for s in sources]

    def select_player(self, name: str) -> bool:
        """Pin the followed source by id; "auto" (or "") clears the pin."""
        if name in ("", "auto"):
            self._pinned_id = None
            self._sync()
            return True
        self._refresh_sources()
        if name not in self._sources:
            logger.warning("source not found: %s", name)
            return False
        self._pinned_id = name
        self._sync()
        logger.info("pinned source: %s", name)
        return True

    def _refresh_sources(self) -> None:
        """Attach sources that appeared, drop MPRIS ones that vanished.

        MPD stays attached while its monitor reconnects; it is only dropped
        by shutdown.
        """
        ids = {s["id"] for s in list_sources(self._config, attached=self._sources)}
        for sid in ids - self._sources.keys():
            self._attach_source(sid)
        for sid in [s for s, src in self._sources.items() if src.kind != "mpd"]:
            if sid not in ids:
                self._detach_source(sid)

    def _attach_source(self, source_id: str) -> bool:
        """Open a source and register its change monitor with the event loop."""
        source: PlayerSource | None = None
        try:
            source = open_source(self._config, source_id)
            monitor = source.start()
        except (ConnectionError, PlayerUnavailable, ValueError) as e:
            logger.warning("cannot attach source %s: %s", source_id, e)
            if source is not None:
                source.close()
            return False
        self._sources[source_id] = source
        self._monitors[source_id] = monitor
        try:
            loop = asyncio.get_event_loop()
            loop.add_reader(monitor.fileno(), self._on_source_signal, monitor)
        except RuntimeError:
            pass  # event loop not running yet; the poller picks it up
        logger.info("source attached: %s", source_id)
        return True

    def _detach_source(self, source_id: str) -> None:
        """Drop one source, its monitor and its pin."""
        monitor = self._monitors.pop(source_id, None)
        if monitor is not None:
            try:
                loop = asyncio.get_event_loop()
                loop.remove_reader(monitor.fileno())
            except RuntimeError, ValueError:
                pass
            monitor.stop()
        source = self._sources.pop(source_id, None)
        if source is not None:
            source.close()
        if self._active_id == source_id:
            self._active_id = None
        if self._pinned_id == source_id:
            self._pinned_id = None

    def _reset_track_state(self, clear_screen: bool) -> None:
        """Forget the current song; optionally blank the overlay."""
        self._last_track = None
        self._last_track_key = None
        self._last_state = None
        self._last_position_us = 0
        self._fetch_gen += 1
        if clear_screen:
            self.ctrl.set_ass_input(EMPTY_ASS)

    def _on_source_signal(self, monitor) -> None:
        """A change event arrived on a monitor fd: reconcile once."""
        monitor.read_events()
        self._sync()

    def _collect_snapshots(self) -> tuple[dict[str, SourceSnapshot], set[str]]:
        """Snapshot every attached source; drop the MPRIS ones that died."""
        snaps: dict[str, SourceSnapshot] = {}
        failed: set[str] = set()
        for sid, source in list(self._sources.items()):
            try:
                snaps[sid] = source.snapshot()
            except PlayerUnavailable as e:
                failed.add(sid)
                if source.kind == "mpd":
                    # The idle thread reconnects on its own; freeze the overlay
                    # until the next successful snapshot resumes tracking.
                    logger.debug("mpd unavailable: %s", e)
                else:
                    logger.warning("player disconnected: %s", e)
                    self._detach_source(sid)
        return snaps, failed

    def _sync(self) -> None:
        """Pick the source to follow and apply its deltas to the overlay.

        Single reconciliation path used by both the 1s poller and the change
        monitors; each step is idempotent. start_time_ms is only rebased on
        real transitions (new track, play/pause, seek jumps) to avoid drift.
        """
        snaps, failed = self._collect_snapshots()
        active = pick_active_source(
            snaps, current=self._active_id, pinned=self._pinned_id
        )

        if active is None:
            if self._active_id in failed:
                if not self.ctrl.state.paused:
                    self.ctrl.set_status(paused=True)
                return
            # Every source is stopped or unloaded: clear the screen and freeze.
            if (
                self._last_state is not PlaybackState.STOPPED
                or self._last_track is not None
            ):
                self._reset_track_state(clear_screen=True)
            if not self.ctrl.state.paused:
                self.ctrl.set_status(paused=True)
            self._last_state = PlaybackState.STOPPED
            self._last_position_us = 0
            return

        if active != self._active_id:
            logger.info("following: %s", active)
            self._active_id = active

        snap = snaps[active]
        state = snap.state
        pos = snap.position_us
        track = snap.track

        # Track changes are detected by cache key, not by per-source song id:
        # the same song can be published by two backends at once (MPD and
        # mpDris2 wrapping it), and switching between them must not re-fetch.
        track_key = make_cache_key(track) if track and track.title else None
        if track_key != self._last_track_key:
            self._fetch_gen += 1
            self._last_track_key = track_key
            self._last_track = track
            self._last_position_us = pos
            if track_key is None:
                self.ctrl.set_ass_input(EMPTY_ASS)
                return
            logger.info("track changed: %s", track.title)
            self.ctrl.set_ass_input(EMPTY_ASS)
            asyncio.get_event_loop().create_task(
                self._auto_fetch_lyrics(track, self._fetch_gen)
            )

        now_ms = int(time.monotonic() * 1000)
        if state is not self._last_state:
            self._last_state = state
            if state is PlaybackState.PLAYING:
                self.ctrl.set_status(
                    paused=False,
                    start_time_ms=now_ms - pos // 1000 + self._lyrics_delay_ms,
                )
            elif state is PlaybackState.PAUSED:
                self.ctrl.set_status(paused=True)

        # Seek detection: a position jump while playing means the user seeked.
        if state is PlaybackState.PLAYING:
            expected = self._last_position_us + 1_000_000
            if abs(pos - expected) > 500_000:
                self.ctrl.set_status(
                    start_time_ms=now_ms - pos // 1000 + self._lyrics_delay_ms
                )
        self._last_position_us = pos

    def adjust_lyrics_delay(self, delta_ms: int) -> None:
        """Shift the lyrics timeline by delta_ms relative to the player."""
        self._lyrics_delay_ms += delta_ms
        self._persist_lyrics_delay()
        self._sync_with_delay()
        logger.info("lyrics delay %+dms -> total %dms", delta_ms, self._lyrics_delay_ms)

    def reset_lyrics_delay(self) -> bool:
        """Reset the lyrics delay and re-align to the player position.

        Returns False while paused or when no source is selected.
        """
        if self.ctrl.state.paused or self.player is None:
            return False
        self._lyrics_delay_ms = 0
        self._persist_lyrics_delay()
        self._sync_with_delay()
        logger.info("lyrics delay reset")
        return True

    def _persist_lyrics_delay(self) -> None:
        """Save the current lyrics delay for the current track."""
        if self._last_track is None:
            return
        key = make_cache_key(self._last_track)
        cache = SongCache()
        entry = cache.get(key)
        if entry is None:
            return
        cache.set_lyrics_delay(
            key, entry.lyrics_song_id, entry.lyrics_source, self._lyrics_delay_ms
        )
        logger.debug("lyrics delay persisted: %+dms (%s)", self._lyrics_delay_ms, key)

    def _restore_lyrics_delay(self, key: str, song_id: str, source: str) -> None:
        """Load the persisted lyrics delay for this track and re-sync."""
        cache = SongCache()
        delay = cache.get_lyrics_delay(key, song_id, source)
        self._lyrics_delay_ms = delay if delay is not None else 0
        if delay:
            logger.info("lyrics delay restored: %+dms (%s)", delay, key)
        if not self.ctrl.state.paused:
            self._sync_with_delay()

    def _sync_with_delay(self) -> bool:
        """Set start_time_ms = now - pos + lyrics_delay_ms.

        Returns False when no source is selected or its position is
        unavailable.
        """
        source = self.player
        if source is None:
            return False
        try:
            pos = source.snapshot().position_us
        except PlayerUnavailable:
            return False
        now_ms = int(time.monotonic() * 1000)
        self.ctrl.set_status(start_time_ms=now_ms - pos // 1000 + self._lyrics_delay_ms)
        return True

    # ── Lyric search (LDDC) ──────────────────────────────────────

    async def search_songs(self, keyword: str, limit: int = 10):
        return await _search_songs(keyword, limit)

    async def fetch_lyrics(self, song_data: dict) -> str:
        song_info = SongInfo.from_dict(song_data)
        ass_content = await _fetch_lyrics(song_info)
        logger.info("lyrics fetched (%d bytes)", len(ass_content))
        return ass_content

    # ── IPC command dispatch ──────────────────────────────────────

    async def _execute(self, req: dict) -> dict:
        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params", {})

        try:
            if method == "list_players":
                players = self.list_players()
                return {
                    "id": req_id,
                    "type": "result",
                    "data": [{"id": pid, "identity": name} for pid, name in players],
                }

            elif method == "select_player":
                name = params.get("name", "")
                ok = self.select_player(name)
                if ok:
                    return {
                        "id": req_id,
                        "type": "result",
                        "data": {"selected": name or "auto"},
                    }
                return {
                    "id": req_id,
                    "type": "error",
                    "data": {"code": 404, "message": f"player not found: {name}"},
                }

            elif method == "search_songs":
                keyword = params.get("keyword", "")
                limit = params.get("limit", 10)
                data = await self.search_songs(keyword, limit)
                # IPC boundary: composite id (source-name prefix) for layctl to echo back
                data = [{**d, "id": f"{d['source']}{d['id']}"} for d in data]
                return {"id": req_id, "type": "result", "data": data}

            elif method == "fetch_lyrics":
                song_id = params.get("song_id", "") or ""
                if song_id:
                    src, raw_id = parse_composite_id(song_id)
                    song_data = {
                        "id": raw_id,
                        "source": src.name,
                        "title": params.get("title"),
                        "artist": params.get("artist", []),
                        "album": params.get("album"),
                        "duration": params.get("duration"),
                    }
                else:
                    if not self._last_track:
                        return {
                            "id": req_id,
                            "type": "error",
                            "data": {"code": 400, "message": "no current track"},
                        }
                    ass_content, _, _, _ = await self._fetch_ass_for_track(
                        self._last_track
                    )
                    return {
                        "id": req_id,
                        "type": "result",
                        "data": {"ass": ass_content},
                    }
                ass_content = await self.fetch_lyrics(song_data)
                return {"id": req_id, "type": "result", "data": {"ass": ass_content}}

            elif method == "load_ass":
                path = params.get("path", "")
                if not path:
                    return {
                        "id": req_id,
                        "type": "error",
                        "data": {"code": 400, "message": "missing path"},
                    }
                self.load_ass(path)
                return {"id": req_id, "type": "result", "data": {"loaded": path}}

            elif method == "hide":
                raw = params.get("value", "true")
                if isinstance(raw, bool):
                    val = raw
                else:
                    try:
                        parsed = _parse_bool(raw if isinstance(raw, str) else "true")
                    except ValueError:
                        return {
                            "id": req_id,
                            "type": "error",
                            "data": {"code": 400, "message": f"invalid value: {raw!r}"},
                        }
                    val = not self.ctrl.state.hidden if parsed is None else parsed
                self.ctrl.set_status(hidden=val)
                return {"id": req_id, "type": "result", "data": {"hidden": val}}

            elif method == "unhide":
                self.ctrl.set_status(hidden=False)
                return {"id": req_id, "type": "result", "data": {"hidden": False}}

            elif method == "lock":
                raw = params.get("value", "true")
                if isinstance(raw, bool):
                    val = raw
                else:
                    try:
                        parsed = _parse_bool(raw if isinstance(raw, str) else "true")
                    except ValueError:
                        return {
                            "id": req_id,
                            "type": "error",
                            "data": {"code": 400, "message": f"invalid value: {raw!r}"},
                        }
                    val = not self.ctrl.state.locked if parsed is None else parsed
                self.ctrl.set_status(locked=val)
                return {"id": req_id, "type": "result", "data": {"locked": val}}

            elif method == "unlock":
                self.ctrl.set_status(locked=False)
                return {"id": req_id, "type": "result", "data": {"locked": False}}

            elif method == "set_fps":
                fps = params.get("fps", -1)
                if not isinstance(fps, int) or (fps <= 0 and fps != -1):
                    return {
                        "id": req_id,
                        "type": "error",
                        "data": {
                            "code": 400,
                            "message": "fps must be > 0 or -1 (vsync)",
                        },
                    }
                self.apply_target_fps(fps)
                return {"id": req_id, "type": "result", "data": {"target_fps": fps}}

            elif method == "stop":
                self.stop_overlay()
                return {
                    "id": req_id,
                    "type": "result",
                    "data": {"status": "stopped"},
                }

            elif method == "start":
                self.start_overlay()
                if (
                    self._last_track is not None
                    and self.player is not None
                    and self._sync_with_delay()
                ):
                    self.ctrl.set_status(hidden=False)
                    logger.info("re-synced start_time on start")
                return {
                    "id": req_id,
                    "type": "result",
                    "data": {"status": "started"},
                }

            elif method == "get_status":
                player_info = None
                source = self.player
                if source is not None:
                    try:
                        snap = source.snapshot()
                        player_info = {
                            "kind": source.kind,
                            "id": source.source_id,
                            "identity": source.identity(),
                            "pinned": source.source_id == self._pinned_id,
                            "playback_status": snap.state.value,
                            "position_ms": snap.position_us // 1000,
                        }
                        if snap.track:
                            player_info["track"] = asdict(snap.track)
                    except Exception:
                        player_info = {"error": "disconnected"}
                s = self.ctrl.state
                overlay = {
                    "paused": s.paused,
                    "hidden": s.hidden,
                    "locked": s.locked,
                    "start_time_ms": s.start_time_ms,
                    "drag_offset_x": s.drag_offset_x,
                    "drag_offset_y": s.drag_offset_y,
                    "target_fps": s.target_fps,
                    "position_ms": int(time.monotonic() * 1000) - s.start_time_ms,
                }
                return {
                    "id": req_id,
                    "type": "result",
                    "data": {
                        "player": player_info,
                        "overlay": overlay,
                    },
                }

            elif method == "cache_list":
                cache = SongCache()
                entries = cache.list_all()
                return {
                    "id": req_id,
                    "type": "result",
                    "data": [
                        {
                            "key": e["key"],
                            "song_id": e["song_id"],
                            "lyrics_title": e["lyrics_title"],
                            "lyrics_artists": e["lyrics_artists"],
                            "lyrics_album": e["lyrics_album"],
                            "lyrics_duration": e["lyrics_duration"],
                            "updated_at": e["updated_at"],
                        }
                        for e in entries
                    ],
                }

            elif method == "cache_set":
                song_id = params.get("song_id", "")
                key = params.get("key") or ""
                try:
                    await self.apply_cache_set(song_id, key)
                except (
                    RuntimeError,
                    ValueError,
                    LyricsNotFoundError,
                    json.JSONDecodeError,
                ) as e:
                    return {
                        "id": req_id,
                        "type": "error",
                        "data": {"code": 400, "message": str(e)},
                    }
                return {"id": req_id, "type": "result", "data": {"cached": True}}

            elif method == "cache_remove":
                key = params.get("key") or ""
                try:
                    self.apply_cache_remove(key)
                except RuntimeError as e:
                    return {
                        "id": req_id,
                        "type": "error",
                        "data": {"code": 400, "message": str(e)},
                    }
                return {"id": req_id, "type": "result", "data": {"removed": True}}

            elif method == "ass_get":
                prov = self._config._provider_config.get("default", {})
                return {
                    "id": req_id,
                    "type": "result",
                    "data": {
                        "karaoke": prov.get("karaoke"),
                        "line_mode": prov.get("line_mode"),
                        "secondary": prov.get("secondary"),
                    },
                }

            elif method == "ass_set":
                key = params.get("key", "")
                raw_value = params.get("value", "")
                if not key or not raw_value:
                    return {
                        "id": req_id,
                        "type": "error",
                        "data": {"code": 400, "message": "key and value required"},
                    }
                try:
                    key, parsed = await self.apply_ass_config(key, raw_value)
                except ValueError as e:
                    return {
                        "id": req_id,
                        "type": "error",
                        "data": {"code": 400, "message": str(e)},
                    }
                return {
                    "id": req_id,
                    "type": "result",
                    "data": {"key": key, "value": parsed},
                }

            else:
                return {
                    "id": req_id,
                    "type": "error",
                    "data": {
                        "code": -2,
                        "message": f"unknown method: {method}",
                    },
                }

        except Exception as e:
            logger.exception("error executing %s", method)
            return {
                "id": req_id,
                "type": "error",
                "data": {"code": -1, "message": str(e)},
            }

    # ── IPC connection handler ────────────────────────────────────

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        req = None
        try:
            data = await asyncio.wait_for(reader.readline(), timeout=30)
            if not data:
                return
            req = json.loads(data.decode())
            resp = await self._execute(req)
            writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode())
            await writer.drain()
        except json.JSONDecodeError:
            err = {
                "id": None,
                "type": "error",
                "data": {"code": 400, "message": "invalid json"},
            }
            writer.write((json.dumps(err) + "\n").encode())
            await writer.drain()
        except TimeoutError:
            pass
        except Exception as e:
            req_id = req.get("id") if isinstance(req, dict) else None
            err = {
                "id": req_id,
                "type": "error",
                "data": {"code": -1, "message": str(e)},
            }
            writer.write((json.dumps(err) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: S110 - ignore close failure
                pass

    # ── player poller ─────────────────────────────────────────────

    async def _player_poller(self):
        while True:
            try:
                self._refresh_sources()
                self._sync()
            except Exception as e:
                logger.debug("player poll error: %s", e)
            await asyncio.sleep(1)

    # ── Run ───────────────────────────────────────────────────────

    async def run(self):
        self.start_overlay()

        if self._config.overlay.target_fps > 0:
            self.ctrl.set_status(target_fps=self._config.overlay.target_fps)
            logger.info(
                "target FPS set from config: %d", self._config.overlay.target_fps
            )

        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=self.socket_path,
        )
        os.chmod(self.socket_path, 0o666)
        logger.info("ipc server listening on %s", self.socket_path)

        # Seed the menu cache so the first right-click opens with content (the
        # core renders the cached items synchronously, then Python refreshes).
        try:
            await self.refresh_menu()
        except Exception:
            logger.exception("initial menu refresh failed")

        self._refresh_sources()
        self._sync()
        poller_task = asyncio.create_task(self._player_poller())
        key_poller_task = asyncio.create_task(self.key_manager.poller())
        ui_poller_task = asyncio.create_task(self.ui_manager.poller())

        try:
            await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            poller_task.cancel()
            key_poller_task.cancel()
            ui_poller_task.cancel()
            self._server.close()
            await self._server.wait_closed()

    def cleanup(self):
        for source_id in list(self._sources):
            self._detach_source(source_id)
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError, OSError:
            pass
        self.ctrl.stop()
        self.ctrl.join()
        logger.info("cleanup done")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    import argparse

    parser = argparse.ArgumentParser(description="layrics - desktop lyrics overlay")
    parser.add_argument("--socket", "-s", help="IPC socket path")
    args = parser.parse_args()

    _acquire_instance_lock()

    app = LayricsApp(socket_path=args.socket or "")

    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("shutting down...")
    finally:
        app.cleanup()


if __name__ == "__main__":
    main()
