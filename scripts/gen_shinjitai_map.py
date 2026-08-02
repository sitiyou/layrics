#!/usr/bin/env python3
"""Generate layrics/data/simplified_to_shinjitai.json.

Builds a simplified-Chinese → Japanese shinjitai character map from the
Unicode Unihan_Variants database:

  1. Download Unihan.zip from unicode.org, extract Unihan_Variants.txt
  2. Parse kTraditionalVariant: simplified → traditional/old glyphs
  3. Parse kSimplifiedVariant in reverse: traditional/old glyphs → shinjitai
     (a character whose kSimplifiedVariant is some traditional glyph is a
      shinjitai/simplified-Japanese form of that glyph)
  4. Cascade simplified → traditional → shinjitai, skipping identity mapping
  5. Apply manual overrides for frequent chars missing from the variant chain

Usage:
  python3 scripts/gen_shinjitai_map.py [--out layrics/data/simplified_to_shinjitai.json]

By default entries whose key is encodable in Shift-JIS are dropped (those
glyphs already exist in Japanese fonts and need no conversion); pass
--keep-shift-jis to keep them.
"""

import argparse
import json
import tempfile
import urllib.request
import zipfile
from pathlib import Path

UNIHAN_ZIP_URL = "https://www.unicode.org/Public/UNIDATA/Unihan.zip"
VARIANTS_FILE = "Unihan_Variants.txt"

# Manual overrides: frequent chars whose simplified→shinjitai link is not
# derivable via the Unihan variant chain (or maps to the wrong glyph).
MANUAL_OVERRIDES = {
    "关": "関", "国": "国", "铁": "鉄", "发": "発", "转": "転",
    "对": "対", "广": "広", "双": "双", "写": "写", "乐": "楽",
    "应": "応", "显": "顕", "严": "厳", "带": "帯", "图": "図",
}

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "layrics" / "data" / "simplified_to_shinjitai.json"


def fetch_unihan_variants(tmpdir: Path) -> Path:
    """Download Unihan.zip and return the extracted Unihan_Variants.txt path."""
    zip_path = tmpdir / "Unihan.zip"
    print(f"Downloading {UNIHAN_ZIP_URL} ...")
    urllib.request.urlretrieve(UNIHAN_ZIP_URL, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extract(VARIANTS_FILE, tmpdir)
    return tmpdir / VARIANTS_FILE


def u_to_char(u_str: str) -> str:
    """Convert a Unicode codepoint field like 'U+4E00<kMatters' to the character."""
    code_point = u_str.split("<")[0].strip()  # drop variant remarks
    return chr(int(code_point.replace("U+", ""), 16))


def parse_unihan_variants(variants_path: Path) -> dict[str, str]:
    """Parse the variants database into a simplified → shinjitai map."""
    simp_to_trad: dict[str, list[str]] = {}
    trad_to_shinjitai: dict[str, list[str]] = {}

    with open(variants_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            if len(parts) < 3:
                continue

            src_char = u_to_char(parts[0])
            tag = parts[1]
            targets = [u_to_char(p) for p in parts[2].split()]

            if tag == "kTraditionalVariant":
                # simplified → traditional/old glyphs
                simp_to_trad[src_char] = targets
            elif tag == "kSimplifiedVariant":
                # reverse: traditional/old glyphs → shinjitai forms
                for trad in targets:
                    trad_to_shinjitai.setdefault(trad, []).append(src_char)

    # Cascade: simplified → traditional → shinjitai
    s2jp_map: dict[str, str] = {}
    for simp_char, trad_list in simp_to_trad.items():
        for trad_char in trad_list:
            for jp_char in trad_to_shinjitai.get(trad_char, []):
                # skip identity mapping (e.g. 关 → 關 → 関 keeps 关 → 関)
                if simp_char != jp_char:
                    s2jp_map[simp_char] = jp_char

    s2jp_map.update(MANUAL_OVERRIDES)
    return s2jp_map


def in_shift_jis(ch: str) -> bool:
    """Return True if the character is encodable in Shift-JIS."""
    try:
        ch.encode("shift_jis")
        return True
    except UnicodeEncodeError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output JSON path (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--keep-shift-jis",
        action="store_true",
        help="keep entries whose key is encodable in Shift-JIS",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="shinjitai_") as tmpdir:
        variants_path = fetch_unihan_variants(Path(tmpdir))
        s2jp_map = parse_unihan_variants(variants_path)

    if not args.keep_shift_jis:
        s2jp_map = {k: v for k, v in s2jp_map.items() if not in_shift_jis(k)}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(s2jp_map, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Generated {len(s2jp_map)} simplified→shinjitai mappings -> {args.out}")


if __name__ == "__main__":
    main()
