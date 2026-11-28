"""Original optical meniscus-wavefront karaoke template for desktop lyrics.

Preserves native ASS typography, layout, shadows, and configured resting colors
before and after singing. Visual expression is concentrated strictly at the
moving local sweep front:
- A forward-leaning curved meniscus wavefront continuous across letters.
- Theme-adaptive refractive crest + chromatic wet-ink wake that settles back
  to the exact configured primary fill.
- Directional outline rim-catch along the passing front that settles back to
  the exact configured outline color.
- Subtle, bounded buoyant micro-lift on active syllables/readings.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass, replace
from itertools import accumulate
from math import radians, tan

from kara_templater import (
    BLACK,
    WHITE,
    Color,
    Document,
    Lifetime,
    Line,
    LyricLayout,
    LyricLine,
    ObjectGroup,
    PositionedText,
    Scene,
    SceneObject,
    ShaderPaint,
    StatePatch,
    Style,
    TextObject,
    Tween,
    Vec2,
    layout_lyrics,
    parse_document_lyrics,
    smooth_rate,
)

from layrics.LDDC.common.models import FSLyricsData

from .effect import body_origin, project_words

SWEEP_SLANT_DEG = 14.0
ITALIC_SLANT_DEG = 20.0
LIFT_BODY_RATIO = 0.055
LIFT_RUBY_RATIO = 0.045
LIFT_PEAK = 0.30
LIFT_TAIL_SECONDS = 0.16
LIFT_MIN_SECONDS = 0.30
LIFT_MAX_SECONDS = 0.54
MIN_CLIP_SECONDS = 0.05

WAVEFRONT_FUNCTIONS = """
vec4 layrics_wavefront(int data, float t, float x_local, float y_local) {
    float y_top = item(data + 18);
    float y_height = max(item(data + 19), 1.0);
    float slant = item(data + 20);
    float em = max(item(data + 21), 1.0);
    float border_x = item(data + 24);
    int seg_count = refAt(data + 26);

    float v = clamp((y_local - y_top) / y_height, 0.0, 1.0);
    float ny = 2.0 * v - 1.0;
    float bow = 0.075 * em;
    float curve = slant * (0.5 * y_height - (y_local - y_top))
                + bow * (1.0 - ny * ny);
    float px = x_local - curve;

    float soft = max(0.14 * em, 0.5);
    float slant_reach = abs(slant) * (0.5 * y_height + border_x);
    float pad_l = 0.5 * slant_reach + 0.4 * bow + 0.5 * soft;
    float pad_r = border_x + slant_reach + soft;
    float settle = 0.24;

    int chosen = -1;
    for (int k = 0; k < seg_count; k++) {
        int seg = data + 30 + 4 * k;
        if (t >= item(seg)) {
            chosen = k;
        }
    }
    if (chosen < 0) {
        return vec4(0.0, -1e4, 0.0, v);
    }

    int seg = data + 30 + 4 * chosen;
    float t0 = item(seg);
    float t1 = item(seg + 1);
    float x0 = item(seg + 2);
    float x1 = item(seg + 3);
    bool is_first = (chosen == 0);
    bool is_last = (chosen == seg_count - 1);

    float start_x = is_first ? (x0 - pad_l) : x0;
    float end_x = is_last ? (x1 + 0.35 * pad_r) : x1;
    float dur = t1 - t0;

    float front;
    float sweep_t;
    float activity;

    if (dur <= 1e-5) {
        float post = max(t - t0, 0.0);
        float z_settle = 0.18;
        float q = clamp(post / z_settle, 0.0, 1.0);
        front = x1 + pad_r + 0.65 * em * (1.0 - pow(max(1.0 - q, 0.0), 2.2));
        sweep_t = 1.0;
        activity = (1.0 - smoothstep(0.0, z_settle, post)) * 0.85;
    } else if (t <= t1) {
        float u = clamp((t - t0) / dur, 0.0, 1.0);
        front = mix(start_x, end_x, u);
        float d = front - px;
        float onset_env = is_first
            ? smoothstep(0.0, min(0.035, 0.28 * dur), t - t0)
            : 1.0;
        float fill_env = is_first
            ? smoothstep(0.0, min(0.025, 0.22 * dur), t - t0)
            : 1.0;
        sweep_t = smoothstep(-soft, soft, d) * fill_env;
        activity = onset_env;
    } else {
        float post = t - t1;
        if (is_last) {
            float q = clamp(post / settle, 0.0, 1.0);
            front = end_x
                  + (0.65 * pad_r + 0.65 * em) * (1.0 - pow(max(1.0 - q, 0.0), 2.2));
            float d = front - px;
            sweep_t = max(smoothstep(-soft, soft, d), smoothstep(0.0, 0.06, post));
            activity = 1.0 - smoothstep(0.0, settle, post);
        } else {
            front = end_x;
            float d = front - px;
            sweep_t = smoothstep(-soft, soft, d);
            activity = mix(1.0, 0.25, smoothstep(0.0, 0.18, post));
        }
    }

    return vec4(sweep_t, front - px, activity, v);
}
"""

WAVEFRONT_PAINT_SOURCE = """
if (component == 0 || component == 1) {
    float t_local = PTS >= 0.0 ? (PTS - item(paint + 2)) : time;
    vec4 wf = layrics_wavefront(data, t_local, local.x, local.y);
    float sweep_t = wf.x;
    float dist = wf.y;
    float activity = wf.z;
    float v = wf.w;
    float em = max(item(data + 21), 1.0);
    float inv_face_op = item(data + 25);

    if (component == 0) {
        vec3 before_rgb = rgbAt(data);
        vec3 after_rgb = rgbAt(data + 3);
        vec3 base_rgb = mix(before_rgb, after_rgb, sweep_t);
        if (activity > 0.0005) {
            vec3 crest_rgb = rgbAt(data + 6);
            vec3 wake_rgb = rgbAt(data + 9);
            float crest_strength = item(data + 23);

            float d_crest = dist - 0.02 * em;
            float crest_w = d_crest < 0.0 ? (0.11 * em) : (0.21 * em);
            float crest_k = d_crest / max(crest_w, 1.0);
            float crest = exp(-crest_k * crest_k * 2.2);

            float bevel_k = (v - 0.36) / 0.36;
            float bevel = 0.72 + 0.28 * exp(-bevel_k * bevel_k);
            float caustic = 0.84 + 0.16 * cos(v * 4.4 - screen.x * 0.022 - t_local * 2.4);

            float wake_u = clamp(dist / max(0.88 * em, 1.0), 0.0, 1.0);
            float wake = smoothstep(0.0, 0.24, wake_u)
                       * pow(max(1.0 - wake_u, 0.0), 1.85);

            base_rgb = mix(base_rgb, wake_rgb, clamp(wake * 0.44 * activity, 0.0, 0.55));
            base_rgb = mix(
                base_rgb,
                crest_rgb,
                clamp(crest * bevel * caustic * crest_strength * activity, 0.0, 0.75)
            );
        }
        ink = base_rgb;
        alpha = alpha * inv_face_op * mix(item(data + 15), item(data + 16), sweep_t);
    } else {
        if (activity > 0.0005) {
            vec3 rim_rgb = rgbAt(data + 12);
            float rim_strength = item(data + 22);
            float d_rim = dist - 0.03 * em;
            float rim_w = d_rim < 0.0 ? (0.16 * em) : (0.35 * em);
            float rim_k = d_rim / max(rim_w, 1.0);
            float rim_wave = exp(-rim_k * rim_k * 2.0);
            float rim_bevel = mix(0.42, 1.0, 1.0 - smoothstep(0.18, 1.0, v));
            float rim_mix = rim_wave * rim_bevel * rim_strength * activity;
            ink = mix(ink, rim_rgb, clamp(rim_mix, 0.0, 0.72));
        }
        alpha = alpha * inv_face_op * item(data + 17);
    }
} else if (component == 2) {
    ink = rgbAt(data + 27);
}
"""

@dataclass(frozen=True)
class _WavePalette:
    before_fill: Color
    after_fill: Color
    outline_color: Color
    shadow_color: Color
    crest_fill: Color
    wake_fill: Color
    rim_outline: Color
    before_alpha: float
    after_alpha: float
    outline_alpha: float
    rim_strength: float
    crest_strength: float
    base_face_opacity: float


def _parse_ass_color(raw: str | None, fallback: Color) -> tuple[Color, float]:
    if not raw:
        return fallback, 1.0
    text = raw.strip().removesuffix("&")
    if text.startswith(("&H", "&h")):
        text = text[2:]
    elif text.startswith("H"):
        text = text[1:]
    try:
        packed = int(text, 16)
    except ValueError:
        return fallback, 1.0
    red = packed & 0xFF
    green = (packed >> 8) & 0xFF
    blue = (packed >> 16) & 0xFF
    alpha_byte = (packed >> 24) & 0xFF if len(text) > 6 else 0
    return Color(red, green, blue), max(0.0, min(1.0, 1.0 - alpha_byte / 255.0))


def _style_field(style: Style, key: str) -> str | None:
    target = key.lower()
    for name, value in style.fields.items():
        if name.lower() == target:
            return value
    return None


def _relative_luminance(color: Color) -> float:
    def linear(channel: int) -> float:
        value = channel / 255.0
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * linear(color.red)
        + 0.7152 * linear(color.green)
        + 0.0722 * linear(color.blue)
    )


def _hsv_color(hue: float, sat: float, val: float) -> Color:
    r, g, b = colorsys.hsv_to_rgb(
        hue % 1.0,
        max(0.0, min(1.0, sat)),
        max(0.0, min(1.0, val)),
    )
    return Color(round(r * 255), round(g * 255), round(b * 255))


def _mix_color(a: Color, b: Color, t: float) -> Color:
    k = max(0.0, min(1.0, t))
    return Color(
        round(a.red + (b.red - a.red) * k),
        round(a.green + (b.green - a.green) * k),
        round(a.blue + (b.blue - a.blue) * k),
    )


def _derive_wave_palette(style: Style) -> _WavePalette:
    after_fill, after_alpha = _parse_ass_color(
        _style_field(style, "PrimaryColour"), WHITE
    )
    before_fill, before_alpha = _parse_ass_color(
        _style_field(style, "SecondaryColour"), WHITE
    )
    outline_color, outline_alpha = _parse_ass_color(
        _style_field(style, "OutlineColour"), BLACK
    )

    ha, sa, va = colorsys.rgb_to_hsv(
        after_fill.red / 255.0, after_fill.green / 255.0, after_fill.blue / 255.0
    )
    hb, sb, _ = colorsys.rgb_to_hsv(
        before_fill.red / 255.0, before_fill.green / 255.0, before_fill.blue / 255.0
    )
    lum_after = _relative_luminance(after_fill)
    lum_outline = _relative_luminance(outline_color)

    chromatic = sa >= 0.14 or sb >= 0.14
    anchor_hue = ha if sa >= 0.14 else (hb if sb >= 0.14 else 0.11)
    anchor_sat = sa if sa >= 0.14 else (sb * 0.55 if sb >= 0.14 else 0.08)

    if lum_after < 0.18:
        # Dark-ink theme: satin tinted sheen instead of harsh white glare.
        crest_fill = _hsv_color(
            anchor_hue + 0.045, min(0.45, anchor_sat * 0.85), min(0.72, va + 0.42)
        )
        wake_fill = _hsv_color(
            anchor_hue - 0.035, min(0.85, anchor_sat * 1.1), min(0.48, va + 0.22)
        )
        crest_strength = 0.46
    elif lum_after > 0.84 and sa < 0.14:
        # Near-white achromatic sung fill: subtle pearl warmth, let outline carry shimmer.
        crest_fill = _hsv_color(anchor_hue + 0.04, 0.10, 1.0)
        wake_fill = _mix_color(after_fill, crest_fill, 0.35)
        crest_strength = 0.36
    else:
        # Standard chromatic / bright lyrics: subtle optical split-tint (+18° crest, -14° wake).
        crest_fill = _hsv_color(
            anchor_hue + 0.05,
            anchor_sat * 0.32 if chromatic else 0.06,
            min(1.0, max(va, 0.92) + 0.08),
        )
        wake_fill = _hsv_color(
            anchor_hue - 0.039,
            min(1.0, anchor_sat * 1.12 + 0.04) if chromatic else 0.04,
            min(1.0, va + (1.0 - va) * 0.24),
        )
        crest_strength = 0.56 if lum_after < 0.72 else 0.44

    if lum_outline < 0.35:
        rim_outline = _mix_color(after_fill, crest_fill, 0.36)
        if _relative_luminance(rim_outline) < 0.32:
            rim_outline = _mix_color(rim_outline, WHITE, 0.45)
        rim_strength = 0.56
    else:
        rim_outline = _mix_color(outline_color, after_fill, 0.55)
        rim_strength = 0.42

    opaque_face = before_alpha >= 0.998 and after_alpha >= 0.998
    return _WavePalette(
        before_fill=before_fill,
        after_fill=after_fill,
        outline_color=outline_color,
        shadow_color=_parse_ass_color(_style_field(style, "BackColour"), BLACK)[0],
        crest_fill=crest_fill,
        wake_fill=wake_fill,
        rim_outline=rim_outline,
        before_alpha=before_alpha,
        after_alpha=after_alpha,
        outline_alpha=outline_alpha,
        rim_strength=rim_strength,
        crest_strength=crest_strength,
        base_face_opacity=1.0 if opaque_face else 0.5,
    )


def _rgb_floats(color: Color) -> tuple[float, float, float]:
    return (color.red / 255.0, color.green / 255.0, color.blue / 255.0)


def _line_vertical_frame(characters: tuple[PositionedText, ...]) -> tuple[float, float]:
    boxes = [c.ink_bounds or c.bounds for c in characters if c.object.text.strip()]
    if not boxes:
        boxes = [c.bounds for c in characters]
    if not boxes:
        return 0.0, 48.0
    top = min(b.top for b in boxes)
    bottom = max(b.top + b.height for b in boxes)
    return top, max(bottom - top, 1.0)


def _unit_segments(
    layout: LyricLayout, unit_index: int
) -> tuple[tuple[float, float, float, float], ...]:
    unit = layout.lyrics.units[unit_index]
    segments = unit.segments
    if not segments:
        return ()
    if len(segments) == 1:
        span = segments[0].timing
        return ((span.start, span.end, 0.0, 1.0),)

    readings = {
        item.segment_index: item.layout.bounds.width
        for item in layout.ruby
        if item.unit_index == unit_index
    }
    widths = [readings.get(i, 0.0) for i in range(len(segments))]
    total = sum(widths)
    if total <= 0.0:
        widths = [1.0] * len(segments)
        total = float(len(segments))
    fractions = [acc / total for acc in accumulate(widths, initial=0.0)]
    return tuple(
        (seg.timing.start, seg.timing.end, fractions[i], fractions[i + 1])
        for i, seg in enumerate(segments)
    )


def _build_wave_paint(
    palette: _WavePalette,
    node: TextObject,
    scale: Vec2,
    y_top_line: float,
    y_height_line: float,
    italic: bool,
    segments_local: tuple[tuple[float, float, float, float], ...],
) -> ShaderPaint:
    y_top_local = (y_top_line - node.state.position.y) / scale.y
    y_height_local = max(y_height_line / scale.y, 1.0)
    angle = ITALIC_SLANT_DEG if italic else SWEEP_SLANT_DEG
    slant = tan(radians(angle)) * scale.y / scale.x
    em_local = max(node.font_size / scale.x, 1.0)
    border_local = node.state.border / scale.x
    inv_face_op = 1.0 / palette.base_face_opacity

    params: list[float] = [
        *_rgb_floats(palette.before_fill),
        *_rgb_floats(palette.after_fill),
        *_rgb_floats(palette.crest_fill),
        *_rgb_floats(palette.wake_fill),
        *_rgb_floats(palette.rim_outline),
        palette.before_alpha,
        palette.after_alpha,
        palette.outline_alpha,
        y_top_local,
        y_height_local,
        slant,
        em_local,
        palette.rim_strength,
        palette.crest_strength,
        border_local,
        inv_face_op,
        float(len(segments_local)),
        *_rgb_floats(palette.shadow_color),
    ]
    for t0, t1, x0, x1 in segments_local:
        params.extend((t0, t1, x0, x1))

    return ShaderPaint(
        source=WAVEFRONT_PAINT_SOURCE,
        parameters=tuple(params),
        functions=WAVEFRONT_FUNCTIONS,
    )


def _schedule_buoyancy(
    node: TextObject,
    height: float,
    raw_windows: list[tuple[float, float]],
) -> TextObject:
    if height <= 0.0 or not raw_windows:
        return node
    life_start = node.lifetime.start
    life_end = node.lifetime.end
    origin = node.time_origin
    cursor = life_start

    for raw_start, raw_end in sorted(raw_windows):
        start = max(cursor, raw_start)
        if start >= life_end - MIN_CLIP_SECONDS:
            break
        natural = max(raw_end - raw_start, 0.0) + LIFT_TAIL_SECONDS
        dur = max(LIFT_MIN_SECONDS, min(LIFT_MAX_SECONDS, natural))
        end = min(life_end, start + dur)
        actual_dur = end - start
        if actual_dur < MIN_CLIP_SECONDS:
            continue
        # Two bounded translations let the exporter cull the glyph outside
        # its measured travel, including at times between the endpoints.
        rest = node.state.position
        rise = actual_dur * LIFT_PEAK
        at = start - origin
        node = node.animate(
            Tween(StatePatch(position=rest + Vec2(0, -height)), smooth_rate),
            at=at, duration=rise,
        ).animate(
            Tween(StatePatch(position=rest), smooth_rate),
            at=at + rise, duration=actual_dur - rise,
        )
        cursor = end + 1e-4
    return node


def _decorate_line(
    line: LyricLine, palette: _WavePalette, style_italic: bool
) -> LyricLine:
    layout = line.layout
    body_top, body_height = _line_vertical_frame(layout.body.characters)

    # Map each glyph node_id -> (PositionedText, y_top, y_height, segments_line, char_windows)
    glyph_specs: dict[
        str,
        tuple[
            PositionedText,
            float,
            float,
            tuple[tuple[float, float, float, float], ...],
            list[tuple[float, float]],
            bool,
        ],
    ] = {}

    for unit_index, unit in enumerate(layout.lyrics.units):
        if unit.start == unit.end or not unit.segments:
            continue
        unit_box = layout.body.range_bounds(unit.start, unit.end)
        if unit_box.width <= 0.0:
            continue
        parts = _unit_segments(layout, unit_index)
        seg_line = tuple(
            (
                t0,
                t1,
                unit_box.left + unit_box.width * a,
                unit_box.left + unit_box.width * b,
            )
            for t0, t1, a, b in parts
        )
        for ch in layout.body.characters:
            if not (unit.start <= ch.start and ch.end <= unit.end):
                continue
            if not ch.object.text.strip():
                continue
            c_left = ch.bounds.left
            c_right = ch.bounds.right
            windows: list[tuple[float, float]] = []
            for t0, t1, sx0, sx1 in seg_line:
                span_w = sx1 - sx0
                if span_w <= 0.0:
                    continue
                if c_right <= sx0 or c_left >= sx1:
                    continue
                f0 = max(0.0, min(1.0, (c_left - sx0) / span_w))
                f1 = max(f0, min(1.0, (c_right - sx0) / span_w))
                dt = max(t1 - t0, 0.0)
                windows.append((t0 + dt * f0, t0 + dt * f1))
            if not windows and seg_line:
                windows.append((seg_line[0][0], seg_line[-1][1]))
            glyph_specs[ch.object.id] = (
                ch,
                body_top,
                body_height,
                seg_line,
                windows,
                False,
            )

    for ruby in layout.ruby:
        unit = layout.lyrics.units[ruby.unit_index]
        if ruby.segment_index >= len(unit.segments):
            continue
        span = unit.segments[ruby.segment_index].timing
        ruby_box = ruby.layout.bounds
        if ruby_box.width <= 0.0:
            continue
        r_top, r_height = _line_vertical_frame(ruby.layout.characters)
        seg_line = ((span.start, span.end, ruby_box.left, ruby_box.right),)
        for ch in ruby.layout.characters:
            if not ch.object.text.strip():
                continue
            f0 = max(0.0, min(1.0, (ch.bounds.left - ruby_box.left) / ruby_box.width))
            f1 = max(f0, min(1.0, (ch.bounds.right - ruby_box.left) / ruby_box.width))
            dt = max(span.end - span.start, 0.0)
            windows = [(span.start + dt * f0, span.start + dt * f1)]
            glyph_specs[ch.object.id] = (ch, r_top, r_height, seg_line, windows, True)

    def transform_node(node: SceneObject) -> SceneObject:
        if isinstance(node, ObjectGroup):
            return replace(
                node, children=tuple(transform_node(child) for child in node.children)
            )
        if not isinstance(node, TextObject):
            return node

        base_state = replace(
            node.state,
            fill=palette.before_fill,
            outline=palette.outline_color,
            face_opacity=palette.base_face_opacity,
        )
        updated = replace(node, state=base_state)
        spec = glyph_specs.get(node.id)
        if spec is None:
            return updated

        ch, y_top, y_height, seg_line, windows, is_ruby = spec
        scale = ch.layout_scale or Vec2(1.0, 1.0)
        # Measured bounds and the original pen share layout coordinates.
        # LyricLine reparents the drawing under its unit and changes its position.
        pen_x = ch.object.state.position.x
        origin = updated.time_origin
        segments_local = tuple(
            (
                t0 - origin,
                t1 - origin,
                (sx0 - pen_x) / scale.x,
                (sx1 - pen_x) / scale.x,
            )
            for t0, t1, sx0, sx1 in seg_line
        )
        italic = style_italic or updated.italic
        paint = _build_wave_paint(
            palette, ch.object, scale, y_top, y_height, italic, segments_local
        )
        updated = replace(updated, shader_paint=paint)
        lift_ratio = LIFT_RUBY_RATIO if is_ruby else LIFT_BODY_RATIO
        return _schedule_buoyancy(updated, updated.font_size * lift_ratio, windows)

    decorated = transform_node(line)
    assert isinstance(decorated, LyricLine)
    return decorated


def build_scene(ass: str, rows: FSLyricsData) -> Scene:
    """Build a seekable Hook Scene with the original meniscus-wavefront sweep."""
    doc = Document.parse(ass)
    scene = Scene(doc)
    styles = doc.styles
    if not any(name.startswith("Primary") for name in styles):
        return scene

    palettes = {
        name: _derive_wave_palette(style)
        for name, style in styles.items()
        if name != "Secondary"
    }

    row_index = 0
    for i, event in enumerate(doc.records):
        if not isinstance(event, Line) or event.comment:
            continue
        scene.replace_source(i)
        style = styles[event.style]
        secondary = event.style == "Secondary"
        if secondary:
            lyric = parse_document_lyrics(
                doc.text_at(i), start=event.start_time / 1000.0
            )
        else:
            if row_index >= len(rows):
                continue
            lyric = project_words(rows[row_index].words, style.name)
            row_index += 1
        if event.end_time <= event.start_time or not lyric.body.text.strip():
            continue
        layout = layout_lyrics(
            doc,
            lyric,
            id=f"desktop-{i}",
            ruby_gap=0,
            display=Lifetime(event.start_time / 1000.0, event.end_time / 1000.0),
        )
        position = Vec2(*body_origin(doc, style, layout.body.bounds))
        if secondary:
            scene.add(layout.body.group(position=position))
        else:
            line = _decorate_line(
                LyricLine.from_layout(layout),
                palettes[style.name],
                bool(style.italic),
            )
            scene.add(replace(line, state=replace(line.state, position=position)))
    return scene
