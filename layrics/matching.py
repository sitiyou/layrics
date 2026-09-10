from __future__ import annotations

import logging
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from .player import TrackMeta

logger = logging.getLogger("layrics.match")

TITLE_MIN_SIMILARITY = 0.6
DURATION_MAX_DIFF_SEC = 5

# ── character normalization map ──────────────────────────────────────
# Key: ordinal, Value: replacement string
CHAR_MAP = {
    # wave dashes → ~
    0x301C: "~",  # 〜 WAVE DASH
    0x223C: "~",  # ∼ TILDE OPERATOR
    0x223E: "~",  # ∾ INVERTED LAZY S
    0x3030: "~",  # 〰 WAVY DASH
    # dashes → -
    0x2010: "-",  # ‐ HYPHEN
    0x2011: "-",  # ‑ NON-BREAKING HYPHEN
    0x2012: "-",  # ‒ FIGURE DASH
    0x2013: "-",  # – EN DASH
    0x2014: "-",  # — EM DASH
    0x2015: "-",  # ― HORIZONTAL BAR
    0x2212: "-",  # − MINUS SIGN
    # Japanese brackets → "
    0x300C: '"',  # 「
    0x300D: '"',  # 」
    0x300E: '"',  # 『
    0x300F: '"',  # 』
    0x3014: '"',  # 〔
    0x3015: '"',  # 〕
    # spaces
    0x3000: " ",  # ideographic space
    0x00A0: " ",  # no-break space
}

# ── annotation keywords ──────────────────────────────────────────────
ANNOT_KEYWORDS = [
    "inst",
    "instrumental",
    "feat",
    "ft",
    "featuring",
    "live",
    "remix",
    "cover",
    "demo",
    "edit",
    "acoustic",
    "off vocal",
    "offvocal",
    "karaoke",
    "ver",
    "version",
    "tv.size",
    "tv size",
    "radio.edit",
    "radio edit",
    "solo",
    "reprise",
    "intro",
    "outro",
    "bonus.track",
    "bonus track",
    "single.version",
    "single version",
    "album.version",
    "album version",
    "original.mix",
    "original mix",
    "extended",
    "extended.mix",
    "extended mix",
    "インスト",
    "オフヴォーカル",
    "オフボーカル",
    "カラオケ",
    "ライブ",
    "リミックス",
    "カバー",
    "デモ",
    "アコースティック",
    "テレビサイズ",
]

KEYWORD_OR = "|".join(ANNOT_KEYWORDS)

ANNOT_RE = re.compile(
    r"(?:"
    r"\([^)]*(?:" + KEYWORD_OR + r")[^)]*\)"
    r"|\[[^\]]*(?:" + KEYWORD_OR + r")[^\]]*\]"
    r"|【[^】]*(?:" + KEYWORD_OR + r")[^】]*】"
    r"|〈[^〉]*(?:" + KEYWORD_OR + r")[^〉]*〉"
    r")",
    re.IGNORECASE,
)

# wavy-delimited annotations: e.g. 〜2025ver〜
WAVY_ANNOT_RE = re.compile(
    r"[~〜][^~〜]*(?:" + KEYWORD_OR + r")[^~〜]*[~〜]",
    re.IGNORECASE,
)

TRACK_PREFIX_RE = re.compile(r"^\d+[.．\-\)\s]+")


# ── normalization ────────────────────────────────────────────────────


def normalize_title(title: str) -> str:
    s = unicodedata.normalize("NFKC", title)
    s = s.translate(CHAR_MAP)
    s = ANNOT_RE.sub("", s)
    s = WAVY_ANNOT_RE.sub("", s)
    s = TRACK_PREFIX_RE.sub("", s)
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


BRACKET_PAIRS = [("(", ")"), ("[", "]"), ("【", "】"), ("〈", "〉")]
ANNOT_KEYWORDS_LONGEST = sorted(ANNOT_KEYWORDS, key=len, reverse=True)


