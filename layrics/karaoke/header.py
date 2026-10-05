import colorsys
import re

KARAOKE_HEADER_TEMPLATE = r"""[Script Info]
Title: Karaoke Subtitle
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: K1,__FONTNAME__,__FONTSIZE__,&H00FFFFFF,&H000000FF,&H00__BASE_OUTLINE_COLOR__,&H00000000,0,0,0,0,100,100,__SPACING__,0,1,2,2,1,__MARGIN_H__,__MARGIN_H__,__MARGIN_K1__,1
Style: K2,__FONTNAME__,__FONTSIZE__,&H00FFFFFF,&H000000FF,&H00__BASE_OUTLINE_COLOR__,&H00000000,0,0,0,0,100,100,__SPACING__,0,1,2,2,3,__MARGIN_H__,__MARGIN_H__,__MARGIN_V__,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


DEFAULTS: dict[str, str | float] = {
    "FONTNAME": "sans-serif",
    "FONTSIZE": 96,
    "SPACING": 5,
    "BORD": 5,
    "BORD_FURI": 3,
    "FADE_IN_MS": 800,
    "FADE_OUT_MS": 200,
    "MARGIN_H": 64,
    "MARGIN_V": 48,
    "OVERLAY_COLOR": "FCDD1C",
    "RUBY_OFFSET": "+10",
    "BASE_OUTLINE_COLOR": "222222",
    "OVERLAY_OUTLINE_COLOR": "EFEFEF",
    "BLUR": 3,
    "BLUR_SCALE": 1.5,
    "CLIP_SIZE": 24,
}

SWEEP_FAST_FRAC = 0.3
SWEEP_SPEED_RATIO = 2


def _glow_colour(
    bgr: str, saturation_scale: float, brightness: float, hue_shift: float = 0
) -> str:
    blue, green, red = bytes.fromhex(bgr)
    hue, saturation, _ = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
    red, green, blue = colorsys.hsv_to_rgb(
        (hue + hue_shift) % 1,
        max(0, min(1, saturation * saturation_scale)),
        max(0, min(1, brightness)),
    )
    return "".join(f"{round(channel * 255):02X}" for channel in (blue, green, red))


def _effect_rows(style: str, values: dict[str, str | float]) -> list[str]:
    clip_size = int(values["CLIP_SIZE"])
    fast_time_fraction = format(
        SWEEP_FAST_FRAC / (SWEEP_FAST_FRAC + SWEEP_SPEED_RATIO * (1 - SWEEP_FAST_FRAC)),
        "g",
    )
    fast_end_x = (
        f"!math.floor($sleft*{1 - SWEEP_FAST_FRAC:g}+$sright*{SWEEP_FAST_FRAC:g})!"
    )
    split_time = f"!$sstart+$sdur*{fast_time_fraction}!"
    left = f"!$sleft-{clip_size}!"
    pulse = (
        r"\fscx100\fscy100"
        r"\t($sstart,$send,0.5,\fscx110\fscy110)"
        r"\t($send,!$send+$sdur/2!,2,\fscx100\fscy100)"
    )
    sweep = (
        rf"\clip({left},0,{left},1080)"
        rf"\t(!$sstart-{clip_size}!,$sstart,\clip({left},0,$sleft,1080))"
        rf"\t($sstart,{split_time},{1 / SWEEP_SPEED_RATIO:g},\clip({left},0,{fast_end_x},1080))"
        rf"\t({split_time},$send,\clip({left},0,$sright,1080))"
        rf"\t($send,!$send+{clip_size}!,\clip({left},0,!$sright+{clip_size}!,1080))"
    )
    rows = []
    for kind, y, border_key in (
        ("syl", "$middle", "BORD"),
        ("furi", f"!$middle{int(values['RUBY_OFFSET']):+d}!", "BORD_FURI"),
    ):
        border = values[border_key]
        glow_border = round(float(border) * float(values["BLUR_SCALE"]))
        common = (
            rf"\pos($center,{y})\an5\shad0"
            rf"\fad({values['FADE_IN_MS']},{values['FADE_OUT_MS']})"
        )
        commands = (
            common
            + rf"\blur{values['BLUR']}"
            + pulse
            + rf"\bord{glow_border}\3c&H{values['BASE_BLUR_COLOR']}&\alpha&H33&",
            common
            + rf"\blur{values['BLUR']}"
            + rf"\1c&H{values['OVERLAY_COLOR']}&\3c&H{values['OVERLAY_BLUR_COLOR']}&"
            + r"\alpha&HCC&\t($sstart,$send,\alpha&H33&)"
            + pulse
            + rf"\bord{glow_border}",
            common + pulse + rf"\bord{border}\3c&H{values['BASE_OUTLINE_COLOR']}&",
            common
            + rf"\1c&H{values['OVERLAY_COLOR']}&\3c&H{values['OVERLAY_OUTLINE_COLOR']}&"
            + sweep
            + pulse
            + rf"\bord{border}",
        )
        for layer, text in enumerate(commands):
            name = "overlay" if layer in (1, 3) else ""
            rows.append(
                f"Comment: {layer},0:00:00.00,0:00:00.00,{style},{name},"
                f"0,0,0,template {kind} noblank,{{{text}}}"
            )
    return rows


def render_karaoke_header(
    *, secondary_scale: float = 1, **overrides: str | float
) -> str:
    values = {**DEFAULTS, **overrides}
    values.setdefault(
        "MARGIN_K1", int(values["MARGIN_V"]) * 2 + int(values["FONTSIZE"]) // 2 * 3
    )
    values.setdefault(
        "OVERLAY_BLUR_COLOR", _glow_colour(str(values["OVERLAY_COLOR"]), 0.6, 1)
    )
    values.setdefault(
        "BASE_BLUR_COLOR",
        _glow_colour(str(values["OVERLAY_BLUR_COLOR"]), 0.618, 0.618, 0.5),
    )
    header = re.sub(
        r"__([A-Z][A-Z0-9]*(_[A-Z][A-Z0-9]*)*)__",
        lambda match: str(values[match.group(1)]),
        KARAOKE_HEADER_TEMPLATE,
    )
    effects = [row for style in ("K1", "K2") for row in _effect_rows(style, values)]
    effect_scale = secondary_scale * 0.5
    border = float(values["BORD"]) * effect_scale
    blur = float(values["BLUR"]) * effect_scale
    glow_border = (
        round(float(values["BORD"]) * float(values["BLUR_SCALE"])) * effect_scale
    )
    common = r"\shad0"
    for layer, text in (
        (0, common + rf"\blur{blur:g}\bord{glow_border:g}\alpha&H33&"),
        (2, common + rf"\blur{blur:g}\bord{border:g}"),
    ):
        effects.append(
            f"Comment: {layer},0:00:00.00,0:00:00.00,Secondary,,"
            f"0,0,0,template pre-line keeptags,{{{text}}}"
        )
    return header + "\n".join(effects) + "\n"


KARAOKE_HEADER = render_karaoke_header()
