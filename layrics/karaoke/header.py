import re

KARAOKE_HEADER_TEMPLATE = r"""[Script Info]
Title: Karaoke Subtitle
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None
PlayResX: 1920
PlayResY: 1080

[Aegisub Project Garbage]
Audio File: origin.wav
Video File: video.mp4
Video AR Mode: 4
Video AR Value: 1.777778
Video Zoom Percent: 0.500000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: K1,__FONTNAME__,__FONTSIZE__,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,1,__MARGIN_H__,__MARGIN_H__,__MARGIN_K1__,1
Style: K2,__FONTNAME__,__FONTSIZE__,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,3,__MARGIN_H__,__MARGIN_H__,__MARGIN_V__,1
Style: LEAD,sans-serif,__FONTSIZE__,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,1,__MARGIN_H__,__MARGIN_H__,__MARGIN_LEAD__,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Comment: 0,0:00:00.00,0:00:00.00,K1,,0,0,0,code syl all,fxgroup.kara=syl.inline_fx==""
Comment: 1,0:00:00.00,0:00:00.00,K1,overlay,0,0,0,template syl noblank all fxgroup kara,!retime("line",-100,500)!{\pos($center,$middle)\an5\shad0\fad(__FADE_IN_MS__,__FADE_OUT_MS__)\1c&H__OVERLAY_COLOR__&\3c&HFFFFFF&\clip(!$sleft-3!,0,!$sleft-3!,1080)\t($sstart,$send,\clip(!$sleft-3!,0,!$sright+3!,1080))\bord__BORD__}
Comment: 0,0:00:00.00,0:00:00.00,K1,,0,0,0,template syl all fxgroup kara,!retime("line",-500,500)!{\pos($center,$middle)\an5\fad(__FADE_IN_MS__,__FADE_OUT_MS__)}
Comment: 1,0:00:18.65,0:00:20.65,K1,overlay,0,0,0,template furi all,!retime("line",-100,500)!{\pos($center,!$middle__RUBY_OFFSET__!)\an5\shad0\fad(__FADE_IN_MS__,__FADE_OUT_MS__)\1c&H__OVERLAY_COLOR__&\3c&HFFFFFF&\clip(!$sleft-3!,0,!$sleft-3!,1080)\t($sstart,$send,\clip(!$sleft-3!,0,!$sright+3!,1080))\bord__BORD_FURI__}
Comment: 0,0:00:00.00,0:00:00.00,K1,,0,0,0,template furi all,!retime("line",-500,500)!{\pos($center,!$middle__RUBY_OFFSET__!)\an5\fad(__FADE_IN_MS__,__FADE_OUT_MS__)}
Comment: 0,0:00:00.00,0:00:00.00,K1,music,0,0,0,template fx no_k,!retime("line",-500,500)!{\pos($center,!$middle!)\an5\1c&H505050&\3c&HFFFFFFF&}
Comment: 0,0:00:00.00,0:00:00.00,K2,,0,0,0,code syl all,fxgroup.kara=syl.inline_fx==""
Comment: 1,0:00:00.00,0:00:00.00,K2,overlay,0,0,0,template syl noblank all fxgroup kara,!retime("line",-100,500)!{\pos($center,$middle)\an5\shad0\fad(__FADE_IN_MS__,__FADE_OUT_MS__)\1c&H__OVERLAY_COLOR__&\3c&HFFFFFF&\clip(!$sleft-3!,0,!$sleft-3!,1080)\t($sstart,$send,\clip(!$sleft-3!,0,!$sright+3!,1080))\bord__BORD__}
Comment: 0,0:00:00.00,0:00:00.00,K2,,0,0,0,template syl all fxgroup kara,!retime("line",-500,500)!{\pos($center,$middle)\an5\fad(__FADE_IN_MS__,__FADE_OUT_MS__)}
Comment: 1,0:00:18.65,0:00:20.65,K2,overlay,0,0,0,template furi all,!retime("line",-100,500)!{\pos($center,!$middle__RUBY_OFFSET__!)\an5\shad0\fad(__FADE_IN_MS__,__FADE_OUT_MS__)\1c&H__OVERLAY_COLOR__&\3c&HFFFFFF&\clip(!$sleft-3!,0,!$sleft-3!,1080)\t($sstart,$send,\clip(!$sleft-3!,0,!$sright+3!,1080))\bord__BORD_FURI__}
Comment: 0,0:00:00.00,0:00:00.00,K2,,0,0,0,template furi all,!retime("line",-500,500)!{\pos($center,!$middle__RUBY_OFFSET__!)\an5\fad(__FADE_IN_MS__,__FADE_OUT_MS__)}
Comment: 0,0:00:00.00,0:00:00.00,K2,music,0,0,0,template fx no_k,!retime("line",-500,500)!{\pos($center,!$middle!)\an5\1c&H505050&\3c&HFFFFFFF&}
"""


_DEFAULTS: dict[str, str | int] = {
    "FONTNAME": "sans-serif",
    "FONTSIZE": 96,
    "BORD": 5,
    "BORD_FURI": 3,
    "FADE_IN_MS": 800,
    "FADE_OUT_MS": 200,
    "MARGIN_H": 64,
    "MARGIN_V": 48,
    "OVERLAY_COLOR": "FF0000",
    "RUBY_OFFSET": "+10",
}


def render_karaoke_header(**overrides: str | int) -> str:
    values = dict(_DEFAULTS)
    values.update(overrides)
    values.setdefault(
        "MARGIN_K1", int(values["MARGIN_V"]) * 2 + int(values["FONTSIZE"]) // 2 * 3
    )
    values.setdefault(
        "MARGIN_LEAD", int(values["MARGIN_V"]) * 3 + int(values["FONTSIZE"]) * 3
    )

    def _repl(m: re.Match) -> str:
        key = m.group(1)
        return str(values.get(key, m.group(0)))

    return re.sub(
        r"__([A-Z][A-Z0-9]*(_[A-Z][A-Z0-9]*)*)__", _repl, KARAOKE_HEADER_TEMPLATE
    )


KARAOKE_HEADER = render_karaoke_header()
