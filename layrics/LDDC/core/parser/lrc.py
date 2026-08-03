# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only
import re

from layrics.LDDC.common.models import (
    LyricsData,
    LyricsLine,
    LyricsType,
    LyricsWord,
    MultiLyricsData,
    Source,
)
from layrics.LDDC.common.time import time2ms

from .utils import judge_lyrics_type

_TAG_SPLIT_PATTERN = re.compile(r"^\[(?P<k>\w+):(?P<v>[^\]]*)\]$")  # tag match pattern
_LINE_SPLIT_PATTERN = re.compile(r"^\[(\d+):(\d+)\.(\d+)\](.*)$")  # lyric line match pattern
_ENHANCED_WORD_SPLIT_PATTERN = re.compile(r"<(\d+):(\d+)\.(\d+)>((?:(?!<\d+:\d+\.\d+>).)*)(?:<(\d+):(\d+)\.(\d+)>$)?")
_WORD_SPLIT_PATTERN = re.compile(r"((?:(?!\[\d+:\d+\.\d+\]).)*)(?:\[(\d+):(\d+)\.(\d+)\])?")  # lyric word match pattern
_MULTI_LINE_SPLIT_PATTERN = re.compile(r"^((?:\[\d+:\d+\.\d+\]){2,})(.*)$")
_TIMESTAMPS_PATTERN = re.compile(r"\[(\d+):(\d+)\.(\d+)\]")


def _lrc2list_data(lrc: str, source: Source | None = None) -> tuple[dict[str, str], list[LyricsData]]:
    """Convert plain, enhanced, per-word, and NetEase non-standard LRC into a list of LyricsData.

    Args:
        lrc (str): the LRC string
        source (Source | None, optional): LRC source. Defaults to None.

    Returns:
        tuple[dict[str, str], list[LyricsData]]: tag dict, list of LyricsData

    """
    lrc_lists: list[LyricsData] = [LyricsData([])]
    start_time_lists: list[list] = [[]]

    def add_line(line: LyricsLine) -> None:
        for i, lrc_list in enumerate(lrc_lists):
            if line.start not in start_time_lists[i]:
                # no existing lyric line with the same start time
                if line.start is not None:
                    lrc_list.append(line)
                    start_time_lists[i].append(line.start)
                break
        else:
            if line[2]:
                lrc_lists.append(LyricsData([line]))
                start_time_lists.append([line.start])

    tags = {}

    for raw_line in lrc.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("["):
            continue

        if line_match := _LINE_SPLIT_PATTERN.match(line):  # handle a lyric line
            m, s, ms, line_content = line_match.groups()
            start, end, words = time2ms(m, s, ms), None, []
            words: list[LyricsWord]

            if source == Source.NE and (multi_match := _MULTI_LINE_SPLIT_PATTERN.match(line)):
                # for NetEase lyrics, multiple leading timestamps mean all those lines share this content
                timestamps, line_content = multi_match.groups()
                # multiple timestamps at the start of the lyric line
                for ts_match in _TIMESTAMPS_PATTERN.finditer(timestamps):
                    start = time2ms(*ts_match.groups())
                    add_line(LyricsLine(start, None, [LyricsWord(start, None, line_content)]))
                continue

            if "<" in line_content and ">" in line_content:
                # the lyric line uses the enhanced format
                for enhanced_word_parts in _ENHANCED_WORD_SPLIT_PATTERN.finditer(line_content):
                    s_m, s_s, s_ms, word_str, e_m, e_s, e_ms = enhanced_word_parts.groups()
                    word_start = time2ms(s_m, s_s, s_ms)
                    word_end = time2ms(e_m, e_s, e_ms) if e_m and e_s and e_ms else None
                    end = word_end or end

                    # set the end time of the previous word
                    if words:  # a previous word exists
                        words[-1] = LyricsWord(words[-1][0], word_start, words[-1][2])

                    # append the lyric word to the lyric line
                    if word_str:
                        words.append(LyricsWord(word_start, word_end, word_str))
            else:
                # the lyric line does not use the enhanced format
                word_parts = _WORD_SPLIT_PATTERN.findall(line_content)
                if word_parts:
                    # per word
                    for w_i, (word_str, e_m, e_s, e_ms) in enumerate(word_parts):
                        word_start = start if not words else words[-1].end
                        word_end = time2ms(e_m, e_s, e_ms) if e_m and e_s and e_ms else None
                        if w_i == len(word_parts) - 1:  # current word is the last in the line
                            end = word_end or end

                        # append the lyric word to the lyric line
                        if word_str:
                            words.append(LyricsWord(word_start, word_end, word_str))

            add_line(LyricsLine(start, end, words))
            continue

        if tag_match := _TAG_SPLIT_PATTERN.match(line):  # handle a tag line
            tags[tag_match.group("k")] = tag_match.group("v")
            continue

    # sort by start time
    for i, lrc_list in enumerate(lrc_lists):
        lrc_lists[i] = LyricsData(sorted([line for line in lrc_list if line.start is not None], key=lambda x: x.start))  # type: ignore[]  line.start is guaranteed not None here
        for i_, line in enumerate(lrc_lists[i]):
            if i_ != 0 and lrc_lists[i][i_ - 1].end is None and line.start is not None:
                # the previous line has no end time, so set it to the current line's start time
                lrc_lists[i][i_ - 1] = LyricsLine(lrc_lists[i][i_ - 1].start, line.start, lrc_lists[i][i_ - 1].words)

        # drop empty lines
        lrc_lists[i] = LyricsData([line for line in lrc_lists[i] if line.words])

    return tags, lrc_lists


def lrc2mdata(lrc: str, source: Source | None = None) -> tuple[dict[str, str], MultiLyricsData]:
    tags, lrc_lists = _lrc2list_data(lrc, source)

    if not lrc_lists:
        return {}, MultiLyricsData({})
    if len(lrc_lists) == 1:
        return tags, MultiLyricsData({"orig": lrc_lists[0]})

    if len(lrc_lists) == 2:
        if judge_lyrics_type(lrc_lists[0]) == LyricsType.VERBATIM and judge_lyrics_type(lrc_lists[1]) == LyricsType.VERBATIM:
            return tags, MultiLyricsData({"roma": lrc_lists[0], "orig": lrc_lists[1]})
        return tags, MultiLyricsData({"orig": lrc_lists[0], "ts": lrc_lists[1]})
    return tags, MultiLyricsData({"roma": lrc_lists[0], "orig": lrc_lists[1], "ts": lrc_lists[2]})


def lrc2data(lrc: str, source: Source | None = None) -> tuple[dict[str, str], LyricsData]:
    tags, lrc_lists = _lrc2list_data(lrc, source)
    # merge into a single LyricsData
    for i, lrc_list in enumerate(lrc_lists):
        if i == 0:
            continue
        for line_list1 in lrc_list:
            for line_list2 in reversed(lrc_lists[0]):
                if line_list1[0] == line_list2[0]:
                    # same start time as an existing line, insert after it
                    lrc_lists[0].insert(lrc_lists[0].index(line_list2) + 1, line_list1)
                    break
    return tags, lrc_lists[0]
