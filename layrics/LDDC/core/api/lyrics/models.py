# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only

from abc import ABC, abstractmethod
from typing import Literal

from layrics.LDDC.common.models import (
    APIResultList,
    LyricInfo,
    Lyrics,
    SearchType,
    SongInfo,
    Source,
)


class BaseAPI(ABC):
    source: Source

    @abstractmethod
    def get_lyrics(self, info: SongInfo | LyricInfo) -> Lyrics: ...


class CloudAPI(BaseAPI):
    supported_search_types: tuple[Literal[SearchType.SONG], ...]

    @abstractmethod
    def search(
        self,
        keyword: str,
        search_type: SearchType,
        page: int = 1,
    ) -> APIResultList[SongInfo]: ...
