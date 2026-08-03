# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only
"""Lyrics data models (slimmed from LDDC: dropped to()/add_offset()/is_inst() etc. unused APIs)"""

import re
from collections import UserDict
from collections.abc import MutableMapping
from dataclasses import replace
from typing import Literal, NamedTuple, NewType, TypeVar, overload

from ._enums import LyricsType, Source
from ._info import Artist, LyricInfo, SongInfo
from ._ruby import detect_ruby, strip_ruby


class LyricsWord(NamedTuple):
    start: int | None
    end: int | None
    text: str


class LyricsLine(NamedTuple):
    start: int | None
    end: int | None
    words: list[LyricsWord]


LyricsData = NewType("LyricsData", list[LyricsLine])
MultiLyricsData = NewType("MultiLyricsData", MutableMapping[str, LyricsData])


# FS is short for full_timestamps
class FSLyricsWord(NamedTuple):
    start: int
    end: int
    text: str


class FSLyricsLine(NamedTuple):
    start: int
    end: int
    words: list[FSLyricsWord]


FSLyricsData = NewType("FSLyricsData", list[FSLyricsLine])
FSMultiLyricsData = NewType("FSMultiLyricsData", MutableMapping[str, FSLyricsData])


@overload
def get_full_timestamps_lyrics_data(data: LyricsData, duration: int | None, only_line: Literal[False], skip_none: Literal[True]) -> FSLyricsData: ...


@overload
def get_full_timestamps_lyrics_data(data: LyricsData, duration: int | None, only_line: Literal[True], skip_none: bool = False) -> LyricsData: ...


@overload
def get_full_timestamps_lyrics_data(data: LyricsData, duration: int | None, only_line: bool = False, skip_none: Literal[False] = False) -> LyricsData: ...


def get_full_timestamps_lyrics_data(data: LyricsData, duration: int | None, only_line: bool = False, skip_none: bool = False) -> LyricsData | FSLyricsData:
    """Get lyrics data with complete timestamps.

    :param data: lyrics data
    :param duration: song end time
    :param only_line: whether to only infer line timestamps
    :param skip_none: whether to skip lines whose timestamps cannot be inferred
    """
    result = LyricsData([])
    fsresult = FSLyricsData([])

    for i, line in enumerate(data):
        # handle line-level timestamps
        line_start_time = line.start or (line.words[0].start if line.words else None)
        line_end_time = line.end or (line.words[-1].end if line.words else None)

        # infer the line start time
        if line_start_time is None:
            line_start_time = 0 if i == 0 else data[i - 1].end

        # infer the line end time
        if line_end_time is None:
            line_end_time = (
                (duration if duration is not None and line_start_time is not None and duration >= line_start_time else None)
                if i == len(data) - 1
                else data[i + 1].start
            )

        # handle line-only timestamp mode
        if only_line:
            if not skip_none or (line_start_time is not None and line_end_time is not None):
                result.append(LyricsLine(line_start_time, line_end_time, line[2]))
            continue

        # handle word-level timestamps
        words: list[LyricsWord] = []
        fswords: list[FSLyricsWord] = []
        for j, word in enumerate(line.words):
            # infer the word start time
            word_start_time = (line_start_time if j == 0 else line.words[j - 1].end) if word.start is None else word.start

            # infer the word end time
            word_end_time = (line_end_time if j == len(line.words) - 1 else line.words[j + 1].start) if word.end is None else word.end

            if skip_none:
                if word_start_time is None or word_end_time is None:  # skip invalid timestamps
                    continue
                fswords.append(FSLyricsWord(word_start_time, word_end_time, word.text))
            else:
                words.append(LyricsWord(word_start_time, word_end_time, word.text))

        # add valid lyric lines
        if not skip_none:
            result.append(LyricsLine(line_start_time, line_end_time, words))
        elif line_start_time is not None and line_end_time is not None:
            fsresult.append(FSLyricsLine(line_start_time, line_end_time, fswords))

    return fsresult if (not only_line and skip_none) else result


VT = TypeVar("VT", LyricsData, FSLyricsData)

_TRACK_ORDER = ("orig", "ts", "roma")


