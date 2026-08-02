# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only
"""LDDC 的歌词提供 api

模块中的函数都是被缓存的,而 LyricsAPI 中的函数则不是
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Lock
from types import MappingProxyType
from typing import TYPE_CHECKING

from layrics.LDDC.common.data.cache import cached_call_with_status
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
        self.init_lock = Lock()
        self.inited = False

    def init(self) -> None:
        with self.init_lock:
            if self.inited:
                return
            from .kg import KGAPI
            from .lrclib import LrclibAPI
            from .ne import NEAPI
            from .qm import QMAPI

            self.cloud_apis: dict[Source, CloudAPI] = {
                KGAPI.source: KGAPI(),
                NEAPI.source: NEAPI(),
                QMAPI.source: QMAPI(),
                LrclibAPI.source: LrclibAPI(),
            }
            self.inited = True

    def timeout_retry(self, func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        from httpx import TimeoutException  # 加快启动速度

        for i in range(3):
            try:
                return func(*args, **kwargs)
            except TimeoutException:
                if i == 2:
                    raise
                continue
            except Exception:
                logger.exception("请求歌词Api时遇到错误")
                raise

        msg = "Unknown error"
        raise LDDCError(msg)

    def search(
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
            self.init()
        if sources is None:
            src_list = list(self.cloud_apis)
        elif isinstance(sources, Source):
            src_list = [sources]
        else:
            src_list = list(sources)

        keyword = " ".join(p for p in (title, artist, album) if p)

        def _search_one(src: Source) -> tuple[Source, APIResultList[SongInfo] | None]:
            try:
                result = self.timeout_retry(
                    self.cloud_apis[src].search, keyword, SearchType.SONG, page
                )
                return src, result if len(result) > 0 else None
            except Exception as e:  # noqa: BLE001 - isolate per-source failures
                logger.error("search: source %s failed: %s", src, e)
                return src, None

        per_source: dict[Source, APIResultList[SongInfo]] = {}
        with ThreadPoolExecutor(max_workers=len(src_list)) as executor:
            for src, result in executor.map(_search_one, src_list):
                if result is not None:
                    per_source[src] = result

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

    def get_lyrics(self, info: SongInfo | LyricInfo | None = None) -> Lyrics:
        """获取歌词

        Args:
            info (SongInfo | LyricInfo): 歌曲信息或歌词信息

        Returns:
            Lyrics: 歌词

        """
        if not self.inited:
            self.init()
        if not info:
            msg = "info cannot be None"
            raise ValueError(msg)
        lyrics = self.timeout_retry(self.cloud_apis[info.source].get_lyrics, info)
        if not lyrics:
            msg = "没有找到歌词"
            raise LyricsNotFoundError(msg, info)
        return lyrics


lyrics_api = LyricsAPI()


def search(
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
    result, cached = cached_call_with_status(
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


def get_lyrics(info: SongInfo | LyricInfo | None = None) -> Lyrics:
    """获取歌词

    Args:
        info (SongInfo | LyricInfo): 歌曲信息或歌词信息

    Returns:
        Lyrics: 歌词

    """
    result, cached = cached_call_with_status(lyrics_api.get_lyrics, {"expire": 14400}, info)
    result.info = replace(result.info, cached=cached)
    return result
