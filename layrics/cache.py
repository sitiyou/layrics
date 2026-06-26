from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional

from .config import _CONFIG_DIR
from .mpris import TrackMeta


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
    lyrics_title: str
    lyrics_artists: str
    created_at: int
    updated_at: int


class SongCache:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = os.path.join(_CONFIG_DIR, "song_cache.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS song_cache ("
            "  cache_key TEXT PRIMARY KEY,"
            "  lyrics_song_id TEXT NOT NULL,"
            "  lyrics_source TEXT NOT NULL,"
            "  lyrics_title TEXT,"
            "  lyrics_artists TEXT,"
            "  created_at INTEGER NOT NULL,"
            "  updated_at INTEGER NOT NULL"
            ")"
        )
        self._conn.commit()

    def get(self, key: str) -> Optional[CacheEntry]:
        row = self._conn.execute(
            "SELECT cache_key, lyrics_song_id, lyrics_source, "
            "lyrics_title, lyrics_artists, created_at, updated_at "
            "FROM song_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return CacheEntry(*row)

    def set(
        self, key: str, song_id: str, source: str, title: str = "", artists: str = ""
    ):
        now = int(time.time())
        self._conn.execute(
            "INSERT OR REPLACE INTO song_cache "
            "(cache_key, lyrics_song_id, lyrics_source, "
            "lyrics_title, lyrics_artists, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, "
            "COALESCE((SELECT created_at FROM song_cache WHERE cache_key = ?), ?), "
            "?)",
            (key, song_id, source, title, artists, key, now, now),
        )
        self._conn.commit()

    def set_if_missing(
        self, key: str, song_id: str, source: str, title: str = "", artists: str = ""
    ) -> bool:
        now = int(time.time())
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO song_cache "
            "(cache_key, lyrics_song_id, lyrics_source, "
            "lyrics_title, lyrics_artists, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key, song_id, source, title, artists, now, now),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def remove(self, key: str):
        self._conn.execute("DELETE FROM song_cache WHERE cache_key = ?", (key,))
        self._conn.commit()

    def list_all(self) -> list[CacheEntry]:
        rows = self._conn.execute(
            "SELECT cache_key, lyrics_song_id, lyrics_source, "
            "lyrics_title, lyrics_artists, created_at, updated_at "
            "FROM song_cache ORDER BY updated_at DESC"
        ).fetchall()
        return [CacheEntry(*row) for row in rows]
