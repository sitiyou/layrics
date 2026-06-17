#!/usr/bin/env python3
"""
layrics - ASS subtitle overlay on wlr-layer-shell
Provides JSON-based IPC control over a Unix domain socket.

Protocol:
  Request:  {"id": <int>, "method": "<str>", "params": {<opt>}}
  Response: {"id": <int>, "type": "result", "data": <any>}
  Error:    {"id": <int>, "type": "error", "data": {"code": <int>, "message": "<str>"}}

Methods:
  list_players                         -> [{bus_name, identity}]
  select_player  {name}                -> {selected}
  search_songs   {keyword, limit?}     -> [{id (composite), name, artists, album, source}]
  fetch_lyrics   {song_id?, sync?}     -> {ass}  (song_id e.g. "QM248672467", omit for current track)
   load_ass       {path}                -> {loaded}
   hide                                 -> {hidden}
   unhide                               -> {hidden}
   lock                                 -> {locked}
   unlock                               -> {locked}
   set_fps      {fps}                   -> {target_fps}
   stop                                 -> {status}
   start                                -> {status}
   get_status                           -> {mpris_player, overlay}
   cache_list                           -> [{key, song_id, lyrics_title, lyrics_artists, updated_at}]
   cache_set     {song_id, key?}       -> {cached}  (key defaults to current track)
   cache_remove  {key?}                -> {removed}  (key defaults to current track)
"""

import sys
import os
import fcntl
import json
import asyncio
import logging
import time
from dataclasses import asdict
from typing import Any, Optional

from LDDC.common.exceptions import LyricsNotFoundError
from LDDC.common.models import Artist, SongInfo, Source

from ._layrics import ApplicationController
from .config import get_config
from .cache import SongCache, make_cache_key
from .lyricsource import search_songs as _search_songs, fetch_lyrics as _fetch_lyrics, parse_composite_id, _resolve_song_info
from .matching import match_song, clean_search_keyword
from .mpris import MPRISPlayerFinder, MprisSignalMonitor, TrackMeta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("layrics")

# LAYRICS_DEBUG=lyrics,match  → 模块级 DEBUG；=core  → C++ DEBUG
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


