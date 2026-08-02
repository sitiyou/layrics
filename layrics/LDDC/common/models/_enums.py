# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only

from enum import Enum

__all__ = ["Language", "LyricsType", "SearchType", "Source"]


class SearchType(Enum):
    SONG = 0
    ALBUM = 1
    SONGLIST = 2
    ARTIST = 3
    LYRICS = 7


class LyricsType(Enum):
    PlainText = 0
    VERBATIM = 1
    LINEBYLINE = 2


class Source(Enum):
    MULTI = 0
    QM = 1
    KG = 2
    NE = 3
    LRCLIB = 4
    Local = 100

    def __str__(self) -> str:
        return self.name

    @property
    def supported_search_types(self) -> tuple[SearchType, ...]:
        match self:
            case Source.QM | Source.KG | Source.NE | Source.LRCLIB:
                return (SearchType.SONG,)
            case _:
                return ()


class Language(Enum):
    INSTRUMENTAL = 0
    OTHER = 1

    CHINESE = 2
    ENGLISH = 3
    JAPANESE = 4
    KOREAN = 5
