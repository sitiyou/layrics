from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, fields
from typing import Any, Optional

import appdirs
from LDDC.common.models import Source

if os.environ.get("LAYRICS_CONFIG_DIR"):
    _CONFIG_DIR = os.environ["LAYRICS_CONFIG_DIR"]
else:
    _CONFIG_DIR = appdirs.user_config_dir("layrics")

_CONFIG_PATH = os.path.join(_CONFIG_DIR, "config.toml")


@dataclass
class SearchConfig:
    sources: list[Source] = field(default_factory=lambda: [Source.QM, Source.NE])
    result_count: int = 5


@dataclass
class OverlayConfig:
    target_fps: int = -1


@dataclass
class MprisConfig:
    include_players: list[str] = field(default_factory=list)
    exclude_players: list[str] = field(default_factory=list)


@dataclass
class FontsConfig:
    mapping: dict[str, str] = field(default_factory=lambda: {
        "default": "sans-serif",
        "ja": "Noto Sans CJK JP",
        "zh": "Noto Sans CJK SC",
    })


@dataclass
class StyleOverrideConfig:
    font_name: str | None = None
    font_size: float | None = None
    primary_colour: str | None = None
    secondary_colour: str | None = None
    outline_colour: str | None = None
    back_colour: str | None = None
    bold: int | None = None
    italic: int | None = None
    underline: int | None = None
    strike_out: int | None = None
    scale_x: float | None = None
    scale_y: float | None = None
    spacing: float | None = None
    angle: float | None = None
    border_style: int | None = None
    outline: float | None = None
    shadow: float | None = None
    alignment: int | None = None
    margin_l: int | None = None
    margin_r: int | None = None
    margin_v: int | None = None
    encoding: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {f.name: v for f in fields(self) if (v := getattr(self, f.name)) is not None}


@dataclass
class StyleConfig:
    primary: StyleOverrideConfig = field(default_factory=StyleOverrideConfig)
    secondary: StyleOverrideConfig = field(default_factory=StyleOverrideConfig)


@dataclass
class LyricsConfig:
    primary: list[str] = field(default_factory=lambda: ["orig"])
    secondary: list[str] = field(default_factory=lambda: ["ts"])


class Config:
    def __init__(self):
        self.search = SearchConfig()
        self.overlay = OverlayConfig()
        self.mpris = MprisConfig()
        self.fonts = FontsConfig()
        self.style = StyleConfig()
        self.lyrics = LyricsConfig()
        self._provider_config: dict[str, dict[str, Any]] = {}
        self._include_patterns: list[re.Pattern] = []
        self._exclude_patterns: list[re.Pattern] = []
        self._load()

    @staticmethod
    def _parse_sources(raw_sources: list[str]) -> list[Source]:
        parsed: list[Source] = []
        for name in raw_sources:
            try:
                parsed.append(Source[name.upper().strip()])
            except KeyError:
                pass
        return parsed

    def _load(self):
        if not os.path.exists(_CONFIG_PATH):
            return
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[import-unresolved]
        with open(_CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)

        # [search]
        raw_search = data.get("search", {})
        if isinstance(raw_search, dict):
            raw_sources = raw_search.get("sources")
            if isinstance(raw_sources, list) and raw_sources:
                parsed = self._parse_sources(raw_sources)
                if parsed:
                    self.search.sources = parsed
            raw_count = raw_search.get("result_count")
            if isinstance(raw_count, int) and raw_count > 0:
                self.search.result_count = raw_count

        # [overlay]
        raw_overlay = data.get("overlay", {})
        if isinstance(raw_overlay, dict):
            raw_fps = raw_overlay.get("target_fps", -1)
            if isinstance(raw_fps, int) and (raw_fps > 0 or raw_fps == -1):
                self.overlay.target_fps = raw_fps

        # [mpris]
        raw_mpris = data.get("mpris", {})
        if isinstance(raw_mpris, dict):
            raw_include = raw_mpris.get("include_players", [])
            if isinstance(raw_include, list):
                self.mpris.include_players = [str(p) for p in raw_include]
            raw_exclude = raw_mpris.get("exclude_players", [])
            if isinstance(raw_exclude, list):
                self.mpris.exclude_players = [str(p) for p in raw_exclude]

        self._include_patterns = [re.compile(p) for p in self.mpris.include_players]
        self._exclude_patterns = [re.compile(p) for p in self.mpris.exclude_players]

        # [fonts]
        raw_fonts = data.get("fonts", {})
        if isinstance(raw_fonts, dict):
            self.fonts.mapping = {str(k): str(v) for k, v in raw_fonts.items()}

        # [style]
        raw_style = data.get("style", {})
        if isinstance(raw_style, dict):
            for key in ("primary", "secondary"):
                section = raw_style.get(key, {})
                if isinstance(section, dict):
                    valid = {f.name for f in fields(StyleOverrideConfig)}
                    kwargs = {str(k): v for k, v in section.items() if k in valid}
                    setattr(self.style, key, StyleOverrideConfig(**kwargs))

        # [lyrics]
        raw_lyrics = data.get("lyrics", {})
        if isinstance(raw_lyrics, dict):
            raw_pri = raw_lyrics.get("primary")
            if isinstance(raw_pri, list) and all(isinstance(i, str) for i in raw_pri):
                self.lyrics.primary = raw_pri
            raw_sec = raw_lyrics.get("secondary")
            if isinstance(raw_sec, list) and all(isinstance(i, str) for i in raw_sec):
                self.lyrics.secondary = raw_sec

        # [assprovider.*]
        raw_assprovider = data.get("assprovider", {})
        if isinstance(raw_assprovider, dict):
            for k, v in raw_assprovider.items():
                if isinstance(v, dict):
                    self._provider_config[str(k)] = {str(kk): vv for kk, vv in v.items()}

    def get_style_config(self, key: str) -> dict[str, Any]:
        d = getattr(self.style, key, None)
        if d is None:
            return {}
        return d.to_dict()

    def get_provider_config(self, name: str) -> dict[str, Any]:
        return dict(self._provider_config.get(name, {}))

    @property
    def include_players(self) -> list[re.Pattern]:
        return self._include_patterns

    @include_players.setter
    def include_players(self, patterns: list[re.Pattern]) -> None:
        self._include_patterns = list(patterns)

    @property
    def exclude_players(self) -> list[re.Pattern]:
        return self._exclude_patterns

    @exclude_players.setter
    def exclude_players(self, patterns: list[re.Pattern]) -> None:
        self._exclude_patterns = list(patterns)


_CONFIG: Optional[Config] = None


def get_config() -> Config:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = Config()
    return _CONFIG
