#!/usr/bin/env python3
"""Generate the layrics app icon (SVG) — karaoke lyric overlay on a circular blue gradient.

Concept:
  - circular blue gradient plate = the wlr-layer-shell overlay window on the desktop
  - eighth note (left)           = music / lyrics (gradient notehead)
  - karaoke bar (below)          = ASS \\k karaoke fill: orange→red gradient sung segment
                                   + cursor, remaining lyric in translucent blue bar

Usage:
  python3 scripts/make_icon.py [--fg #ffffff] [--unsung #a9d0f5]
                               [--bg-top #12284a] [--bg-bottom #2a6dc0]
                               [--accent-top #ffab40] [--accent-bottom #ff4757]
                               [--out assets/icon.svg] [--png 256]
                               # --bg-top none for transparent background
"""

import argparse
import subprocess
from pathlib import Path

S = 256  # canvas size

INNER_R = 112      # inner ring radius (16px from the circular edge)
STROKE = 10         # line weight (minimal line style)

NOTE_HEAD = (72, 124)  # notehead center
STEM_X = 89            # stem x
LYRIC_Y = 172          # lyric line center
LYRIC_X1, LYRIC_X2 = 72, 184
FILL_W = 52            # karaoke filled segment width
BAR_H = 12             # filled segment height
CURSOR_H = 28          # karaoke cursor height (sticks above/below bar)


CURSOR_H = 28          # karaoke cursor height (sticks above/below bar)


def mix_hex(a: str, b: str, t: float) -> str:
    """Linear mix of two hex colors at ratio t (0..1)."""
    ca = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    c = [round(x + (y - x) * t) for x, y in zip(ca, cb)]
    return "#" + "".join(f"{v:02x}" for v in c)


def svg(fg: str, unsung: str, bg_top: str, bg_bottom: str, accent_top: str, accent_bottom: str) -> str:
    parts = []
    note_end = mix_hex(fg, unsung, 0.6)  # notehead gradient end (white → light blue)
    defs = (
        '<defs>'
        f'<linearGradient id="acc" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="{accent_top}"/>'
        f'<stop offset="1" stop-color="{accent_bottom}"/>'
        '</linearGradient>'
        f'<linearGradient id="nt" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{fg}"/>'
        f'<stop offset="1" stop-color="{note_end}"/>'
        '</linearGradient>'
    )
    if bg_top != "none":
        mid = mix_hex(bg_top, bg_bottom, 0.55)
        defs += (
            f'<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{bg_top}"/>'
            f'<stop offset="0.55" stop-color="{mid}"/>'
            f'<stop offset="1" stop-color="{bg_bottom}"/>'
            '</linearGradient>'
        )
        parts.append(defs + '</defs>')
        parts.append(f'<circle cx="{S // 2}" cy="{S // 2}" r="{S // 2}" fill="url(#bg)"/>')
    else:
        parts.append(defs + '</defs>')
    # 1. inner ring (subtle)
    parts.append(
        f'<circle cx="{S // 2}" cy="{S // 2}" r="{INNER_R}" '
        f'stroke="{fg}" stroke-opacity="0.3" stroke-width="{STROKE}" fill="none"/>'
    )
    # 2. eighth note: solid head + line stem/flag
    cx, cy = NOTE_HEAD
    parts.append(
        f'<g stroke="{fg}" stroke-width="{STROKE}" stroke-linecap="round" '
        f'stroke-linejoin="round">'
        f'<ellipse cx="{cx}" cy="{cy}" rx="17" ry="12" transform="rotate(-20 {cx} {cy})" fill="url(#nt)"/>'
        f'<path d="M {STEM_X} {cy - 1} V 76" fill="none"/>'
        f'<path d="M {STEM_X} 76 C 114 80 122 96 110 114" fill="none"/>'
        f'</g>'
    )
    # 3. karaoke bar: un-sung translucent bar + gradient sung segment + cursor
    fy = LYRIC_Y - BAR_H // 2
    parts.append(
        f'<g stroke-linecap="round">'
        f'<rect x="{LYRIC_X1}" y="{fy}" width="{LYRIC_X2 - LYRIC_X1}" height="{BAR_H}" '
        f'rx="{BAR_H // 2}" fill="{unsung}" fill-opacity="0.5"/>'
        f'<rect x="{LYRIC_X1}" y="{fy}" width="{FILL_W}" height="{BAR_H}" '
        f'rx="{BAR_H // 2}" fill="url(#acc)"/>'
        f'<line x1="{LYRIC_X1 + FILL_W}" y1="{LYRIC_Y - CURSOR_H // 2}" '
        f'x2="{LYRIC_X1 + FILL_W}" y2="{LYRIC_Y + CURSOR_H // 2}" '
        f'stroke="{accent_top}" stroke-width="{STROKE}"/>'
        f'</g>'
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" '
        f'width="{S}" height="{S}">'
        f'{"".join(parts)}\n</svg>\n'
    )


def render_png(svg_path: Path, png_path: Path, size: int) -> None:
    subprocess.run(
        ["rsvg-convert", "-w", str(size), "-h", str(size), "-o", str(png_path), str(svg_path)],
        check=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="layrics icon generator")
    ap.add_argument("--fg", default="#ffffff", help="foreground color (notehead, frame)")
    ap.add_argument("--unsung", default="#a9d0f5", help="un-sung lyric bar color")
    ap.add_argument("--bg-top", default="#12284a", help="background gradient top (none = transparent)")
    ap.add_argument("--bg-bottom", default="#2a6dc0", help="background gradient bottom")
    ap.add_argument("--accent-top", default="#ffab40", help="karaoke gradient start (orange)")
    ap.add_argument("--accent-bottom", default="#ff4757", help="karaoke gradient end (red)")
    ap.add_argument("--out", default="assets/icon.svg", help="output SVG path")
    ap.add_argument("--png", type=int, default=0, help="also render PNG at this size (needs rsvg-convert)")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg(args.fg, args.unsung, args.bg_top, args.bg_bottom,
                       args.accent_top, args.accent_bottom))

    if args.png:
        png = out.with_suffix(".png")
        render_png(out, png, args.png)
        print(f"wrote {out} and {png}")
    else:
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
