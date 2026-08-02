from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any, ClassVar, Protocol, runtime_checkable

from layrics.LDDC.common.models import (
    FSLyrics,
    FSLyricsLine,
    LyricsType,
    Source,
)
from layrics.LDDC.common.models import (
    Lyrics as _LDCLyrics,
)

from ._ass import DEFAULT_PRIMARY, DEFAULT_SECONDARY, AssStyle

logger = logging.getLogger("layrics.assprovider")


_ass_providers: list[type[AssProvider]] = []


@dataclass
class AssTrigger:
    player_regex: str | None = None
    lyric_types: set[LyricsType] | None = None
    has_translation: bool | None = None
    has_romaji: bool | None = None
    source: Source | list[Source] | None = None

    def matches(self, player_name: str, lyrics: _LDCLyrics) -> bool:
        if self.player_regex is not None and not re.search(self.player_regex, player_name):
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
        fonts: dict[str, str] | None = None,
        *,
        primary_track: str | None = None,
        secondary_track: str | None = None,
        primary_priority: list[str] | None = None,
        secondary_priority: list[str] | None = None,
        primary_override: dict[str, Any] | None = None,
        secondary_override: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(lyrics.info)
        self.update(lyrics)
        self.types = dict(lyrics.types)
        self.tags = dict(lyrics.tags)
        self._fonts = dict(fonts or {})
        self._primary_override = primary_override or {}
        self._secondary_override = secondary_override or {}
        self._init_tracks(
            primary_track, secondary_track, primary_priority, secondary_priority
        )

    def _init_tracks(
        self,
        primary_track: str | None,
        secondary_track: str | None,
        primary_priority: list[str] | None,
        secondary_priority: list[str] | None,
    ) -> None:
        if primary_priority:
            pt = self.select_track(primary_priority)
            self._primary_track = pt or "orig"
        elif primary_track:
            self._primary_track = primary_track
        else:
            self._primary_track = "orig"
        if secondary_priority:
            st = self.select_track(secondary_priority)
            self._secondary_track = st
        elif secondary_track is not None:
            self._secondary_track = secondary_track
        else:
            self._secondary_track = "ts"

    @property
    def primary_track(self) -> str:
        return self._primary_track

    @property
    def secondary_track(self) -> str | None:
        return self._secondary_track

    @property
    def primary_style(self) -> AssStyle:
        return self._build_style(
            DEFAULT_PRIMARY, "Primary", self._primary_track, self._primary_override
        )

    @property
    def secondary_style(self) -> AssStyle | None:
        if not self._secondary_track:
            return None
        return self._build_style(
            DEFAULT_SECONDARY,
            "Secondary",
            self._secondary_track,
            self._secondary_override,
        )

    def _build_style(
        self, base: AssStyle, name: str, lang_key: str, override: dict[str, Any]
    ) -> AssStyle:
        if override:
            base = replace(base, name=name, **override)
        else:
            base = replace(base, name=name)
        lang = self.detect_lang(lang_key)
        f = self._fonts.get(lang)
        if f:
            base = replace(base, font_name=f)
        return base

    def active_tracks(
        self, fslyrics: FSLyrics, *, secondary_enabled: bool = True
    ) -> list[str]:
        langs = [self._primary_track]
        sec = self._secondary_track
        if secondary_enabled and sec and sec in fslyrics and len(fslyrics[sec]) > 0:
            langs.append(sec)
        return langs

    def align_tracks(
        self, fslyrics: FSLyrics, active_tracks: list[str]
    ) -> dict[str, dict[int, int]]:
        alignment: dict[str, dict[int, int]] = {}
        orig_data = fslyrics[self._primary_track]
        logger.debug(
            "align_tracks: primary=%s len=%d  active=%s",
            self._primary_track,
            len(orig_data),
            active_tracks,
        )
        for track in active_tracks[1:]:
            if track not in fslyrics:
                logger.debug("align_tracks: track %r not in fslyrics, skipping", track)
                continue
            track_data = fslyrics[track]
            logger.debug(
                "align_tracks: aligning %r (%d lines) → primary (%d lines)",
                track,
                len(track_data),
                len(orig_data),
            )
            mapping: dict[int, int] = {}
            for oi, oline in enumerate(orig_data):
                best = -1
                best_dist = 2**31 - 1
                for li, lline in enumerate(track_data):
                    dist = abs(lline.start - oline.start)
                    if dist < best_dist:
                        best_dist = dist
                        best = li
                mapping[oi] = best
                otext = "".join(w.text for w in oline.words)
                ttext = (
                    "".join(w.text for w in track_data[best].words)
                    if best >= 0
                    else "?"
                )
                logger.debug(
                    "align_tracks:  primary[%d] start=%d %r → %r[%d] start=%d dist=%d %r",
                    oi,
                    oline.start,
                    otext[:30],
                    track,
                    best,
                    track_data[best].start if best >= 0 else -1,
                    best_dist,
                    ttext[:30],
                )
            alignment[track] = mapping
            logger.debug("align_tracks: %r mapping=%s", track, mapping)
        return alignment

    def iter_aligned(
        self,
        fslyrics: FSLyrics,
        *,
        secondary_enabled: bool = True,
    ) -> Iterator[tuple[FSLyricsLine, dict[str, FSLyricsLine]]]:
        active_tracks = self.active_tracks(
            fslyrics, secondary_enabled=secondary_enabled
        )
        logger.debug("iter_aligned: active_tracks=%s", active_tracks)
        alignment = self.align_tracks(fslyrics, active_tracks)
        orig_data = fslyrics[self._primary_track]
        for i, oline in enumerate(orig_data):
            aligned: dict[str, FSLyricsLine] = {}
            for track in active_tracks[1:]:
                li = alignment.get(track, {}).get(i)
                if li is not None and li >= 0:
                    aligned[track] = fslyrics[track][li]
            yield oline, aligned


@runtime_checkable
class AssProvider(Protocol):
    PROVIDER: ClassVar[str]
    priority: ClassVar[int]
    trigger: ClassVar[AssTrigger]

    def generate(self, lyrics: Lyrics, duration_ms: int | None = None) -> str: ...


def register_ass_provider(provider: type[AssProvider]) -> None:
    _ass_providers.append(provider)
    _ass_providers.sort(key=lambda p: p.priority)


def match_provider(player_name: str, lyrics: _LDCLyrics) -> type[AssProvider] | None:
    for p in _ass_providers:
        if p.trigger.matches(player_name, lyrics):
            return p
    return None
