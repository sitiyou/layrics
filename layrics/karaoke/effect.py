"""The desktop lyric effect, compiled by kara-templater into standard ASS."""

import colorsys
from collections.abc import Iterator
from dataclasses import replace
from itertools import accumulate
from math import floor
from typing import Any, Literal

from kara_templater import (
    BLACK,
    WHITE,
    Box,
    Document,
    DocumentLyrics,
    DocumentText,
    Lifetime,
    Line,
    LyricMapping,
    LyricSegment,
    LyricUnit,
    RubyText,
    Style,
    TextAppearance,
    TextRun,
    TimedTextSpan,
    layout_lyrics,
)

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


def _lyrics(words: list[FSLyricsWord], style_name: str) -> DocumentLyrics:
    appearance = TextAppearance(style_name, WHITE, WHITE, BLACK, BLACK)
    runs: list[TextRun] = []
    units: list[LyricUnit] = []
    offset = 0
    for word in words:
        body, sep, ruby = word.text.replace("｜", "|").partition("|")
        if sep:
            reading = ruby.rstrip(" \t")
            body += ruby[len(reading) :]
            ruby = reading
        mode: Literal["join", "break", "spill"] = "join"
        if ruby.startswith(("<", "＜")):
            mode, ruby = "spill", ruby[1:]
        elif ruby.startswith(("!", "！")):
            mode, ruby = "break", ruby[1:]
        continuation = bool(units) and body.strip() in ("#", "＃")
        if continuation:
            start, end = units[-1].start, units[-1].end
        else:
            start, end = offset, offset + len(body)
            if body:
                runs.append(TextRun(body, start, end, appearance))
            offset = end

        reading = None
        if ruby:
            length = len(ruby)
            run = TextRun(ruby, 0, length, appearance)
            reading = RubyText(
                DocumentText(None, (), (run,), (), (), ()),
                (LyricMapping(0, length, 0, length),),
                mode,
            )
        timing = TimedTextSpan(start, end, word.start / 1000, word.end / 1000, "kf")
        segment = LyricSegment(timing, start, end, reading)
        if continuation:
            previous = units[-1]
            units[-1] = replace(previous, segments=(*previous.segments, segment))
        else:
            units.append(LyricUnit(start, end, (segment,)))

    body = DocumentText(None, (), tuple(runs), (), (), ())
    return DocumentLyrics(
        body, body, (LyricMapping(0, offset, 0, offset),), tuple(units)
    )


def _body_origin(document: Document, style: Style, bounds: Box) -> tuple[float, float]:
    available = document.meta.res_x - style.margin_l - style.margin_r - bounds.width
    left = style.margin_l + available * ((style.align - 1) % 3) / 2
    top = (
        document.meta.res_y - style.margin_v - bounds.height,
        (document.meta.res_y - bounds.height) / 2,
        style.margin_v,
    )[(style.align - 1) // 3]
    return left - bounds.left, top - bounds.top


def _clock(
    timing: TimedTextSpan, left: float, right: float
) -> tuple[int, int, float, float]:
    return round(timing.start * 1000), round(timing.end * 1000), left, right


def _draw_layout(
    document: Document,
    line: Line,
    words: list[FSLyricsWord],
    style: Style,
    ruby: Style,
    options: dict[str, Any],
) -> Iterator[Line]:
    lyrics = _lyrics(words, style.name)
    surface = lyrics.body.text
    if not surface.strip():
        return
    measured = layout_lyrics(
        document,
        lyrics,
        id=f"{line.style}:{line.start_time}",
        display=Lifetime(line.start_time / 1000, line.end_time / 1000),
        ruby_gap=0,
    )
    x, y = _body_origin(document, style, measured.body.bounds)
    readings = {
        (item.unit_index, item.segment_index): item.layout for item in measured.ruby
    }
    for index, unit in enumerate(lyrics.units):
        text = surface[unit.start : unit.end]
        unit_readings = tuple(
            readings.get((index, i)) for i in range(len(unit.segments))
        )
        if text.strip():
            box = measured.body.range_bounds(unit.start, unit.end)
            box = replace(box, left=box.left + x, top=box.top + y)
            widths = [item.bounds.width if item else 0 for item in unit_readings]
            total = sum(widths)
            if not total:
                widths = [1.0] * len(unit.segments)
                total = len(widths)
            edges = tuple(
                box.left + box.width * width / total
                for width in accumulate(widths, initial=0)
            )
            clocks = [
                _clock(segment.timing, edges[i], edges[i + 1])
                for i, segment in enumerate(unit.segments)
            ]
            yield from _layers(
                line, style.name, text, box, clocks, options, options["bord"]
            )
        for segment, reading in zip(unit.segments, unit_readings, strict=True):
            if reading is None:
                continue
            box = replace(
                reading.bounds, left=reading.bounds.left + x, top=reading.bounds.top + y
            )
            yield from _layers(
                line,
                ruby.name,
                reading.source.text,
                box,
                [_clock(segment.timing, box.left, box.right)],
                options,
                options["bord_furi"],
                float(options["ruby_offset"]),
            )


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
            document.records.extend(
                _draw_layout(
                    document, line, next(source_rows).words, style, ruby, options
                )
            )
        line.comment = True
        line.effect = "karaoke"
    return document.dumps()