def clean_search_keyword(keyword: str) -> str:
    """Strip annotation keywords from search keywords, keeping the rest.

    ``Mayday (feat. Laura Brehm) TheFatRat`` → ``Mayday Laura Brehm TheFatRat``
    ``Lemon (cover)`` → ``Lemon``
    """
    kw = keyword
    for lb, rb in BRACKET_PAIRS:
        pat = re.compile(
            re.escape(lb) + r"([^" + re.escape(rb) + r"]*)" + re.escape(rb)
        )

        def _strip(m: re.Match) -> str:
            inner = m.group(1)
            if not any(
                re.search(r"\b" + re.escape(k) + r"\b", inner, re.IGNORECASE)
                for k in ANNOT_KEYWORDS_LONGEST
            ):
                return m.group(0)
            for k in ANNOT_KEYWORDS_LONGEST:
                inner = re.sub(
                    r"\b" + re.escape(k) + r"\.?\s*", "", inner, flags=re.IGNORECASE
                )
            inner = re.sub(r"\s+", " ", inner).strip(" ,、.")
            return inner

        kw = pat.sub(_strip, kw)
    kw = re.sub(r"\s+", " ", kw).strip()
    parts = kw.split(" ")
    seen: set[str] = set()
    deduped: list[str] = []
    for p in parts:
        pl = p.lower()
        if pl not in seen:
            seen.add(pl)
            deduped.append(p)
    return " ".join(deduped)


# ── similarity helpers ───────────────────────────────┐


def _title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if shorter in longer:
        return 0.95
    return SequenceMatcher(None, shorter, longer).ratio()


def _artist_similarity(local: list[str], remote: list[str]) -> float:
    if not local or not remote:
        return 0.0
    best = 0.0
    for la in local:
        for ra in remote:
            ratio = SequenceMatcher(None, la, ra).ratio()
            best = max(best, ratio)
    return best


# ── matching ─────────────────────────────────────────────────────────


def _composite_id(c: dict[str, Any]) -> str:
    """Render a candidate as ``SourceID`` (e.g. ``QM213837399``) for logs."""
    return f"{c.get('source', '?')}{c.get('id', '?')}"


def match_song(
    meta: TrackMeta,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not meta.title or not candidates:
        return None

    q_title = normalize_title(meta.title)
    q_duration_s = (meta.length or 0) / 1_000_000  # μs → s
    q_artists = [normalize_title(a) for a in (meta.artists or [])]

    # Try stripping known artist prefix from both query and candidate
    def _with_artist_stripped(title_norm: str) -> str:
        for art in q_artists:
            if title_norm.startswith(art):
                rest = title_norm[len(art) :].lstrip("-–—~ ")
                if rest:
                    return rest
        return title_norm

    q_title = _with_artist_stripped(q_title)

    scored: list[tuple[float, float, float, dict[str, Any]]] = []

    for c in candidates:
        c_title = normalize_title(c.get("title") or "")
        c_title = _with_artist_stripped(c_title)
        c_duration_s = (c.get("duration") or 0) / 1000  # ms → s
        c_artists = [normalize_title(a) for a in (c.get("artist") or [])]

        # Stage 1: title similarity
        title_score = _title_similarity(q_title, c_title)
        if title_score < TITLE_MIN_SIMILARITY:
            continue

        # Stage 2: duration check
        dur_diff = 999999.0
        if (
            q_duration_s is not None
            and q_duration_s > 0
            and c_duration_s
            and c_duration_s > 0
        ):
            dur_diff = abs(q_duration_s - c_duration_s)
            if dur_diff > DURATION_MAX_DIFF_SEC:
                logger.info(
                    "  skip %s: title=%.3f OK but duration diff=%.1fs > %ds",
                    _composite_id(c),
                    title_score,
                    dur_diff,
                    DURATION_MAX_DIFF_SEC,
                )
                continue

        # Stage 3: artist bonus
        artist_score = _artist_similarity(q_artists, c_artists)

        logger.debug(
            "  candidate %s: title=%.3f dur_diff=%.1fs artist=%.2f",
            _composite_id(c),
            title_score,
            dur_diff,
            artist_score,
        )
        scored.append((title_score, dur_diff, artist_score, c))

    if not scored:
        return None

    scored.sort(key=lambda x: (-x[0], -x[2], x[1]))
    best = scored[0]
    best_c = best[3]

    logger.info(
        "match: pick %s (title=%.3f dur_diff=%.1fs artist=%.2f)",
        _composite_id(best_c),
        best[0],
        best[1],
        best[2],
    )
    return best_c
