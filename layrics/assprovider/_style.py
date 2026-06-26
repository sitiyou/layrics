from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class BottomStyle:
    primary: str = "orig"
    secondary: str | None = "ts"
    primary_position: str = "top"

    animation: bool = False
    anim_duration: int = 200
    anim_style: str = "fade"

    font_family: str = "sans-serif"
    font_size: int = 12
    font_size_secondary: int = 8
    bold: bool = False
    italic: bool = False

    primary_color: str = "&H00FFFFFF"
    secondary_color: str = "&H00CCCCCC"
    primary_karaoke_color: str | None = None
    secondary_karaoke_color: str | None = None
    outline_color: str = "&H00000000"
    shadow_color: str = "&H00000000"
    outline_size: float = 1.0
    shadow_size: float = 1.0

    alignment: int = 2
    margin_v: int = 5
    margin_lr: int = 20
    margin_v_spacing: int = 2

    gradient: str | None = None
    gradient_color: str = "&H00000000"
    gradient_angle: float = 0.0
