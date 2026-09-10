from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from typing import Any

import appdirs

from layrics.LDDC.common.models import Source

if os.environ.get("LAYRICS_CONFIG_DIR"):
    CONFIG_DIR = os.environ["LAYRICS_CONFIG_DIR"]
else:
    CONFIG_DIR = appdirs.user_config_dir("layrics")

CONFIG_PATH = os.path.join(CONFIG_DIR, "config.toml")


@dataclass
class SearchConfig:
    sources: list[Source] = field(default_factory=lambda: [Source.QM, Source.NE])


@dataclass
class OverlayConfig:
    target_fps: int = -1


@dataclass
class MprisConfig:
    """MPRIS bus names to ignore when discovering players."""

    exclude: list[str] = field(default_factory=list)


@dataclass
class MpdConfig:
    """Direct MPD connection; the MPD_* environment overrides these fields.

    host accepts mpc-style values: hostname, "/unix/socket", "@abstract".
    """

    host: str = ""
    port: int = 0
    password: str = ""


@dataclass
class FontsConfig:
    mapping: dict[str, str] = field(
        default_factory=lambda: {
            "default": "sans-serif",
            "ja": "Noto Sans CJK JP",
            "zh": "Noto Sans CJK SC",
        }
    )


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
        return {
            f.name: v for f in fields(self) if (v := getattr(self, f.name)) is not None
        }


@dataclass
class StyleConfig:
    primary: StyleOverrideConfig = field(default_factory=StyleOverrideConfig)
    secondary: StyleOverrideConfig = field(default_factory=StyleOverrideConfig)


@dataclass
class LyricsConfig:
    primary: list[str] = field(default_factory=lambda: ["orig"])
    secondary: list[str] = field(default_factory=lambda: ["ts"])


@dataclass
class DmenuConfig:
    """layctl dmenu 使用的菜单程序（可带参数，如 "rofi -dmenu"）"""

    program: str = "dmenu"


class Config:
    def __init__(self):
        self.search = SearchConfig()
        self.overlay = OverlayConfig()
        self.mpris = MprisConfig()
        self.mpd = MpdConfig()
        self.fonts = FontsConfig()
        self.style = StyleConfig()
        self.lyrics = LyricsConfig()
        self.dmenu = DmenuConfig()
        self._provider_config: dict[str, dict[str, Any]] = {}
        self._load()
        self._provider_config.setdefault(
            "default",
            {
                "karaoke": True,
                "line_mode": "single",
                "secondary": True,
                "single": {"margin_v_bottom": 32},
                "double": {
                    "advance_ms": 5000,
                    "margin_v_right": 24,
                    "v_spacing": 64,
                    "margin_l": 480,
                    "margin_r": 480,
                    "max_length": 1280,
                },
            },
        )

    @staticmethod
    def _parse_sources(raw_sources: list[str]) -> list[Source]:
        parsed: list[Source] = []
        for name in raw_sources:
            src = Source.parse(name)
            if src is not None:
                parsed.append(src)
        return parsed

    def _load(self):
        if not os.path.exists(CONFIG_PATH):
            return
        import tomllib
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)

        # [search]
        raw_search = data.get("search", {})
        if isinstance(raw_search, dict):
            raw_sources = raw_search.get("sources")
            if isinstance(raw_sources, list) and raw_sources:
                parsed = self._parse_sources(raw_sources)
                if parsed:
                    self.search.sources = parsed

        # [overlay]
        raw_overlay = data.get("overlay", {})
        if isinstance(raw_overlay, dict):
            raw_fps = raw_overlay.get("target_fps", -1)
            if isinstance(raw_fps, int) and (raw_fps > 0 or raw_fps == -1):
                self.overlay.target_fps = raw_fps

        # [mpris]
        raw_mpris = data.get("mpris", {})
        if isinstance(raw_mpris, dict):
            raw_exclude = raw_mpris.get("exclude", [])
            if isinstance(raw_exclude, list):
                self.mpris.exclude = [str(p) for p in raw_exclude]

        # [mpd]
        raw_mpd = data.get("mpd", {})
        if isinstance(raw_mpd, dict):
            raw_host = raw_mpd.get("host")
            if isinstance(raw_host, str):
                self.mpd.host = raw_host
            raw_port = raw_mpd.get("port")
            if isinstance(raw_port, int) and raw_port > 0:
                self.mpd.port = raw_port
            raw_password = raw_mpd.get("password")
            if isinstance(raw_password, str):
                self.mpd.password = raw_password

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

        # [dmenu]
        raw_dmenu = data.get("dmenu", {})
        if isinstance(raw_dmenu, dict):
            raw_program = raw_dmenu.get("program")
            if isinstance(raw_program, str) and raw_program.strip():
                self.dmenu.program = raw_program.strip()

        # [assprovider.*]
        raw_assprovider = data.get("assprovider", {})
        if isinstance(raw_assprovider, dict):
            for k, v in raw_assprovider.items():
                if isinstance(v, dict):
                    self._provider_config[str(k)] = {
                        str(kk): vv for kk, vv in v.items()
                    }

    def get_style_config(self, key: str) -> dict[str, Any]:
        d = getattr(self.style, key, None)
        if d is None:
            return {}
        return d.to_dict()

    def get_provider_config(self, name: str) -> dict[str, Any]:
        return dict(self._provider_config.get(name, {}))


CONFIG: Config | None = None


def get_config() -> Config:
    global CONFIG
    if CONFIG is None:
        CONFIG = Config()
    return CONFIG
