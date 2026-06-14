from __future__ import annotations
import re
from typing import Any, ClassVar, Protocol, runtime_checkable
from dataclasses import dataclass, field, replace

from LDDC.common.models import Lyrics, LyricsType, Source

from ._ass import AssStyle, DEFAULT_PRIMARY, DEFAULT_SECONDARY


_ass_providers: list[type[AssProvider]] = []


@dataclass
class AssTrigger:
    player_regex: str | None = None
    lyric_types: set[LyricsType] | None = None
    has_translation: bool | None = None
    has_romaji: bool | None = None
    source: Source | list[Source] | None = None

    def matches(self, player_name: str, lyrics: Lyrics) -> bool:
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


@dataclass
class AssContext:
    primary_style: AssStyle = field(default_factory=lambda: DEFAULT_PRIMARY)
    secondary_style: AssStyle | None = field(default_factory=lambda: DEFAULT_SECONDARY)
    primary_lang: str = "orig"
    secondary_lang: str | None = "ts"


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
    player_name: str, lyrics: Lyrics
) -> type[AssProvider] | None:
    for p in _ass_providers:
        if p.trigger.matches(player_name, lyrics):
            return p
    return None


def _detect_lang(text: str) -> str:
    if re.search(r'[\u3040-\u309f\u30a0-\u30ff]', text):
        return "ja"
    if re.search(r'[\uac00-\ud7af]', text):
        return "ko"
    if re.search(r'[\u0400-\u04ff]', text):
        return "ru"
    if re.search(r'[\u4e00-\u9fff]', text):
        return "zh"
    return "default"


def detect_lyrics_lang(lyrics: Lyrics, key: str = "orig") -> str:
    """通过字符集检测指定 key 的歌词文本的语言。

    Returns:
        语言代码: ``"ja"`` ``"zh"`` ``"ko"`` ``"ru"`` 或 ``"default"``。
    """
    data = lyrics.get(key)
    if not data:
        return "default"
    text = "".join(w.text for line in data for w in line.words)
    return _detect_lang(text)


def make_context(
    lyrics: Lyrics,
    fonts: dict[str, str] = {},
    *,
    primary_lang: str = "orig",
    secondary_lang: str | None = "ts",
    primary_override: dict[str, Any] | None = None,
    secondary_override: dict[str, Any] | None = None,
) -> AssContext:
    """根据歌词语言动态构造 AssContext，自动匹配字体。

    Args:
        lyrics: 歌词对象
        fonts: ``{语言代码: 字体名}`` 映射（来自 ``Config.fonts``）
        primary_lang: 原文在 ``lyrics`` 中的 key
        secondary_lang: 翻译在 ``lyrics`` 中的 key，设为 ``None`` 禁用
        primary_override: 覆盖 Primary 样式属性（来自 ``cfg.get_style_config("primary")``）
        secondary_override: 覆盖 Secondary 样式属性
    """
    def _build(name: str, lang_key: str, override: dict[str, Any] | None) -> AssStyle:
        base = DEFAULT_PRIMARY if name == "Primary" else DEFAULT_SECONDARY
        if override:
            base = replace(base, name=name, **override)
        else:
            base = replace(base, name=name)
        lang = detect_lyrics_lang(lyrics, lang_key)
        f = fonts.get(lang)
        if f:
            base = replace(base, font_name=f)
        return base

    primary = _build("Primary", primary_lang, primary_override)
    secondary = None
    if secondary_lang:
        secondary = _build("Secondary", secondary_lang, secondary_override)

    return AssContext(
        primary_style=primary,
        secondary_style=secondary,
        primary_lang=primary_lang,
        secondary_lang=secondary_lang,
    )