class LayricsApp:
    """Orchestrates overlay, MPRIS monitoring, NetEase API, and IPC."""

    def __init__(self, socket_path: str = ""):
        self.ctrl = ApplicationController()
        self._config = get_config()
        self.mpris_finder = MPRISPlayerFinder()
        self._mpris_player: Any = None
        self._last_track: Optional[TrackMeta] = None

        self.socket_path = (
            socket_path
            or os.environ.get("LAYRICS_SOCK")
            or os.path.join(
                os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "layrics.sock"
            )
        )

        self._server: Optional[asyncio.AbstractServer] = None
        self._paused = False
        self._last_status: Optional[str] = None
        self._last_position_us: int = 0
        self._signal_monitor: Optional[MprisSignalMonitor] = None
        self._signal_reader: Optional[asyncio.AbstractEventLoop] = None
        self._fetch_gen: int = 0

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

    # ── auto-fetch ────────────────────────────────────────────────

    async def _fetch_ass_for_track(self, meta: TrackMeta) -> str:
        keyword = (meta.title or "")
        if meta.artists:
            keyword += " " + " ".join(meta.artists)
        keyword = clean_search_keyword(keyword.strip())
        if not keyword:
            raise RuntimeError(f"empty keyword for track {meta.unique_song_id}")

        loop = asyncio.get_event_loop()
        cache = SongCache()
        key = make_cache_key(meta)
        cached = cache.get(key)
        if cached is not None:
            logger.info("fetch: cache hit %s -> %s%s", keyword,
                         cached.lyrics_source, cached.lyrics_song_id)
            try:
                src = Source[cached.lyrics_source]
            except KeyError:
                logger.warning("fetch: invalid source in cache %s", cached.lyrics_source)
                cache.remove(key)
            else:
                song_info = SongInfo(source=src, id=cached.lyrics_song_id)
                try:
                    ass = await loop.run_in_executor(None, lambda: _fetch_lyrics(song_info))
                    logger.info("fetch: cache hit %s (%d bytes)", keyword, len(ass))
                    return ass
                except Exception:
                    logger.warning("fetch: stale cache entry, removing: %s", key)
                    cache.remove(key)

        logger.info("fetch: searching %s", keyword)
        results = await loop.run_in_executor(
            None, lambda: _search_songs(keyword, 20)
        )
        if not results:
            raise RuntimeError(f"no search results for {keyword!r}")

        matched = match_song(meta, results)
        if not matched:
            logger.info("fetch: no match for %s in %d candidates", keyword, len(results))
            raise RuntimeError(f"no match found for {keyword!r}")

        src, raw_id = parse_composite_id(matched["id"])
        song_info = SongInfo(
            source=src,
            id=raw_id,
            title=matched["name"],
            artist=Artist(matched.get("artists", [])),
            album=matched.get("album"),
            duration=matched.get("duration"),
        )
        ass = await loop.run_in_executor(None, lambda: _fetch_lyrics(song_info))
        logger.info("fetch: %s -> %s (%d bytes)", keyword, matched["id"], len(ass))

        cache.set_if_missing(
            key, raw_id, src.name,
            matched.get("name", ""),
            "|".join(matched.get("artists", [])),
        )

        return ass

    async def _auto_fetch_lyrics(self, meta: TrackMeta, gen: int) -> None:
        try:
            ass_content = await self._fetch_ass_for_track(meta)
        except (RuntimeError, LyricsNotFoundError, json.JSONDecodeError) as e:
            logger.info("auto-fetch: %s — hiding overlay", e)
            self.ctrl.set_hidden(True)
            return
        else:
            if self._fetch_gen != gen:
                return
            self.ctrl.set_ass_input(ass_content)

        if self._fetch_gen != gen:
            return
        self.ctrl.set_hidden(False)
        if self._paused:
            self.ctrl.set_paused(True)
        else:
            self.ctrl.set_paused(False)
            now_ms = int(time.monotonic() * 1000)
            try:
                pos = self._mpris_player.get_position()
                self.ctrl.set_start_time(now_ms - pos // 1000)
            except Exception:
                pass

    # ── MPRIS ─────────────────────────────────────────────────────

    def list_players(self):
        return [(p.bus_name, p.get_identity()) for p in self.mpris_finder.find_all_players()]

    def select_mpris_player(self, name: str, match_by: str = "bus_name") -> bool:
        for p in self.mpris_finder.find_all_players():
            match = False
            if match_by == "bus_name":
                match = p.bus_name == name
            elif match_by == "identity":
                match = p.get_identity() == name
            elif match_by == "both":
                match = p.bus_name == name or p.get_identity() == name
            if match:
                self._mpris_player = p
                self._last_track = None
                self._start_signal_monitor()
                logger.info("selected mpris player: %s", p.get_identity())
                return True
        logger.warning("mpris player not found: %s", name)
        return False

    def _auto_select_player(self) -> bool:
        players = self.mpris_finder.find_all_players()
        if self._config.exclude_players:
            players = [
                p for p in players
                if not any(
                    pat.search(p.bus_name) or pat.search(p.get_identity())
                    for pat in self._config.exclude_players
                )
            ]
        elif self._config.include_players:
            players = [
                p for p in players
                if any(
                    pat.search(p.bus_name) or pat.search(p.get_identity())
                    for pat in self._config.include_players
                )
            ]
        if not players:
            return False
        for p in players:
            try:
                if p.get_playback_status() == "Playing":
                    self._mpris_player = p
                    self._last_track = None
                    logger.info("auto-selected player: %s", p.get_identity())
                    self._start_signal_monitor()
                    return True
            except Exception:
                continue
        p = players[0]
        self._mpris_player = p
        self._last_track = None
        logger.info("auto-selected player: %s", p.get_identity())
        self._start_signal_monitor()
        return True

    def _start_signal_monitor(self):
        if self._signal_monitor:
            self._signal_monitor.stop()
            self._signal_monitor = None
        if not self._mpris_player:
            return
        self._signal_monitor = MprisSignalMonitor(self._mpris_player.bus_name)
        self._signal_monitor.start()
        loop = asyncio.get_event_loop()
        loop.add_reader(self._signal_monitor.fileno(), self._on_mpris_signal)

    def _on_mpris_signal(self):
        assert self._signal_monitor is not None
        for event in self._signal_monitor.read_events():
            typ = event.get("type")
            val = event.get("value")
            if typ == "status":
                if val == "Playing":
                    if not self._paused:
                        continue
                    self._paused = False
                    self.ctrl.set_paused(False)
                    now_ms = int(time.monotonic() * 1000)
                    try:
                        pos = self._mpris_player.get_position()
                        self.ctrl.set_start_time(now_ms - pos // 1000)
                    except Exception:
                        pass
                elif val in ("Paused", "Stopped"):
                    if self._paused:
                        continue
                    self._paused = True
                    self.ctrl.set_paused(True)
            elif typ == "seeked":
                now_ms = int(time.monotonic() * 1000)
                self.ctrl.set_start_time(now_ms - val // 1000)
                self._last_position_us = val
            elif typ == "track":
                self._fetch_gen += 1
                self._last_track = None
                logger.info("signal: track changed: %s", val)
                self.ctrl.set_hidden(True)

    def _stop_signal_monitor(self):
        if self._signal_reader:
            assert self._signal_monitor is not None
            loop = asyncio.get_event_loop()
            loop.remove_reader(self._signal_monitor.fileno())
            self._signal_reader = None
        if self._signal_monitor:
            self._signal_monitor.stop()
            self._signal_monitor = None

    def _mpris_sync(self) -> None:
        if not self._mpris_player:
            return
        try:
            meta = self._mpris_player.get_metadata()
            status = self._mpris_player.get_playback_status()
            pos = self._mpris_player.get_position()
        except Exception as e:
            logger.warning("mpris player disconnected: %s", e)
            self._fetch_gen += 1
            self._mpris_player = None
            self._last_track = None
            self._last_status = None
            self._paused = False
            self._stop_signal_monitor()
            self.ctrl.set_hidden(True)
            return

        cur_id = meta.unique_song_id
        last_id = self._last_track.unique_song_id if self._last_track else None
        track_changed = cur_id != last_id
        if track_changed:
            self._fetch_gen += 1
            gen = self._fetch_gen
            self._last_track = meta
            logger.info("track changed: %s", meta.title or "?")
            self.ctrl.set_hidden(True)
            asyncio.get_event_loop().create_task(self._auto_fetch_lyrics(meta, gen))

        # play / pause
        if status != self._last_status:
            self._last_status = status
            if status == "Playing":
                self._paused = False
                self.ctrl.set_paused(False)
                now_ms = int(time.monotonic() * 1000)
                self.ctrl.set_start_time(now_ms - pos // 1000)
            elif status in ("Paused", "Stopped"):
                self._paused = True
                self.ctrl.set_paused(True)

        # seek detection (position jump)
        if status == "Playing":
            expected = self._last_position_us + 1_000_000
            if abs(pos - expected) > 500_000:
                now_ms = int(time.monotonic() * 1000)
                self.ctrl.set_start_time(now_ms - pos // 1000)

        self._last_position_us = pos

    # ── Lyric search (LDDC) ──────────────────────────────────────

    async def search_songs(self, keyword: str, limit: int = 10):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _search_songs(keyword, limit)
        )

    async def fetch_lyrics(self, song_data: dict) -> str:
        song_info = SongInfo(
            source=Source[song_data["source"]],
            id=song_data["id"],
            title=song_data.get("name"),
            artist=Artist(song_data.get("artists", [])),
            album=song_data.get("album"),
            duration=song_data.get("duration"),
        )
        loop = asyncio.get_event_loop()
        ass_content = await loop.run_in_executor(
            None, lambda: _fetch_lyrics(song_info)
        )
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
                    "data": [
                        {"bus_name": bn, "identity": id_}
                        for bn, id_ in players
                    ],
                }

            elif method == "select_player":
                name = params.get("name", "")
                match_by = params.get("match_by", "bus_name")
                ok = self.select_mpris_player(name, match_by)
                if ok:
                    return {
                        "id": req_id,
                        "type": "result",
                        "data": {"selected": name},
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
                return {"id": req_id, "type": "result", "data": data}

            elif method == "fetch_lyrics":
                song_id = params.get("song_id", "") or ""
                if song_id:
                    src, raw_id = parse_composite_id(song_id)
                    song_data = {
                        "id": raw_id,
                        "source": src.name,
                        "name": params.get("name"),
                        "artists": params.get("artists", []),
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
                    ass_content = await self._fetch_ass_for_track(self._last_track)
                    if params.get("sync", False):
                        self.ctrl.set_ass_input(ass_content)
                    return {"id": req_id, "type": "result", "data": {"ass": ass_content}}
                ass_content = await self.fetch_lyrics(song_data)
                if params.get("sync", False):
                    self.ctrl.set_ass_input(ass_content)
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
                self.ctrl.set_hidden(True)
                return {"id": req_id, "type": "result", "data": {"hidden": True}}

            elif method == "unhide":
                self.ctrl.set_hidden(False)
                self.ctrl.set_paused(self._paused)
                return {"id": req_id, "type": "result", "data": {"hidden": False}}

            elif method == "lock":
                self.ctrl.set_locked(True)
                return {"id": req_id, "type": "result", "data": {"locked": True}}

            elif method == "unlock":
                self.ctrl.set_locked(False)
                return {"id": req_id, "type": "result", "data": {"locked": False}}

            elif method == "set_fps":
                fps = params.get("fps", -1)
                if not isinstance(fps, int) or (fps <= 0 and fps != -1):
                    return {
                        "id": req_id,
                        "type": "error",
                        "data": {"code": 400, "message": "fps must be > 0 or -1 (vsync)"},
                    }
                self.ctrl.set_target_fps(fps)
                self._config.overlay.target_fps = fps
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
                return {
                    "id": req_id,
                    "type": "result",
                    "data": {"status": "started"},
                }

            elif method == "get_status":
                player_info = None
                if self._mpris_player:
                    try:
                        status = self._mpris_player.get_playback_status()
                        pos = self._mpris_player.get_position()
                        player_info = {
                            "identity": self._mpris_player.get_identity(),
                            "bus_name": self._mpris_player.bus_name,
                            "playback_status": status,
                            "position_ms": pos // 1000,
                        }
                        if self._last_track:
                            player_info["track"] = asdict(self._last_track)
                    except Exception:
                        player_info = {"error": "disconnected"}
                overlay = self.ctrl.get_status()
                overlay["position_ms"] = int(time.monotonic() * 1000) - overlay["start_time_ms"]
                return {
                    "id": req_id,
                    "type": "result",
                    "data": {
                        "mpris_player": player_info,
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
                            "key": e.cache_key,
                            "song_id": e.lyrics_source + e.lyrics_song_id,
                            "lyrics_title": e.lyrics_title,
                            "lyrics_artists": e.lyrics_artists,
                            "updated_at": e.updated_at,
                        }
                        for e in entries
                    ],
                }

            elif method == "cache_set":
                song_id = params.get("song_id", "")
                if not song_id:
                    return {
                        "id": req_id,
                        "type": "error",
                        "data": {"code": 400, "message": "song_id required"},
                    }
                key = params.get("key") or ""
                if not key:
                    if not self._last_track:
                        return {
                            "id": req_id,
                            "type": "error",
                            "data": {"code": 400, "message": "no current track"},
                        }
                    key = make_cache_key(self._last_track)

                src, raw_id = parse_composite_id(song_id)
                song_info = SongInfo(source=src, id=raw_id)
                loop = asyncio.get_event_loop()

                resolved = await loop.run_in_executor(
                    None, lambda: _resolve_song_info(song_info),
                )
                ass = await loop.run_in_executor(
                    None, lambda: _fetch_lyrics(resolved),
                )
                cache = SongCache()
                cache.set(
                    key, raw_id, src.name,
                    resolved.title or "",
                    str(resolved.artist) if resolved.artist else "",
                )

                self.ctrl.set_ass_input(ass)
                self.ctrl.set_hidden(False)
                if self._paused:
                    self.ctrl.set_paused(True)
                else:
                    self.ctrl.set_paused(False)
                    now_ms = int(time.monotonic() * 1000)
                    try:
                        pos = self._mpris_player.get_position()
                        self.ctrl.set_start_time(now_ms - pos // 1000)
                    except Exception:
                        pass

                logger.info("cache set: %s -> %s%s", key, src.name, raw_id)
                return {"id": req_id, "type": "result", "data": {"cached": True}}

            elif method == "cache_remove":
                key = params.get("key") or ""
                if not key:
                    if not self._last_track:
                        return {
                            "id": req_id,
                            "type": "error",
                            "data": {"code": 400, "message": "no current track"},
                        }
                    key = make_cache_key(self._last_track)
                cache = SongCache()
                cache.remove(key)
                logger.info("cache removed: %s", key)
                return {"id": req_id, "type": "result", "data": {"removed": True}}

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
        except asyncio.TimeoutError:
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
            except Exception:
                pass

    # ── MPRIS poller ──────────────────────────────────────────────

    async def _mpris_poller(self):
        while True:
            try:
                if not self._mpris_player:
                    self._auto_select_player()
                    if not self._mpris_player:
                        await asyncio.sleep(1)
                        continue
                self._mpris_sync()
            except Exception as e:
                logger.debug("mpris poll error: %s", e)
            await asyncio.sleep(1)

    # ── Run ───────────────────────────────────────────────────────

    async def run(self):
        self.start_overlay()

        if self._config.overlay.target_fps > 0:
            self.ctrl.set_target_fps(self._config.overlay.target_fps)
            logger.info("target FPS set from config: %d", self._config.overlay.target_fps)

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

        self._auto_select_player()
        poller_task = asyncio.create_task(self._mpris_poller())

        try:
            await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            poller_task.cancel()
            self._server.close()
            await self._server.wait_closed()

    def cleanup(self):
        self._stop_signal_monitor()
        try:
            os.unlink(self.socket_path)
        except (FileNotFoundError, OSError):
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

    parser = argparse.ArgumentParser(description="layrics - ASS subtitle overlay")
    parser.add_argument(
        "ass_file", nargs="?", help="ASS subtitle file to load on startup"
    )
    parser.add_argument("--socket", "-s", help="IPC socket path")
    args = parser.parse_args()

    _acquire_instance_lock()

    app = LayricsApp(socket_path=args.socket or "")

    try:
        if args.ass_file:
            app.load_ass(args.ass_file)
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("shutting down...")
    finally:
        app.cleanup()


if __name__ == "__main__":
    main()
