#!/usr/bin/env python3
"""Generate layrics/data/simplified_to_shinjitai.json.

Builds a simplified-Chinese → Japanese character map:

  1. Download Unihan.zip from unicode.org; extract Unihan_Variants.txt and
     Unihan_IRGSources.txt
  2. Unihan kTraditionalVariant: simplified → traditional/old glyph roots
  3. kIRG_JSource (J0/J1/J3/J4) defines the Japanese standard glyph repertoire
  4. OpenCC JPShinjitaiCharacters.txt (kyūjitai → shinjitai, honoring its
     @reverse-prefer directives) supplies the new-form side. Unihan itself
     never records the Japanese simplification relation, so this curated
     table (Apache-2.0) is required
  5. For each simplified char the candidates are its traditional roots that
     are also Japanese standard glyphs plus the shinjitai of those roots.
     A single candidate wins; otherwise the OpenCC STCharacters chain (the
     Option A reference) breaks the tie, and hand-curated exceptions cover
     what the generic rules get wrong
  6. Option-A entries that Unihan misses entirely (no kTraditionalVariant,
     e.g. 勋/焰/藴) are adopted when the simplified char is not itself a
     Japanese repertoire glyph and the target is encodable in a Japanese font
  7. Entries whose key is encodable in Shift-JIS are dropped, as those glyphs
     already exist in Japanese fonts; pass --keep-shift-jis to keep them

Usage:
  python3 scripts/gen_shinjitai_map.py [--out layrics/data/simplified_to_shinjitai.json]
                                        [--opencc-dir PATH]
  --opencc-dir points at an OpenCC checkout containing data/dictionary/ so
  the generator can run fully offline.
"""

import argparse
import json
import tempfile
import urllib.request
import zipfile
from pathlib import Path

UNIHAN_ZIP_URL = "https://www.unicode.org/Public/UNIDATA/Unihan.zip"
VARIANTS_FILE = "Unihan_Variants.txt"
IRG_FILE = "Unihan_IRGSources.txt"
OPENCC_DIR_URLS = (
    "https://raw.githubusercontent.com/BYVoid/OpenCC/master/data/dictionary",
    "https://cdn.jsdelivr.net/gh/BYVoid/OpenCC@master/data/dictionary",
)
SHINJITAI_FILE = "JPShinjitaiCharacters.txt"
ST_CHARS_FILE = "STCharacters.txt"

# Hand-curated overrides for characters whose Unihan/OpenCC data picks a
# non-standard Japanese glyph.
EXCEPTIONS = {
    "净": "浄",  # Unihan root is a stroke variant; the Japanese standard is 浄
    "娴": "嫺",  # keep the primary traditional 嫺 over the 嫻 variant
    "谥": "諡",  # 諡 is the standard form, 謚 a variant
    "鉴": "鑑",  # 鑑 (鑑賞) is the Japanese standard, 鑒 an older variant
    "锈": "鏽",  # 鏽 is the standard traditional form, 銹 a variant
    "竖": "竪",  # 竪 (竪琴) is the Japanese standard, 豎 Chinese-only
}

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "layrics" / "data" / "simplified_to_shinjitai.json"


def u_to_char(u_str: str) -> str:
    """Convert a Unicode codepoint field like 'U+4E00<kMatters' to the character."""
    code_point = u_str.split("<")[0].strip()  # drop variant remarks
    return chr(int(code_point.replace("U+", ""), 16))


