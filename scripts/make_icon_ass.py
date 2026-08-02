#!/usr/bin/env python3
"""Generate the layrics app icon with libass — a karaoke ♪ (U+266A) on a blue
gradient circle.

The note glyph is rendered by libass directly (see render_note.c) with a \\K
karaoke fill: the ♪ is filled left→right from an un-sung translucent blue state
to a sung orange-red state.

Composition:
  - circular blue gradient background (SVG → rsvg-convert)
  - centered karaoke ♫ (libass, progress = --progress)
  - optional subtle inner ring

Usage:
  python3 scripts/make_icon_ass.py [--size 512] [--progress 0.5]
                                   [--accent #FF6B4F] [--unsung #C9E2F3]
                                   [--outline #F3E2C9] [--bg-top #12284a]
                                   [--bg-bottom #2a6dc0] [--out assets/icon.png]
Requires: gcc + pkg-config (libass, cairo), rsvg-convert, ImageMagick.
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

NOTE = "\u266A"  # ♪ eighth note


def mix_hex(a: str, b: str, t: float) -> str:
    """Linear mix of two hex colors at ratio t (0..1)."""
    ca = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    c = [round(x + (y - x) * t) for x, y in zip(ca, cb)]
    return "#" + "".join(f"{v:02x}" for v in c)


def ass_color(rgb: str, alpha: int = 0x00) -> str:
    """'#RRGGBB' (+transparency 0..255) → ASS &HAABBGGRR value (no &H prefix)."""
    r, g, b = (int(rgb.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return f"{alpha:02X}{b:02X}{g:02X}{r:02X}"


_ASS_TPL = r"""[Script Info]
ScriptType: v4.00+
PlayResX: 512
PlayResY: 512
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Note,sans-serif,__FONTSIZE__,&H00FFFFFF,&H00000000,&H__UNSUNG_OUTLINE__,&H00000000,0,0,0,0,100,100,0,0,1,10,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:02.00,Note,,0,0,0,,{\an5\shad0}__NOTE__
Dialogue: 1,0:00:00.00,0:00:02.00,Note,,0,0,0,,{\an5\shad0\1c&H__ACCENT__&\3c&H__ACCENT_OUTLINE__&\clip(__CLIP_PATH__)}__NOTE__
"""


def clip_path_45(progress: float) -> str:
    """45° diagonal clip path (PlayRes 512): sung region = top-left of the
    line y = -x + c (i.e. x + y <= c). The line runs top-right ↔ bottom-left,
    sweeping across the ♪ ink bbox as progress goes 0→1. Simple polygon
    (no self-intersection, required by nonzero-winding).
    """
    c = 273 + 495 * progress  # p=0 → ♪ top-left corner, p=1 → bottom-right
    if c <= 512:
        # line x+y=c crosses top edge (c,0) and left edge (0,c): top-left triangle
        return f"m 0 0 l {c:.1f} 0 l 0 {c:.1f}"
    # line crosses right edge (512,c-512) and bottom edge (c-512,512)
    return f"m 0 0 l 0 512 l {c - 512:.1f} 512 l 512 {c - 512:.1f} l 512 0"


def write_ass(path: Path, accent: str, accent_outline: str, unsung: str,
              unsung_outline: str, fontsize: int, progress: float) -> None:
    """Two-layer karaoke: bottom = un-sung note, top = sung note clipped by a
    45° diagonal (refs/ass-renderer/test.ass vector-clip technique).

    Placeholders are substituted with str.replace to avoid f-string brace
    escaping (ASS override blocks use many literal {}).
    """
    vals = {
        "__FONTSIZE__": str(fontsize),
        "__ACCENT__": ass_color(accent),
        "__ACCENT_OUTLINE__": ass_color(accent_outline),
        "__UNSUNG__": ass_color(unsung),
        "__UNSUNG_OUTLINE__": ass_color(unsung_outline),
        "__CLIP_PATH__": clip_path_45(progress),
        "__NOTE__": NOTE,
    }
    text = _ASS_TPL
    for k, v in vals.items():
        text = text.replace(k, v)
    path.write_text(text)


def build_renderer(build_dir: Path) -> Path:
    """Compile scripts/render_note.c → <build_dir>/render_note."""
    src = Path(__file__).parent / "render_note.c"
    exe = build_dir / "render_note"
    cflags = subprocess.run(["pkg-config", "--cflags", "libass", "cairo"],
                            capture_output=True, text=True, check=True).stdout.split()
    libs = subprocess.run(["pkg-config", "--libs", "libass", "cairo"],
                          capture_output=True, text=True, check=True).stdout.split()
    subprocess.run(["gcc", "-O2", str(src), "-o", str(exe), *cflags, *libs],
                   check=True)
    return exe


def render_note(exe: Path, ass_path: Path, png_path: Path, progress: float,
                size: int) -> None:
    """Render the karaoke note frame via libass (transparent bg)."""
    time_ms = int(progress * 1000)  # \\K100 = 1s → progress 0..1 maps to ms
    subprocess.run([str(exe), str(ass_path), str(png_path),
                    str(size), str(size), str(time_ms)], check=True)


def render_bg(svg_path: Path, png_path: Path, bg_top: str, bg_bottom: str,
              ring_opacity: float, ring_width: int, size: int) -> None:
    mid = mix_hex(bg_top, bg_bottom, 0.55)
    svg_path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" '
        f'width="{size}" height="{size}">'
        "<defs>"
        '<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{bg_top}"/>'
        f'<stop offset="0.55" stop-color="{mid}"/>'
        f'<stop offset="1" stop-color="{bg_bottom}"/>'
        "</linearGradient>"
        "</defs>"
        f'<circle cx="256" cy="256" r="256" fill="url(#bg)"/>'
        + (
            f'<circle cx="256" cy="256" r="238" stroke="#ffffff" '
            f'stroke-opacity="{ring_opacity}" stroke-width="{ring_width}" fill="none"/>'
            if ring_opacity > 0 else ""
        )
        + "</svg>\n"
    )
    subprocess.run(
        ["rsvg-convert", "-w", str(size), "-h", str(size),
         "-o", str(png_path), str(svg_path)],
        check=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="layrics libass icon generator")
    ap.add_argument("--size", type=int, default=512, help="output size (px)")
    ap.add_argument("--progress", type=float, default=0.5,
                    help="karaoke fill progress 0..1 (0.5 = half sung)")
    ap.add_argument("--fontsize", type=int, default=380, help="♪ font size")
    ap.add_argument("--accent", default="#FF6B4F", help="sung fill color")
    ap.add_argument("--accent-outline", default="#F3E2C9", help="sung outline color")
    ap.add_argument("--unsung", default="#FFFFFF", help="un-sung fill color")
    ap.add_argument("--unsung-outline", default="#505050", help="un-sung outline color")
    ap.add_argument("--bg-top", default="#12284a", help="bg gradient top")
    ap.add_argument("--bg-bottom", default="#2a6dc0", help="bg gradient bottom")
    ap.add_argument("--ring", type=float, default=0.15,
                    help="inner ring opacity (0 = none)")
    ap.add_argument("--ring-width", type=int, default=12,
                    help="inner ring stroke width (px)")
    ap.add_argument("--out", default="assets/icon.png", help="output PNG path")
    ap.add_argument("--keep", action="store_true", help="keep temp files")
    args = ap.parse_args()
    assert 0 <= args.progress <= 1, "--progress must be in [0, 1]"

    tmp = Path(tempfile.mkdtemp(prefix="layrics_icon_"))
    try:
        ass = tmp / "note.ass"
        note_png = tmp / "note.png"
        bg_svg, bg_png = tmp / "bg.svg", tmp / "bg.png"
        write_ass(ass, args.accent, args.accent_outline, args.unsung,
                  args.unsung_outline, args.fontsize, args.progress)
        exe = build_renderer(tmp)
        render_note(exe, ass, note_png, args.progress, args.size)
        render_bg(bg_svg, bg_png, args.bg_top, args.bg_bottom, args.ring,
                  args.ring_width, args.size)

        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["magick", str(bg_png), str(note_png), "-composite", str(out)],
            check=True,
        )
        print(f"wrote {out} ({args.size}x{args.size}, karaoke progress {args.progress})")
        if args.keep:
            print(f"temp files in {tmp}")
    finally:
        if not args.keep:
            subprocess.run(["rm", "-rf", str(tmp)], check=False)


if __name__ == "__main__":
    main()
