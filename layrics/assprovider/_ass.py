from __future__ import annotations

from dataclasses import dataclass

from ._util import ass_escape, ms2ass


@dataclass
class AssHeader:
    title: str = "lyrics"
    script_type: str = "v4.00+"
    collisions: str = "Normal"
    play_depth: int = 0
    play_res_x: int = 1920
    play_res_y: int = 1080

    def to_ass(self) -> str:
        return (
            "[Script Info]\n"
            f"Title: {ass_escape(self.title)}\n"
            f"ScriptType: {self.script_type}\n"
            f"Collisions: {self.collisions}\n"
            f"PlayDepth: {self.play_depth}\n"
            f"PlayResX: {self.play_res_x}\n"
            f"PlayResY: {self.play_res_y}\n\n"
        )


@dataclass
class AssStyle:
    name: str = "primary"
    font_name: str = "sans-serif"
    font_size: float = 24
    primary_colour: str = "&H00FFFFFF"
    secondary_colour: str = "&H00FFFFFF"
    outline_colour: str = "&H00000000"
    back_colour: str = "&H00000000"
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike_out: bool = False
    scale_x: float = 100.0
    scale_y: float = 100.0
    spacing: float = 0.0
    angle: float = 0.0
    border_style: int = 1
    outline: float = 1.0
    shadow: float = 1.0
    alignment: int = 2
    margin_l: int = 20
    margin_r: int = 20
    margin_v: int = 5
    encoding: int = 1

    def to_ass(self) -> str:
        return (
            f"Style: {self.name},{self.font_name},{self.font_size},"
            f"{self.primary_colour},{self.secondary_colour},"
            f"{self.outline_colour},{self.back_colour},"
            f"{int(self.bold)},{int(self.italic)},{int(self.underline)},{int(self.strike_out)},"
            f"{self.scale_x},{self.scale_y},{self.spacing},{self.angle},"
            f"{self.border_style},{self.outline},{self.shadow},"
            f"{self.alignment},{self.margin_l},{self.margin_r},{self.margin_v},"
            f"{self.encoding}"
        )


@dataclass
class AssDialogueLine:
    start_ms: int
    end_ms: int
    layer: int = 0
    style: str = "Default"
    name: str = ""
    margin_l: int = 0
    margin_r: int = 0
    margin_v: int = 0
    effect: str = ""
    text: str = ""

    def to_ass(self) -> str:
        return (
            f"Dialogue: {self.layer},{ms2ass(self.start_ms)},{ms2ass(self.end_ms)},"
            f"{self.style},{self.name},{self.margin_l},{self.margin_r},{self.margin_v},"
            f"{self.effect},{self.text}"
        )


# 默认预置样式 — primary 在上，secondary 在下
# outline/back 色带 alpha 通道实现柔和边缘与阴影
DEFAULT_PRIMARY = AssStyle(
    name="Primary",
    font_size=48,
    primary_colour="&H00E6D8AD",
    secondary_colour="&H00AAAAAA",
    outline_colour="&H88000000",
    back_colour="&H40000000",
    outline=2.0,
    shadow=2.0,
    margin_l=480,
    margin_r=480,
    margin_v=64,
)

DEFAULT_SECONDARY = AssStyle(
    name="Secondary",
    font_size=32,
    primary_colour="&H00CCCCCC",
    secondary_colour="&H00555555",
    # outline_colour="&H66000000",
    back_colour="&H30000000",
    outline=1.0,
    shadow=1.0,
    margin_l=480,
    margin_r=480,
    margin_v=24,
)


def build_ass(
    header: AssHeader,
    styles: list[AssStyle],
    events: list[AssDialogueLine],
) -> str:
    out = header.to_ass()

    out += (
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
        " OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,"
        " ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding\n"
    )
    for s in styles:
        out += s.to_ass() + "\n"
    out += "\n"

    out += (
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name,"
        " MarginL, MarginR, MarginV, Effect, Text\n"
    )
    for e in events:
        out += e.to_ass() + "\n"

    return out
