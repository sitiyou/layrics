from __future__ import annotations

import logging
import re


logger = logging.getLogger("layrics.ruby")


# 行级 detect：kanji + 可选空格 + 括号 ruby（跨 word 边界也能匹配）
_RUBY_RE = re.compile(
    r'[\u4e00-\u9fff]\s*'
    r'(?:（[^）]*）|\([^)]*\)|［[^］]*］|\[[^\]]*\]'
    r')'
)
# strip pass1：kanji + 括号 → 保留 kanji
_RUBY_STRIP_RE = re.compile(
    r'[\u4e00-\u9fff]\s*'
    r'(?:（[^）]*）|\([^)]*\)|［[^］]*］|\[[^\]]*\]'
    r')'
)
# strip pass2：独立括号（kanji 在别的 word 中）→ 整体删除
_RUBY_BARE_RE = re.compile(
    r'（[^）]*）|\([^)]*\)|［[^］]*］|\[[^\]]*\]'
)
# strip pass3：零散括号字符（各字符独立成 word 的情形）
_RUBY_CHARS_RE = re.compile(r'[（）()［］\[\]]')

# 包含 ruby pattern 的 line 数占总 line 数的比例阈值
_RUBY_LINE_RATIO = 0.5


def _find_bracket_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    pairs = [('（', '）'), ('(', ')'), ('［', '］'), ('[', ']')]
    i = 0
    while i < len(text):
        for open_ch, close_ch in pairs:
            if text[i] == open_ch:
                close = text.find(close_ch, i + 1)
                if close != -1:
                    ranges.append((i, close))
                    i = close
                    break
        i += 1
    return ranges


def _is_ruby_content(word_start: int, word_end: int, ranges: list[tuple[int, int]]) -> bool:
    for open_pos, close_pos in ranges:
        if word_start >= open_pos + 1 and word_end <= close_pos:
            return True
    return False


def detect_ruby(lyrics, track: str | None = None) -> bool:
    total = 0
    ruby_lines = 0
    for lang in lyrics:
        if track is not None and lang != track:
            continue
        for line in lyrics[lang]:
            total += 1
            text = ' '.join(w.text for w in line.words)
            if _RUBY_RE.search(text):
                ruby_lines += 1
    ratio = ruby_lines / total if total > 0 else 0
    result = total > 0 and ratio >= _RUBY_LINE_RATIO
    logger.debug("detect: total_lines=%d ruby_lines=%d ratio=%.2f threshold=%.2f strip=%s",
               total, ruby_lines, ratio, _RUBY_LINE_RATIO, result)
    return result


def strip_ruby(lyrics, track: str | None = None) -> None:
    if not detect_ruby(lyrics, track=track):
        return
    for lang in list(lyrics.keys()):
        data = lyrics[lang]
        new_lines: list = []
        for li, line in enumerate(data):
            text = ''.join(w.text for w in line.words)
            ruby_ranges = _find_bracket_ranges(text)

            new_words: list = []
            pos = 0
            for wi, w in enumerate(line.words):
                word_start = pos
                word_end = pos + len(w.text)
                pos = word_end

                if _is_ruby_content(word_start, word_end, ruby_ranges):
                    continue

                clean = _RUBY_STRIP_RE.sub(lambda m: m.group(0)[0], w.text)
                clean = _RUBY_BARE_RE.sub('', clean)
                clean = _RUBY_CHARS_RE.sub('', clean).strip()
                if clean:
                    if clean != w.text:
                        w = w._replace(text=clean)
                    new_words.append(w)
            if new_words:
                new_lines.append(line._replace(words=new_words))
        lyrics[lang] = new_lines