class LyricsBase(UserDict[str, VT]):
    __slots__ = ("tags", "types")

    def __init__(self, info: SongInfo | LyricInfo) -> None:
        super().__init__()
        if isinstance(info, SongInfo):
            self.info = LyricInfo(
                source=info.source,
                songinfo=info,
            )
        elif isinstance(info, LyricInfo):
            self.info = replace(info, data=None)

        self.types: dict[str, LyricsType] = {}
        self.tags: dict[str, str] = {}

    @property
    def source(self) -> Source:
        return self.info.source

    @property
    def title(self) -> str | None:
        return self.info.songinfo.title or self.tags.get("ti")

    @property
    def artist(self) -> Artist:
        return self.info.songinfo.artist or Artist(self.tags["ar"]) if "ar" in self.tags else Artist([])

    @property
    def album(self) -> str | None:
        return self.info.songinfo.album or self.tags.get("al")

    @property
    def id(self) -> int | str | None:
        return self.info.id or self.info.songinfo.id

    @property
    def duration(self) -> int | None:
        return self.info.duration

    @property
    def cached(self) -> bool:
        return self.info.cached

    def detect_lang(self, key: str = "orig") -> str:
        """Detect the language of the lyric text for the given track key by charset.

        Returns:
            Language code: ``"ja"`` ``"zh"`` ``"ko"`` ``"en"`` or ``"default"``.
        """
        data = self.get(key)
        if not data:
            return "default"
        text = "".join(w.text for line in data for w in line.words)
        if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text):
            return "ja"
        if re.search(r"[\uac00-\ud7af]", text):
            return "ko"
        if re.search(r"[\u4e00-\u9fff]", text):
            return "zh"
        if re.search(r"[a-zA-Z]", text):
            return "en"
        return "default"

    def select_track(self, priority: list[str]) -> str | None:
        """Select a track by priority: match track keys first, then detected language, then fall back to the default order."""
        for item in priority:
            if item in self:
                return item
            for key in self:
                if self.detect_lang(key) == item:
                    return key
        for key in _TRACK_ORDER:
            if key in self:
                return key
        return None

    def detect_ruby(self, track: str | None = None) -> bool:
        return detect_ruby(self, track=track)

    def strip_ruby(self, track: str | None = None) -> None:
        strip_ruby(self, track=track)

    def __bool__(self) -> bool:
        return any(lyric for lyric in self.values())

    def get_duration(self) -> int:
        if self.duration is not None:
            return self.duration * 1000
        if self.get("orig"):
            last_line = self["orig"][-1]
            last_start, last_end, last_words = last_line
            if last_end is not None:
                return last_end
            if last_words:
                last_word_start, last_word_end, _ = last_words[-1]
                if last_word_end is not None:
                    return last_word_end
                if last_word_start is not None:
                    return last_word_start
            if last_start is not None:
                return last_start
        elif self:
            for data in self.values():
                if data:
                    last_line = data[-1]
                    break
            else:
                return 0
            if last_line.end is not None:
                return last_line.end
            if last_line.words:
                if last_line.words[-1].end is not None:
                    return last_line.words[-1].end
                if last_line.words[-1].start is not None:
                    return last_line.words[-1].start
            if last_line.start is not None:
                return last_line.start
        return 0


class Lyrics(LyricsBase[LyricsData]):
    """Normal lyrics type (empty timestamps allowed)."""

    def get_fslyrics(self, duration_ms: int | None = None) -> FSLyrics:
        """Get lyrics with complete timestamps.

        :param duration_ms: song duration
        :return: lyrics with complete timestamps
        """
        full_timestamps_lyrics = FSLyrics(self.info)

        duration = duration_ms if duration_ms else self.get_duration()
        full_timestamps_lyrics.types = self.types
        full_timestamps_lyrics.tags = self.tags
        for lang, lyrics_data in self.items():
            full_timestamps_lyrics[lang] = get_full_timestamps_lyrics_data(data=lyrics_data, duration=duration, only_line=False, skip_none=True)

        # Fix overlapping lines: clamp end to the next line's start to avoid overlap when rendering
        for data in full_timestamps_lyrics.values():
            for i in range(len(data) - 1):
                if data[i].end > data[i + 1].start:
                    data[i] = data[i]._replace(end=data[i + 1].start)
            if not data:
                continue
            # Last-line fallback: extend end when end <= start
            last = data[-1]
            if last.end <= last.start:
                data[-1] = last._replace(
                    end=duration_ms if duration_ms else last.start + 5000
                )
        return full_timestamps_lyrics


class FSLyrics(LyricsBase[FSLyricsData]):
    """Lyrics type with complete timestamps."""
