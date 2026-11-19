"""The desktop lyric effect, compiled by kara-templater into standard ASS."""

import colorsys
from dataclasses import replace
from math import floor
from typing import Any

from kara_templater import Document, KaraokeLine, Segment, TextUnit, layout_line

from layrics.assprovider._ass import AssStyle
from layrics.assprovider._util import ass_escape
from layrics.LDDC.common.models import FSLyricsData, FSLyricsWord


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


def _lyrics(words: list[FSLyricsWord]) -> KaraokeLine:
    units = []
    for word in words:
        body, sep, ruby = word.text.replace("｜", "|").partition("|")
        if sep:
            reading = ruby.rstrip(" \t")
            body += ruby[len(reading) :]
            ruby = reading
        spill = ruby.startswith(("<", "＜"))
        join = bool(sep) and not ruby.startswith(("!", "！", "<", "＜"))
        if ruby.startswith(("!", "！", "<", "＜")):
            ruby = ruby[1:]
        segment = Segment(word.start, word.end, ruby)
        if body.strip() in ("#", "＃") and units:
            last = units[-1]
            units[-1] = replace(
                last,
                segments=(*last.segments, segment),
                ruby_continuation=last.ruby_continuation
                if any(s.ruby for s in last.segments)
                else join,
                ruby_spillback=last.ruby_spillback or spill,
            )
        else:
            units.append(TextUnit(body, (segment,), join, spill))
    return KaraokeLine(tuple(units))


def _layers(line, style, text, box, clocks, options, border, y_offset=0):
    """Four native events per drawn word/reading, independent of note duration."""
    if not text.strip():
        return
    start = clocks[0][0] - line.start_time
    end = clocks[-1][1] - line.start_time
    clip_pad = options["clip_size"]
    left = floor(box.left) - clip_pad
    sweep = rf"\clip({left},0,{left},1080)"

    def clip(time1, time2, x, accel=""):
        return rf"\t({time1:g},{time2:g},{accel}\clip({left},0,{floor(x)},1080))"

    sweep += clip(start - clip_pad, start, box.left)
    for t1, t2, x1, x2 in clocks:
        t1 -= line.start_time
        t2 -= line.start_time
        split = t1 + (t2 - t1) * 0.3 / 1.7
        sweep += clip(t1, split, x1 + (x2 - x1) * 0.3, "0.5,") + clip(split, t2, x2)
    sweep += clip(end, end + clip_pad, box.right + clip_pad)
    pulse = (
        rf"\fscx100\fscy100\t({start},{end},0.5,\fscx110\fscy110)"
        rf"\t({end},{end + (end - start) / 2:g},2,\fscx100\fscy100)"
    )
    common = (
        rf"\pos({box.center:g},{box.middle + y_offset:g})\an5\shad0"
        rf"\fad({options['fade_in_ms']},{options['fade_out_ms']})"
    )
    glow = rf"\blur{options['blur']:g}\bord{round(border * options['blur_scale'])}"
    fill = rf"\1c&H{options['overlay_color']}&"
    commands = (
        glow + rf"\3c&H{options['base_blur_color']}&\alpha&H33&",
        glow
        + fill
        + rf"\3c&H{options['overlay_blur_color']}&\alpha&HCC&\t({start},{end},\alpha&H33&)",
        rf"\bord{border:g}\3c&H{options['base_outline_color']}&",
        rf"\bord{border:g}"
        + fill
        + rf"\3c&H{options['overlay_outline_color']}&"
        + sweep,
    )
    for layer, tags in enumerate(commands):
        yield replace(
            line,
            comment=False,
            style=style,
            layer=layer,
            effect="fx",
            text="{" + common + pulse + tags + "}" + ass_escape(text),
        )


def render(
    document: Document, primary: AssStyle, rows: FSLyricsData, overrides: dict[str, Any]
) -> str:
    options: dict[str, Any] = {
        "spacing": 5,
        "bord": 5,
        "bord_furi": 3,
        "blur": 3,
        "blur_scale": 1.5,
        "clip_size": 24,
        "fade_in_ms": 800,
        "fade_out_ms": 200,
        "ruby_offset": 10,
        "base_outline_color": "222222",
        "overlay_outline_color": "EFEFEF",
        "overlay_color": primary.primary_colour.removeprefix("&H")[-6:],
    }
    options.update((key.lower(), value) for key, value in overrides.items())
    options.setdefault(
        "overlay_blur_color", _glow_colour(options["overlay_color"], 0.6, 1)
    )
    options.setdefault(
        "base_blur_color",
        _glow_colour(options["overlay_blur_color"], 0.618, 0.618, 0.5),
    )
    names = {"Primary": "K1", "PrimaryLeft": "K1", "PrimaryRight": "K2"}
    for style in document.styles.values():
        style.spacing = options["spacing"]
        if style.name == "Secondary":
            style.spacing *= style.fontsize / primary.font_size
            continue
        style.name = names.get(style.name, style.name)
        style.fields["PrimaryColour"] = style.fields["SecondaryColour"]
        ruby = replace(
            style, name=style.name + "-furigana", fontsize=style.fontsize / 2
        )
        document.records.insert(document.records.index(style) + 1, ruby)
    styles = document.styles
    source_rows = iter(rows)
    for line in document.lines:
        if line.style == "Secondary":
            ratio = styles["Secondary"].fontsize / primary.font_size / 2
            blur = options["blur"] * ratio
            width = options["bord"]
            for layer, border, alpha in (
                (0, round(width * options["blur_scale"]), r"\alpha&H33&"),
                (2, width, ""),
            ):
                tags = rf"{{\shad0\blur{blur:g}\bord{border * ratio:g}{alpha}}}"
                document.records.append(
                    replace(line, layer=layer, effect="fx", text=tags + line.text)
                )
        else:
            line.style = names.get(line.style, line.style)
            style = styles[line.style]
            ruby = styles[style.name + "-furigana"]
            layout = layout_line(
                _lyrics(next(source_rows).words), style=style, ruby_style=ruby
            )
            for unit in layout.units:
                clocks = [
                    (s.source.start_ms, s.source.end_ms, s.left, s.right)
                    for s in unit.segments
                ]
                document.records.extend(
                    _layers(
                        line,
                        style.name,
                        unit.source.text,
                        unit.box,
                        clocks,
                        options,
                        options["bord"],
                    )
                )
                for seg in unit.segments:
                    if seg.ruby is not None:
                        clocks = [
                            (
                                seg.source.start_ms,
                                seg.source.end_ms,
                                seg.ruby.left,
                                seg.ruby.right,
                            )
                        ]
                        document.records.extend(
                            _layers(
                                line,
                                ruby.name,
                                seg.source.ruby,
                                seg.ruby,
                                clocks,
                                options,
                                options["bord_furi"],
                                float(options["ruby_offset"]),
                            )
                        )
        line.comment = True
        line.effect = "karaoke"
    return document.dumps()
