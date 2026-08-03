# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only
"""LDDC lyrics provider API

Functions in this module are cached, while those in ``LyricsAPI`` are not.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING

from layrics.LDDC.common.data.cache import async_cached_call_with_status
from layrics.LDDC.common.exceptions import LDDCError, LyricsNotFoundError
from layrics.LDDC.common.logger import logger
from layrics.LDDC.common.models import (
    APIResultList,
    LyricInfo,
    Lyrics,
    P,
    SearchInfo,
    SearchType,
    SongInfo,
    Source,
    T,
)

if TYPE_CHECKING:
    from .models import CloudAPI


class LyricsAPI:
    def __init__(self) -> None:
        self.init_lock = asyncio.Lock()
        self.inited = False

    async def init(self) -> None:
        async with self.init_lock:
            if self.inited:
                return
            from .kg import KGAPI
            from .lrclib import LrclibAPI
            from .ne import NEAPI
            from .qm import QMAPI

            apis = [KGAPI(), NEAPI(), QMAPI(), LrclibAPI()]
            for api in apis:
                await api.init()
            self.cloud_apis: dict[Source, CloudAPI] = {
                api.source: api for api in apis
            }
            self.inited = True

    async def timeout_retry(self, func: Callable[P, Awaitable[T]],
                            *args: P.args, **kwargs: P.kwargs) -> T:
        from httpx import TimeoutException  # import here to speed up startup

        for i in range(3):
            try:
                return await func(*args, **kwargs)
            except TimeoutException:
                if i == 2:
                    raise
                continue
            except LyricsNotFoundError:
                # Expected outcome (no lyrics available); no retry, handled by the caller.
                raise
            except Exception:
                logger.exception("lyrics API request failed")
                raise

        msg = "Unknown error"
        raise LDDCError(msg)

    async def search(
        self,
        *,
        title: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        sources: Source | list[Source] | None = None,
        page: int = 1,
    ) -> APIResultList[SongInfo]:
        """Search songs by explicit keyword fields across the given sources.

        At least one of ``title``/``artist``/``album`` must be provided. When
        ``sources`` is None all cloud sources are searched. Results from each
        source are interleaved in ``Source`` enum order.

        Args:
            title (str | None): song title keyword.
            artist (str | None): artist keyword.
            album (str | None): album keyword.
            sources (Source | list[Source] | None): sources to search, default all.
            page (int, optional): page number. Defaults to 1.

        Returns:
            APIResultList[SongInfo]: interleaved search results.
        """
        if not (title or artist or album):
            msg = "at least one of title/artist/album is required"
            raise ValueError(msg)
        if not self.inited:
            await self.init()
        if sources is None:
            src_list = list(self.cloud_apis)
        elif isinstance(sources, Source):
            src_list = [sources]
        else:
            src_list = list(sources)

        keyword = " ".join(p for p in (title, artist, album) if p)

        async def _search_one(src: Source) -> tuple[Source, APIResultList[SongInfo] | None]:
            try:
                result = await self.timeout_retry(
                    self.cloud_apis[src].search, keyword, SearchType.SONG, page
                )
                return src, result if len(result) > 0 else None
            except Exception as e:
                logger.error("search: source %s failed: %s", src, e)
                return src, None

        results = await asyncio.gather(*(_search_one(src) for src in src_list))
        per_source: dict[Source, APIResultList[SongInfo]] = {
            src: r for src, r in results if r is not None
        }

        items = [item for r in per_source.values() for item in r]
        ranges = MappingProxyType(
            {src: r.source_ranges[src] for src, r in per_source.items()}
        )
        info = SearchInfo(
            source=src_list,
            keyword=keyword,
            search_type=SearchType.SONG,
            page=page,
        )
        return APIResultList(items, info, ranges)

    async def get_lyrics(self, info: SongInfo | LyricInfo | None = None) -> Lyrics:
        """Get lyrics for the given song info.

        Args:
            info (SongInfo | LyricInfo): song info or lyric info

        Returns:
            Lyrics: the lyrics

        """
        if not self.inited:
            await self.init()
        if not info:
            msg = "info cannot be None"
            raise ValueError(msg)
        lyrics = await self.timeout_retry(self.cloud_apis[info.source].get_lyrics, info)
        if not lyrics:
            msg = "no lyrics found"
            raise LyricsNotFoundError(msg, info)
        return lyrics


lyrics_api = LyricsAPI()


async def search(
    *,
    title: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    sources: Source | list[Source] | None = None,
    page: int = 1,
) -> APIResultList[SongInfo]:
    """Search songs by explicit keyword fields across sources (cached 4h).

    See :meth:`LyricsAPI.search` for parameter semantics.
    """
    src_key = tuple(sources) if isinstance(sources, list) else sources
    result, cached = await async_cached_call_with_status(
        lyrics_api.search,
        {"expire": 14400},
        title=title,
        artist=artist,
        album=album,
        sources=src_key,
        page=page,
    )
    result.cached = cached
    return result


async def get_lyrics(info: SongInfo | LyricInfo | None = None) -> Lyrics:
    """Get lyrics for the given song info (cached 4h).

    Args:
        info (SongInfo | LyricInfo): song info or lyric info

    Returns:
        Lyrics: the lyrics

    """
    result, cached = await async_cached_call_with_status(lyrics_api.get_lyrics, {"expire": 14400}, info)
    result.info = replace(result.info, cached=cached)
    return result
