from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import Any

from LDDC.common.models import Lyrics as _LDCLyrics, LyricsType, SearchType, SongInfo, Source
from LDDC.core.api.lyrics import get_lyrics as _lddc_get_lyrics
from LDDC.core.api.lyrics import search as _lddc_search

from .assprovider import AssProvider, DefaultProvider, Lyrics, match_provider
from .config import get_config


logger = logging.getLogger("layrics.lyrics")


_SOURCE_PREFIXES: list[tuple[str, Source]] | None = None


def _init_prefixes() -> list[tuple[str, Source]]:
    global _SOURCE_PREFIXES
    if _SOURCE_PREFIXES is None:
        cfg = get_config()
        _SOURCE_PREFIXES = sorted(
            [(s.name, s) for s in cfg.search.sources],
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
    cfg = get_config()
    search_sources = cfg.search.sources
    per_source = cfg.search.result_count
    logger.debug("search: %s  sources=%s  per_source=%d", keyword, [s.name for s in search_sources], per_source)

    def _items(src: Source) -> list[dict[str, Any]]:
        try:
            results = _lddc_search(src, keyword, SearchType.SONG, page=1)
        except Exception:
            return []
        logger.debug("search: %s  from %s -> %d raw results", keyword, src.name, len(results))
        items = []
        for s in results[:per_source]:
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
    logger.debug("search: total %d interleaved candidates", sum(len(r) for r in all_results))
    interleaved = []
    max_len = max(len(r) for r in all_results)
    for i in range(max_len):
        for src_results in all_results:
            if i < len(src_results):
                interleaved.append(src_results[i])
                if len(interleaved) >= limit:
                    logger.debug("search: returning %d results (limit=%d)", len(interleaved), limit)
                    return interleaved
    logger.debug("search: returning %d results", len(interleaved))
    return interleaved


def _resolve_song_info(song_info: SongInfo) -> SongInfo:
    """SongInfo 缺少 title/album/duration 时先用 ID 搜索补齐。"""
    if song_info.title and song_info.duration is not None and song_info.album:
        return song_info

    logger.debug("resolve: %s/%s  searching by ID", song_info.source.name, song_info.id)
    results = _lddc_search(  # noqa: SLF001
        song_info.source, song_info.id or "", SearchType.SONG, page=1
    )
    for s in results:
        if s.id == song_info.id:
            logger.debug("resolve: %s/%s -> title=%s  artist=%s  dur=%s",
                         song_info.source.name, song_info.id, s.title, s.artist, s.duration)
            return SongInfo(
                source=song_info.source,
                id=s.id,
                title=s.title,
                artist=s.artist,
                album=s.album,
                duration=s.duration,
            )

    logger.debug("resolve: %s/%s  no match in %d results, using fallback",
                 song_info.source.name, song_info.id, len(results))
    return SongInfo(
        source=song_info.source,
        id=song_info.id,
        title=song_info.title or "",
        artist=song_info.artist,
        album=song_info.album or "",
        duration=song_info.duration or 0,
    )


def _postprocess_aegisub(ass: str, cli_path: str, automation: str = "kara-templater.lua",
                         header_overrides: dict[str, str | int] | None = None) -> str:
    from .karaoke.header import render_karaoke_header

    karaoke_header = render_karaoke_header(**(header_overrides or {}))

    dialog_lines = []
    for line in ass.splitlines():
        if line.startswith("Dialogue:"):
            line = line.replace(",PrimaryLeft,", ",K1,")
            line = line.replace(",PrimaryRight,", ",K2,")
            line = line.replace(",Primary,", ",K1,")
            line = line.replace(",Secondary,", ",K2,")
            dialog_lines.append(line)

    inter_ass = karaoke_header.rstrip("\n") + "\n" + "\n".join(dialog_lines) + "\n"

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".ass", mode="w", delete=False, prefix="layrics_aegisub_"
        ) as f:
            f.write(inter_ass)
            tmp_path = f.name

        subprocess.run(
            [cli_path, "--automation", automation, tmp_path, tmp_path, "Apply karaoke template"],
            check=True, capture_output=True, text=True,
        )
        with open(tmp_path) as f:
            result = f.read()
    except Exception as e:
        logger.warning("aegisub-cli failed: %s, using intermediate ass", e)
        result = inter_ass
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return result


def fetch_lyrics(
    song_info: SongInfo,
    player_name: str = "",
) -> str:
    song_info = _resolve_song_info(song_info)
    logger.debug("fetch: %s/%s  title=%s  artist=%s  dur=%s",
                 song_info.source.name, song_info.id,
                 song_info.title, song_info.artist, song_info.duration)
    lddc_lyrics = _lddc_get_lyrics(song_info)
    if not lddc_lyrics:
        msg = f"no lyrics returned for {song_info.title}"
        logger.debug("fetch: %s/%s  %s", song_info.source.name, song_info.id, msg)
        raise RuntimeError(msg)

    logger.debug("fetch: %s/%s  got %d lyric lines",
                 song_info.source.name, song_info.id, len(lddc_lyrics))

    provider_cls = match_provider(player_name, lddc_lyrics) or DefaultProvider
    cfg = get_config()
    lyrics = Lyrics(
        lddc_lyrics,
        fonts=cfg.fonts.mapping,
        primary_priority=cfg.lyrics.primary,
        secondary_priority=cfg.lyrics.secondary,
        primary_override=cfg.get_style_config("primary"),
        secondary_override=cfg.get_style_config("secondary"),
    )
    provider: AssProvider = provider_cls(
        config=cfg.get_provider_config(getattr(provider_cls, "PROVIDER", "")),  # type: ignore[call-arg]
    )
    dur_ms = song_info.duration
    ass = provider.generate(lyrics, duration_ms=dur_ms)

    if provider_cls is DefaultProvider:
        provider_cfg = cfg.get_provider_config("default")
        if provider_cfg.get("aegisub_karaoke") and provider_cfg.get("line_mode") == "double":
            orig_type = lyrics.types.get(lyrics.primary_track)
            if provider_cfg.get("karaoke", True) and orig_type == LyricsType.VERBATIM:
                cli = provider_cfg.get("aegisub_cli", "") or "aegisub-cli"
                automation = provider_cfg.get("aegisub_automation", "") or "kara-templater.lua"

                primary_style = lyrics.primary_style
                overrides: dict[str, str | int] = {
                    "FONTNAME": primary_style.font_name,
                }
                pc = primary_style.primary_colour
                if pc.startswith("&H"):
                    pc = pc[2:]
                overrides["OVERLAY_COLOR"] = pc[-6:]

                ass = _postprocess_aegisub(ass, cli, automation, header_overrides=overrides)
            else:
                logger.info(
                    "aegisub_karaoke: lyrics lack word timing (type=%s), skipping",
                    orig_type,
                )

    return ass
