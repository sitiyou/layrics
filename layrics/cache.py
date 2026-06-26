from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Optional

import appdirs
from LDDC.common.models import Artist, SongInfo, Source

from .mpris import TrackMeta

_DATA_DIR = appdirs.user_data_dir("layrics")


def make_cache_key(meta: TrackMeta) -> str:
    title = meta.title or ""
    artists = "|".join(meta.artists) if meta.artists else ""
    album = meta.album or ""
    duration = str(meta.length // 1000000) if meta.length else "0"
    return f"{title}|{artists}|{album}|{duration}"


@dataclass
class CacheEntry:
    cache_key: str
    lyrics_song_id: str
    lyrics_source: str
    created_at: int
    updated_at: int


class SongCache:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = os.path.join(_DATA_DIR, "song_cache.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS song_cache ("
            "  cache_key TEXT PRIMARY KEY,"
            "  lyrics_song_id TEXT NOT NULL,"
            "  lyrics_source TEXT NOT NULL,"
            "  created_at INTEGER NOT NULL,"
            "  updated_at INTEGER NOT NULL"
            ")"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS song_info_cache ("
            "  song_id TEXT NOT NULL,"
            "  source TEXT NOT NULL,"
            "  title TEXT DEFAULT '',"
            "  artists TEXT DEFAULT '',"
            "  album TEXT DEFAULT '',"
            "  duration INTEGER,"
            "  updated_at INTEGER NOT NULL,"
            "  PRIMARY KEY (song_id, source)"
            ")"
        )
        self._conn.commit()

    # ── song_cache (TrackMeta → lyrics_song_id) ──────────────────

    def get(self, key: str) -> Optional[CacheEntry]:
        row = self._conn.execute(
            "SELECT cache_key, lyrics_song_id, lyrics_source, "
            "created_at, updated_at "
            "FROM song_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return CacheEntry(*row)

    def set(self, key: str, song_id: str, source: str):
        now = int(time.time())
        self._conn.execute(
            "INSERT OR REPLACE INTO song_cache "
            "(cache_key, lyrics_song_id, lyrics_source, created_at, updated_at) "
            "VALUES (?, ?, ?, "
            "COALESCE((SELECT created_at FROM song_cache WHERE cache_key = ?), ?), "
            "?)",
            (key, song_id, source, key, now, now),
        )
        self._conn.commit()

    def set_if_missing(self, key: str, song_id: str, source: str) -> bool:
        now = int(time.time())
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO song_cache "
            "(cache_key, lyrics_song_id, lyrics_source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (key, song_id, source, now, now),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def remove(self, key: str):
        self._conn.execute("DELETE FROM song_cache WHERE cache_key = ?", (key,))
        self._conn.commit()

    def list_all(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT sc.cache_key, sc.lyrics_song_id, sc.lyrics_source, "
            "sc.updated_at, "
            "sic.title, sic.artists, sic.album, sic.duration "
            "FROM song_cache sc "
            "LEFT JOIN song_info_cache sic ON "
            "sc.lyrics_song_id = sic.song_id AND sc.lyrics_source = sic.source "
            "ORDER BY sc.updated_at DESC"
        ).fetchall()
        return [
            {
                "key": row[0],
                "song_id": row[2] + row[1],
                "lyrics_title": row[4] or "",
                "lyrics_artists": row[5] or "",
                "lyrics_album": row[6] or "",
                "lyrics_duration": row[7],
                "updated_at": row[3],
            }
            for row in rows
        ]

    # ── song_info_cache (song_id → SongInfo) ─────────────────────

    def store_search_results(self, results: list[dict[str, Any]]):
        now = int(time.time())
        self._conn.executemany(
            "INSERT OR REPLACE INTO song_info_cache "
            "(song_id, source, title, artists, album, duration, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    r["raw_id"],
                    r["source"],
                    r.get("name", ""),
                    "|".join(r.get("artists", [])),
                    r.get("album", ""),
                    r.get("duration"),
                    now,
                )
                for r in results
            ],
        )
        self._conn.commit()

    def lookup_song_info(self, song_id: str, source: str) -> Optional[SongInfo]:
        row = self._conn.execute(
            "SELECT title, artists, album, duration "
            "FROM song_info_cache WHERE song_id = ? AND source = ?",
            (song_id, source),
        ).fetchone()
        if row is None:
            return None
        return SongInfo(
            source=Source[source],
            id=song_id,
            title=row[0] or None,
            artist=Artist(row[1].split("|")) if row[1] else None,
            album=row[2] or None,
            duration=row[3],
        )
