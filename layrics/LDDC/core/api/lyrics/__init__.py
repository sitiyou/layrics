# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only
"""LDDC 的歌词提供 api

模块中的函数都是被缓存的,而 LyricsAPI 中的函数则不是
"""

from collections.abc import Callable
from dataclasses import replace
from threading import Lock
from typing import TYPE_CHECKING

from layrics.LDDC.common.data.cache import cached_call_with_status
from layrics.LDDC.common.exceptions import LDDCError, LyricsNotFoundError
from layrics.LDDC.common.logger import logger
from layrics.LDDC.common.models import (
    APIResultList,
    LyricInfo,
    Lyrics,
    P,
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

    def search(self, source: Source, keyword: str, search_type: SearchType, page: int = 1) -> APIResultList[SongInfo]:
        """从指定歌词源搜索歌曲

        Args:
            source (Source): 歌词源
            keyword (str): 搜索关键词
            search_type (SearchType): 搜索类型
            page (int, optional): 页码. Defaults to 1.

        Returns:
            APIResultList[SongInfo]: 搜索结果

        """
        if not self.inited:
            self.init()
        if source not in self.cloud_apis:
            msg = f"Unsupported source: {source}"
            raise ValueError(msg)
        if search_type not in self.cloud_apis[source].supported_search_types:
            msg = f"Unsupported search type: {search_type}"
            raise ValueError(msg)
        return self.timeout_retry(self.cloud_apis[source].search, keyword, search_type, page)

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


def search(source: Source, keyword: str, search_type: SearchType, page: int = 1) -> APIResultList[SongInfo]:
    """从指定歌词源搜索歌曲

    Args:
        source (Source): 歌词源
        keyword (str): 搜索关键词
        search_type (SearchType): 搜索类型
        page (int, optional): 页码. Defaults to 1.

    Returns:
        APIResultList[SongInfo]: 搜索结果

    """
    result, cached = cached_call_with_status(lyrics_api.search, {"expire": 14400}, source, keyword, search_type, page)
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
