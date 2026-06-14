import os
import re
from typing import Any, Optional

import appdirs

if os.environ.get("LAYRICS_CONFIG_DIR"):
    _CONFIG_DIR = os.environ["LAYRICS_CONFIG_DIR"]
else:
    _CONFIG_DIR = appdirs.user_config_dir("layrics")

_CONFIG_PATH = os.path.join(_CONFIG_DIR, "config.toml")


class Config:
    def __init__(self):
        self.include_players: list[re.Pattern] = []
        self.fonts: dict[str, str] = {}
        self._style_config: dict[str, dict[str, str | int | float | bool]] = {}
        self._provider_config: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self):
        if not os.path.exists(_CONFIG_PATH):
            return
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        with open(_CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
        raw = data.get("include_players", [])
        for pat_str in raw:
            self.include_players.append(re.compile(pat_str))
        raw_fonts = data.get("fonts", {})
        if isinstance(raw_fonts, dict):
            self.fonts = {str(k): str(v) for k, v in raw_fonts.items()}
        raw_style = data.get("style", {})
        if isinstance(raw_style, dict):
            for k, v in raw_style.items():
                if isinstance(v, dict):
                    self._style_config[str(k)] = {str(kk): vv for kk, vv in v.items()}
        raw_assprovider = data.get("assprovider", {})
        if isinstance(raw_assprovider, dict):
            for k, v in raw_assprovider.items():
                if isinstance(v, dict):
                    self._provider_config[str(k)] = {str(kk): vv for kk, vv in v.items()}

    def get_style_config(self, key: str) -> dict[str, str | int | float | bool]:
        return dict(self._style_config.get(key, {}))

    def get_provider_config(self, name: str) -> dict[str, Any]:
        return dict(self._provider_config.get(name, {}))


_CONFIG: Optional[Config] = None


def get_config() -> Config:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = Config()
    return _CONFIG
