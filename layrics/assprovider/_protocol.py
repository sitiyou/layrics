from __future__ import annotations
import re
from typing import Any, ClassVar, Protocol, runtime_checkable
from dataclasses import dataclass, replace

from LDDC.common.models import Lyrics as _LDCLyrics, FSLyrics, LyricsType, Source, LyricsLine, LyricsWord

from ._ass import AssStyle, DEFAULT_PRIMARY, DEFAULT_SECONDARY
from . import _ruby


_ass_providers: list[type[AssProvider]] = []


@dataclass
class AssTrigger:
    player_regex: str | None = None
    lyric_types: set[LyricsType] | None = None
    has_translation: bool | None = None
    has_romaji: bool | None = None
    source: Source | list[Source] | None = None

    def matches(self, player_name: str, lyrics: _LDCLyrics) -> bool:
        if self.player_regex is not None:
            if not re.search(self.player_regex, player_name):
                return False
        if self.lyric_types is not None:
            t = lyrics.types.get("orig")
            if t is None or t not in self.lyric_types:
                return False
        if self.has_translation is not None:
            has_ts = "ts" in lyrics and len(lyrics["ts"]) > 0
            if has_ts != self.has_translation:
                return False
        if self.has_romaji is not None:
            has_roma = "roma" in lyrics and len(lyrics["roma"]) > 0
            if has_roma != self.has_romaji:
                return False
        return True


class Lyrics(_LDCLyrics):
    """Layrics 增强歌词类，内建样式/语言检测。

    包装 LDDC 的原始 Lyrics 对象，将样式解析和语言检测作为属性/方法直接提供。
    """

    def __init__(
        self,
        lyrics: _LDCLyrics,
        fonts: dict[str, str] = {},
        *,
        primary_lang: str = "orig",
        secondary_lang: str | None = "ts",
        primary_override: dict[str, Any] | None = None,
        secondary_override: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(lyrics.info)
        self.update(lyrics)
        self.types = dict(lyrics.types)
        self.tags = dict(lyrics.tags)
        self._fonts = dict(fonts)
        self._primary_lang = primary_lang
        self._secondary_lang = secondary_lang
        self._primary_override = primary_override or {}
        self._secondary_override = secondary_override or {}
        self._strip_ruby()

    def _strip_ruby(self) -> None:
        _ruby.strip_ruby(self)

    def _detect_ruby(self) -> bool:
        return _ruby.detect_ruby(self)

    @property
    def primary_lang(self) -> str:
        return self._primary_lang

    @property
    def secondary_lang(self) -> str | None:
        return self._secondary_lang

    @property
    def primary_style(self) -> AssStyle:
        return self._build_style(DEFAULT_PRIMARY, "Primary", self._primary_lang, self._primary_override)

    @property
    def secondary_style(self) -> AssStyle | None:
        if not self._secondary_lang:
            return None
        return self._build_style(DEFAULT_SECONDARY, "Secondary", self._secondary_lang, self._secondary_override)

    def _build_style(self, base: AssStyle, name: str, lang_key: str, override: dict[str, Any]) -> AssStyle:
        if override:
            base = replace(base, name=name, **override)
        else:
            base = replace(base, name=name)
        lang = self.detect_lang(lang_key)
        f = self._fonts.get(lang)
        if f:
            base = replace(base, font_name=f)
        return base

    def detect_lang(self, key: str = "orig") -> str:
        """通过字符集检测指定 key 的歌词文本的语言。

        Returns:
            语言代码: ``"ja"`` ``"zh"`` ``"ko"`` ``"ru"`` 或 ``"default"``。
        """
        data = self.get(key)
        if not data:
            return "default"
        text = "".join(w.text for line in data for w in line.words)
        if re.search(r'[\u3040-\u309f\u30a0-\u30ff]', text):
            return "ja"
        if re.search(r'[\uac00-\ud7af]', text):
            return "ko"
        if re.search(r'[\u0400-\u04ff]', text):
            return "ru"
        if re.search(r'[\u4e00-\u9fff]', text):
            return "zh"
        return "default"

    def get_fslyrics(self, duration_ms: int | None = None) -> FSLyrics:
        fslyrics = super().get_fslyrics(duration_ms)
        for data in fslyrics.values():
            for i in range(len(data) - 1):
                if data[i].end > data[i + 1].start:
                    data[i] = data[i]._replace(end=data[i + 1].start)
        return fslyrics


@runtime_checkable
class AssProvider(Protocol):
    PROVIDER: ClassVar[str]
    priority: ClassVar[int]
    trigger: ClassVar[AssTrigger]

    def generate(self, lyrics: Lyrics, duration_ms: int | None = None) -> str: ...


def register_ass_provider(provider: type[AssProvider]) -> None:
    _ass_providers.append(provider)
    _ass_providers.sort(key=lambda p: p.priority)


def match_provider(
    player_name: str, lyrics: _LDCLyrics
) -> type[AssProvider] | None:
    for p in _ass_providers:
        if p.trigger.matches(player_name, lyrics):
            return p
    return None
