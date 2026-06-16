from __future__ import annotations

from typing import Any

from LDDC.common.models import Lyrics as _LDCLyrics, SearchType, SongInfo, Source
from LDDC.core.api.lyrics import get_lyrics as _lddc_get_lyrics
from LDDC.core.api.lyrics import search as _lddc_search

from .assprovider import AssProvider, DefaultProvider, Lyrics, match_provider
from .config import get_config


_SOURCE_PREFIXES: list[tuple[str, Source]] | None = None


def _init_prefixes() -> list[tuple[str, Source]]:
    global _SOURCE_PREFIXES
    if _SOURCE_PREFIXES is None:
        cfg = get_config()
        _SOURCE_PREFIXES = sorted(
            [(s.name, s) for s in cfg.sources],
            key=lambda x: -len(x[0]),
        )
    return _SOURCE_PREFIXES


def parse_composite_id(song_id: str) -> tuple[Source, str]:
    """Parse a composite song id like ``QM248672467`` into ``(Source.QM, "248672467")``."""
    for prefix, src in _init_prefixes():
        if song_id.startswith(prefix):
            return src, song_id[len(prefix):]
    raise ValueError(f"cannot parse composite song id: {song_id!r}")


def search_songs(keyword: str, limit: int = 10) -> list[dict[str, Any]]:
    search_sources = get_config().sources

    def _items(src: Source) -> list[dict[str, Any]]:
        try:
            results = _lddc_search(src, keyword, SearchType.SONG, page=1)
        except Exception:
            return []
        items = []
        for s in results:
            sid = s.id or ""
            if not sid:
                continue
            items.append(
                {
                    "id": f"{src.name}{sid}",
                    "raw_id": sid,
                    "name": s.title or "",
                    "artists": [str(s.artist)] if s.artist else [],
                    "album": s.album or "",
                    "source": src.name,
                    "duration": s.duration,
                }
            )
        return items

    all_results = [_items(src) for src in search_sources]
    interleaved = []
    max_len = max(len(r) for r in all_results)
    for i in range(max_len):
        for src_results in all_results:
            if i < len(src_results):
                interleaved.append(src_results[i])
                if len(interleaved) >= limit:
                    return interleaved
    return interleaved


def _resolve_song_info(song_info: SongInfo) -> SongInfo:
    """SongInfo 缺少 title/album/duration 时先用 ID 搜索补齐。"""
    if song_info.title and song_info.duration is not None and song_info.album:
        return song_info

    results = _lddc_search(  # noqa: SLF001
        song_info.source, song_info.id or "", SearchType.SONG, page=1
    )
    for s in results:
        if s.id == song_info.id:
            return SongInfo(
                source=song_info.source,
                id=s.id,
                title=s.title,
                artist=s.artist,
                album=s.album,
                duration=s.duration,
            )

    # QM 需要 title/album/duration，搜索没有返回的场合用空值兜底
    return SongInfo(
        source=song_info.source,
        id=song_info.id,
        title=song_info.title or "",
        artist=song_info.artist,
        album=song_info.album or "",
        duration=song_info.duration or 0,
    )


def fetch_lyrics(
    song_info: SongInfo,
    player_name: str = "",
) -> str:
    song_info = _resolve_song_info(song_info)
    lddc_lyrics = _lddc_get_lyrics(song_info)
    if not lddc_lyrics:
        msg = f"no lyrics returned for {song_info.title}"
        raise RuntimeError(msg)

    provider_cls = match_provider(player_name, lddc_lyrics) or DefaultProvider
    cfg = get_config()
    lyrics = Lyrics(
        lddc_lyrics,
        fonts=cfg.fonts,
        primary_priority=cfg.lyrics_primary,
        secondary_priority=cfg.lyrics_secondary,
        primary_override=cfg.get_style_config("primary"),
        secondary_override=cfg.get_style_config("secondary"),
    )
    provider: AssProvider = provider_cls(
        config=cfg.get_provider_config(getattr(provider_cls, "PROVIDER", "")),  # type: ignore[call-arg]
    )
    dur_ms = song_info.duration
    ass = provider.generate(lyrics, duration_ms=dur_ms)
    return ass
