from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from layrics.LDDC.common.models import (
    Lyrics as _LDCLyrics,
)
from layrics.LDDC.common.models import (
    LyricsLine,
    LyricsWord,
    SongInfo,
    Source,
)
from layrics.LDDC.core.api.lyrics import get_lyrics as _lddc_get_lyrics
from layrics.LDDC.core.api.lyrics import search as _lddc_search

from .assprovider import Lyrics, match_provider
from .config import get_config

logger = logging.getLogger("layrics.lyrics")


SOURCE_PREFIXES: list[tuple[str, Source]] | None = None


def _init_prefixes() -> list[tuple[str, Source]]:
    global SOURCE_PREFIXES
    if SOURCE_PREFIXES is None:
        cfg = get_config()
        SOURCE_PREFIXES = sorted(
            [(s.name, s) for s in cfg.search.sources],
            key=lambda x: -len(x[0]),
        )
    return SOURCE_PREFIXES


def parse_composite_id(song_id: str) -> tuple[Source, str]:
    """Parse a composite song id like ``QM248672467`` into ``(Source.QM, "248672467")``."""
    for prefix, src in _init_prefixes():
        if song_id.startswith(prefix):
            return src, song_id[len(prefix) :]
    raise ValueError(f"cannot parse composite song id: {song_id!r}")


async def search_songs(keyword: str, limit: int = 10) -> list[dict[str, Any]]:
    cfg = get_config()
    search_sources = cfg.search.sources
    logger.debug(
        "search: %s  sources=%s",
        keyword,
        [s.name for s in search_sources],
    )

    try:
        results = await _lddc_search(
            title=keyword, sources=search_sources, page=1
        )
    except Exception as e:
        logger.error("search: error %s", e)
        return []
    logger.debug(
        "search: %s  from %s -> %d raw results",
        keyword,
        [s.name for s in search_sources],
        len(results),
    )
    items: list[dict[str, Any]] = []
    for s in list(results)[:limit]:
        if not s.id:
            continue
        d = s.to_dict()
        items.append(
            {
                "source": d["source"],
                "id": d["id"],
                "title": d["title"] or "",
                "artist": d["artist"] or [],
                "album": d["album"] or "",
                "duration": d["duration"],
            }
        )
    logger.debug("search: returning %d results", len(items))
    return items


KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")

S2S_JSON = Path(__file__).resolve().parent / "data" / "simplified_to_shinjitai.json"
S2S_MAP: dict[str, str] | None = None


def _load_s2s_map() -> dict[str, str]:
    global S2S_MAP
    if S2S_MAP is None:
        with open(S2S_JSON, encoding="utf-8") as f:
            S2S_MAP = json.load(f)
    return S2S_MAP


def _convert_japanese(lyrics_data: _LDCLyrics) -> None:
    s2s = _load_s2s_map()
    for data in lyrics_data.values():
        text = "".join(w.text for line in data for w in line.words)
        if not KANA_RE.search(text):
            continue
        for i, line in enumerate(data):
            new_words = [
                LyricsWord(
                    w.start,
                    w.end,
                    "".join(s2s.get(ch, ch) for ch in w.text),
                )
                for w in line.words
            ]
            data[i] = LyricsLine(line.start, line.end, new_words)


async def fetch_lyrics(
    song_info: SongInfo,
    player_name: str = "",
) -> str:
    logger.debug(
        "fetch: %s/%s  title=%s  artist=%s  dur=%s",
        song_info.source.name,
        song_info.id,
        song_info.title,
        song_info.artist,
        song_info.duration,
    )
    lddc_lyrics = await _lddc_get_lyrics(song_info)

    _convert_japanese(lddc_lyrics)

    logger.debug(
        "fetch: %s/%s  got %d lyric lines",
        song_info.source.name,
        song_info.id,
        len(lddc_lyrics),
    )

    cfg = get_config()
    lyrics = Lyrics(
        lddc_lyrics,
        fonts=cfg.fonts.mapping,
        primary_priority=cfg.lyrics.primary,
        secondary_priority=cfg.lyrics.secondary,
        primary_override=cfg.get_style_config("primary"),
        secondary_override=cfg.get_style_config("secondary"),
    )
    lyrics.strip_ruby(track=lyrics.primary_track)
    provider_cls = match_provider(player_name, lyrics, name=cfg.ass_provider)
    if provider_cls is None:
        raise ValueError("no matching ASS provider")
    provider = provider_cls(config=cfg.get_provider_config(provider_cls.PROVIDER))
    logger.debug("fetch: ASS provider=%s", provider_cls.PROVIDER)
    return await asyncio.to_thread(provider.generate, lyrics, song_info.duration)
