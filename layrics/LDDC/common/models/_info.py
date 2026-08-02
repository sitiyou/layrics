# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only
"""信息模型(精简自 LDDC:去掉 SongListInfo/歌单相关,去掉 to_dict/from_dict 等未用接口)"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from types import MappingProxyType
from typing import Self, TypeVar

from ._enums import Language, SearchType, Source

__all__ = ["APIResultList", "Artist", "InfoBase", "LyricInfo", "SearchInfo", "SongInfo"]


class Artist(tuple[str]):
    __slots__ = ()

    def __new__(cls, artist: str | Iterable[str]) -> Self:
        unique_ordered = OrderedDict.fromkeys([artist] if isinstance(artist, str) else artist)
        return super().__new__(cls, unique_ordered)

    def __str__(self) -> str:
        return self.str()

    def str(self, sep: str = "/") -> str:
        return sep.join(self)

    def __bool__(self) -> bool:
        return bool(self.str())


@dataclass(frozen=True, slots=True)
class InfoBase:
    source: Source


@dataclass(frozen=True, slots=True)
class SongInfo(InfoBase):
    title: str | None = None
    subtitle: str | None = None
    artist: Artist | None = None
    album: str | None = None
    duration: int | None = None  # 单位毫秒

    id: str | None = None
    mid: str | None = None
    hash: str | None = None

    language: Language | None = None

    @property
    def full_title(self) -> str:
        return (f"{self.title}({self.subtitle})" if self.subtitle else self.title) if self.title else ""

    @property
    def str_artist(self) -> str:
        return str(self.artist) if self.artist else ""


@dataclass(frozen=True, slots=True)
class LyricInfo(InfoBase):
    songinfo: SongInfo
    id: str | None = None
    accesskey: str | None = None
    duration: int | None = None
    creator: str | None = None
    score: int | None = None

    path: Path | None = None
    data: bytearray | bytes | None = None

    cached: bool = False


@dataclass(frozen=True, slots=True)
class SearchInfo(InfoBase):
    source: Source | list[Source]
    keyword: str
    search_type: SearchType
    page: int | None


A = TypeVar("A", SongInfo, LyricInfo)


class APIResultList(Sequence[A]):
    __slots__ = ("_items", "_source_ranges", "cached", "info")

    def __init__(
        self,
        result: Iterable[A] | APIResultList[A],
        info: InfoBase | None = None,
        ranges: tuple[int, int, int] | MappingProxyType[Source, tuple[int, int, int]] | None = None,
        cached: bool | None = None,
    ) -> None:
        if isinstance(result, APIResultList):
            self._items = result._items
            self._source_ranges = dict(result._source_ranges)
            self.info = info if info is not None else result.info
            self.cached = cached if cached is not None else result.cached
        else:
            self._source_ranges = self._process_ranges(ranges, {item.source for item in result})
            self._items = self._create_ordered_items(result)  # 始终按source_ranges顺序交叉合并元素
            self.info = info
            self.cached = cached if cached is not None else False

        self._validate_ranges()

    def _process_ranges(
        self,
        ranges: tuple[int, int, int] | MappingProxyType[Source, tuple[int, int, int]] | None,
        sources: set[Source],
    ) -> dict[Source, tuple[int, int, int]]:
        if ranges is None:
            return {}

        if isinstance(ranges, MappingProxyType):
            return dict(ranges)

        if len(sources) > 1:
            msg = "有多个数据源,但只提供了一个范围元组"
            raise ValueError(msg)
        return {next(iter(sources)): ranges} if sources else {}

    def _create_ordered_items(self, items: Iterable[A]) -> tuple[A, ...]:
        """预先生成交叉排序的元组"""
        if not self._source_ranges:
            return ()

        groups: dict[Source, list[A]] = {}
        for item in items:
            groups.setdefault(item.source, []).append(item)

        valid_sources = [source for source in Source.__members__.values() if source in groups]

        return tuple(
            item
            for group in zip_longest(*(groups[source] for source in valid_sources))
            for item in group
            if item is not None
        )

    def _validate_ranges(self) -> None:
        total_in_ranges = sum(end - start + 1 for start, end, _ in self._source_ranges.values())
        if len(self._items) != total_in_ranges:
            msg = "ranges 的总数不等于结果的长度"
            raise ValueError(msg)

    @property
    def source_ranges(self) -> MappingProxyType[Source, tuple[int, int, int]]:
        return MappingProxyType(self._source_ranges)

    @property
    def sources(self) -> list[Source]:
        return list(self.source_ranges.keys())

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, index: int) -> A:
        return self._items[index]

    def __iter__(self) -> Iterator[A]:
        return iter(self._items)
