# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only

from typing import ParamSpec, TypeVar

from ._enums import Language, LyricsType, SearchType, Source
from ._info import APIResultList, Artist, LyricInfo, SearchInfo, SongInfo
from ._lyrics import (
    FSLyrics,
    FSLyricsData,
    FSLyricsLine,
    FSLyricsWord,
    FSMultiLyricsData,
    Lyrics,
    LyricsBase,
    LyricsData,
    LyricsLine,
    LyricsWord,
    MultiLyricsData,
    get_full_timestamps_lyrics_data,
)

__all__ = [
    "APIResultList",
    "Artist",
    "FSLyrics",
    "FSLyricsData",
    "FSLyricsLine",
    "FSLyricsWord",
    "FSMultiLyricsData",
    "Language",
    "LyricInfo",
    "Lyrics",
    "LyricsBase",
    "LyricsData",
    "LyricsLine",
    "LyricsType",
    "LyricsWord",
    "MultiLyricsData",
    "P",
    "SearchInfo",
    "SearchType",
    "SongInfo",
    "Source",
    "T",
    "get_full_timestamps_lyrics_data",
]


P = ParamSpec("P")
T = TypeVar("T")