def fetch_unihan(tmpdir: Path) -> tuple[Path, Path]:
    """Download Unihan.zip and return the variants and IRG source paths."""
    zip_path = tmpdir / "Unihan.zip"
    print(f"Downloading {UNIHAN_ZIP_URL} ...")
    urllib.request.urlretrieve(UNIHAN_ZIP_URL, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extract(VARIANTS_FILE, tmpdir)
        zf.extract(IRG_FILE, tmpdir)
    return tmpdir / VARIANTS_FILE, tmpdir / IRG_FILE


def fetch_opencc_dict(tmpdir: Path, name: str) -> Path:
    """Download one OpenCC dictionary file, falling back across mirrors."""
    for base in OPENCC_DIR_URLS:
        url = f"{base}/{name}"
        try:
            print(f"Downloading {url} ...")
            dest = tmpdir / name
            urllib.request.urlretrieve(url, dest)
            if dest.stat().st_size > 0:
                return dest
        except Exception as e:
            print(f"warning: {url} failed ({e})")
    raise SystemExit(
        f"cannot fetch {name}; pass --opencc-dir with an OpenCC checkout"
    )


def get_opencc_dicts(tmpdir: Path, opencc_dir: Path | None) -> tuple[Path, Path]:
    if opencc_dir is not None:
        d = opencc_dir / "data" / "dictionary"
        return d / SHINJITAI_FILE, d / ST_CHARS_FILE
    return (
        fetch_opencc_dict(tmpdir, SHINJITAI_FILE),
        fetch_opencc_dict(tmpdir, ST_CHARS_FILE),
    )


def parse_traditional_variants(variants_path: Path) -> dict[str, list[str]]:
    """Parse Unihan kTraditionalVariant into simplified → traditional roots."""
    trad: dict[str, list[str]] = {}
    with open(variants_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            if len(parts) < 3 or parts[1] != "kTraditionalVariant":
                continue
            trad.setdefault(u_to_char(parts[0]), []).extend(
                u_to_char(t) for t in parts[2].split()
            )
    return trad


def parse_jis_sources(irg_path: Path) -> set[str]:
    """Chars whose kIRG_JSource is J0/J1/J3/J4 = the Japanese standard repertoire."""
    jset: set[str] = set()
    with open(irg_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            if len(parts) < 3 or parts[1] != "kIRG_JSource":
                continue
            if any(v.startswith(("J0-", "J1-", "J3-", "J4-")) for v in parts[2].split()):
                jset.add(u_to_char(parts[0]))
    return jset


def parse_shinjitai(path: Path) -> dict[str, str]:
    """Parse JPShinjitaiCharacters.txt (shinjitai → kyūjitai) into kyūjitai → shinjitai.

    The file's commented `@reverse-prefer` directives pick the primary
    shinjitai when several map to the same kyūjitai (e.g. 塩 over 䀋 for 鹽).
    """
    prefer: dict[str, str] = {}
    table: dict[str, list[str]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if "@reverse-prefer" in line:
                    arts = line.lstrip("#").strip().split(":", 1)[1].split()
                    prefer[arts[0]] = arts[1]
                continue
            key, _, values = line.partition("\t")
            table[key] = values.split()
    reverse: dict[str, str] = {}
    for shin, olds in table.items():
        for old in olds:
            if old in prefer:
                reverse[old] = prefer[old]
            else:
                reverse.setdefault(old, shin)
    return reverse


def parse_st_characters(path: Path) -> dict[str, list[str]]:
    """Parse OpenCC STCharacters.txt (simplified → traditional, primary first)."""
    table: dict[str, list[str]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, values = line.partition("\t")
            table[key] = values.split()
    return table


def build_map(
    trad: dict[str, list[str]],
    jset: set[str],
    shin: dict[str, str],
    st: dict[str, list[str]],
) -> tuple[dict[str, str], list[str]]:
    """Build the simplified → Japanese map.

    For each simplified char the candidates are its traditional roots that
    are themselves Japanese standard glyphs, plus the shinjitai of those
    roots. A single candidate wins; otherwise the OpenCC STCharacters chain
    breaks the tie; entries still undecided fall back deterministically to
    the lowest codepoint and are returned for review.
    """
    # Option A reference: STCharacters primary traditional → shinjitai
    a_ref: dict[str, str] = {}
    for s, roots in st.items():
        target = shin.get(roots[0], roots[0])
        if s != target:
            a_ref[s] = target

    s2jp: dict[str, str] = {}
    undecided: list[str] = []
    for s, roots in trad.items():
        cands: dict[str, str] = {}
        for r in roots:
            if r in jset and r != s:
                cands[r] = "self"
            j = shin.get(r)
            if j and j != r and j != s:
                cands[j] = "shin"
        if not cands:
            continue
        shin_cands = [c for c, tag in cands.items() if tag == "shin"]
        if len(cands) == 1:
            pick = next(iter(cands))
        elif len(shin_cands) == 1:
            pick = shin_cands[0]
        elif a_ref.get(s) in cands:
            pick = a_ref[s]
        else:
            pick = min(cands, key=ord)
            undecided.append(s)
        if pick != s:
            s2jp[s] = pick

    s2jp.update(EXCEPTIONS)

    # Simplified chars that only OpenCC knows (no kTraditionalVariant in
    # Unihan): adopt the OpenCC target, unless the key is itself a Japanese
    # repertoire glyph (leave those untouched) or the target is not a glyph
    # an actual Japanese font contains.
    for s, target in a_ref.items():
        if s not in s2jp and s not in jset and in_jp_font(target):
            s2jp[s] = target
    return s2jp, undecided


def in_jp_font(ch: str) -> bool:
    """True if ch is encodable in a Japanese font repertoire.

    Python's shift_jis codec omits part of JIS X 0208 level 2, so also probe
    euc_jp (full JIS X 0208), shift_jis_2004 (JIS X 0213) and cp932.
    """
    for codec in ("euc_jp", "shift_jis_2004", "cp932"):
        try:
            ch.encode(codec)
            return True
        except UnicodeEncodeError:
            continue
    return False


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
    parser.add_argument(
        "--opencc-dir",
        type=Path,
        default=None,
        help="OpenCC checkout with data/dictionary/ (offline mode)",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="shinjitai_") as tmp:
        tmpdir = Path(tmp)
        variants_path, irg_path = fetch_unihan(tmpdir)
        shinjitai_path, st_path = get_opencc_dicts(tmpdir, args.opencc_dir)

        trad = parse_traditional_variants(variants_path)
        jset = parse_jis_sources(irg_path)
        shin = parse_shinjitai(shinjitai_path)
        st = parse_st_characters(st_path)

        s2jp, undecided = build_map(trad, jset, shin, st)

    if not args.keep_shift_jis:
        s2jp = {k: v for k, v in s2jp.items() if not in_shift_jis(k)}

    s2jp = dict(sorted(s2jp.items(), key=lambda kv: ord(kv[0])))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(s2jp, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Generated {len(s2jp)} simplified→Japanese mappings -> {args.out}")
    bmp_undecided = sorted(
        (s for s in undecided if s in s2jp and ord(s) < 0x2FFFF), key=ord
    )
    if bmp_undecided:
        print("NOTE: {} entries picked by codepoint tie-break (review):".format(len(bmp_undecided)))
        for s in bmp_undecided:
            print(f"  {s} -> {s2jp[s]}")


if __name__ == "__main__":
    main()