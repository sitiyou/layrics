from __future__ import annotations

from dataclasses import replace
from typing import Any

from LDDC.common.models import (
    FSLyrics,
    FSLyricsLine,
    LyricsType,
)

from ._ass import (
    AssHeader,
    AssStyle,
    AssDialogueLine,
    build_ass,
    DEFAULT_PRIMARY,
    DEFAULT_SECONDARY,
)
from ._protocol import AssProvider, AssTrigger, Lyrics
from ._util import ass_escape


class DefaultProvider(AssProvider):
    PROVIDER = "default"
    priority = 100
    trigger = AssTrigger()

    def __init__(
        self,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config or {}
        self.primary_position = str(cfg.get("primary_position", "top"))
        self.margin_v_spacing = int(cfg.get("margin_v_spacing", 2))
        self.karaoke = bool(cfg.get("karaoke", True))
        self.line_mode = str(cfg.get("line_mode", "single"))
        self.secondary_enabled = bool(cfg.get("secondary", True))
        self.advance_ms = int(cfg.get("advance_ms", 0))
        self.double_margin_v_right = cfg.get("double_margin_v_right", None)
        self.double_margin_v_spacing = cfg.get("double_margin_v_spacing", None)
        self.double_margin_l = cfg.get("double_margin_l", None)
        self.double_margin_r = cfg.get("double_margin_r", None)
        self.double_margin_max_length = cfg.get("double_margin_max_length", None)

    def generate(
        self, lyrics: Lyrics, duration_ms: int | None = None
    ) -> str:
        orig_type = lyrics.types.get(lyrics.primary_track)

        if orig_type == LyricsType.PlainText:
            return self._generate_plaintext(lyrics, duration_ms)

        fslyrics = lyrics.get_fslyrics(duration_ms)
        use_karaoke = orig_type == LyricsType.VERBATIM and self.karaoke

        orig_data = fslyrics[lyrics.primary_track]
        header = AssHeader(title=lyrics.title or "lyrics")

        # Step 1: advance start by up to advance_ms into the gap of the same-side line
        is_double = self.line_mode == "double" and len(orig_data) > 3
        pairs = [(line.start, line.end) for line in orig_data]
        advanced = []
        for i, (start, end) in enumerate(pairs):
            if is_double:
                prev_end = pairs[i - 2][1] if i >= 2 else 0
            else:
                prev_end = pairs[i - 1][1] if i > 0 else 0
            gap = start - prev_end
            shift = max(0, min(self.advance_ms, gap))
            new_start = start - shift
            advanced.append((new_start, end, shift))

        if is_double:
            return self._generate_double(
                header, orig_data, use_karaoke, advanced, lyrics,
            )

        primary = self._adjust(lyrics.primary_style, is_primary=True, secondary_style=lyrics.secondary_style)
        styles = [primary]
        events: list[AssDialogueLine] = []
        secondary: AssStyle | None = None

        for i, (oline, aligned) in enumerate(
            lyrics.iter_aligned(fslyrics, secondary_enabled=self.secondary_enabled)
        ):
            start, end, shift = advanced[i]
            text = self._karaoke_text(oline) if use_karaoke else self._plain_text(oline)
            if shift > 0 and use_karaoke:
                text = f"{{\\k{shift // 10}}}{text}"
            events.append(AssDialogueLine(
                start_ms=start, end_ms=end,
                style=primary.name, text=text,
            ))

            for lang, lline in aligned.items():
                stext = self._plain_text(lline)
                if stext == text:
                    continue
                if secondary is None:
                    secondary = self._adjust(lyrics.secondary_style, is_primary=False, secondary_style=lyrics.secondary_style)
                    styles.append(secondary)
                events.append(AssDialogueLine(
                    start_ms=start, end_ms=end,
                    style=secondary.name, text=stext,
                ))

        return build_ass(header, styles, events)

    def _generate_double(
        self,
        header: AssHeader,
        orig_data: list[FSLyricsLine],
        use_karaoke: bool,
        advanced: list[tuple[int, int, int]],
        lyrics: Lyrics,
    ) -> str:
        left_style, right_style = self._build_double_styles(
            self._adjust(lyrics.primary_style, is_primary=True, secondary_style=lyrics.secondary_style),
            header,
        )
        if not use_karaoke:
            dim_colour = lyrics.primary_style.secondary_colour
            left_dim = replace(left_style, name=left_style.name + "Dim", primary_colour=dim_colour)
            right_dim = replace(right_style, name=right_style.name + "Dim", primary_colour=dim_colour)
            styles = [left_style, left_dim, right_style, right_dim]
        else:
            styles = [left_style, right_style]
        events: list[AssDialogueLine] = []

        for i, oline in enumerate(orig_data):
            start, end, shift = advanced[i]
            text = self._karaoke_text(oline) if use_karaoke else self._plain_text(oline)
            if shift > 0 and use_karaoke:
                text = f"{{\\k{shift // 10}}}{text}"
            if shift > 0 and not use_karaoke:
                original_start = orig_data[i].start
                dim_style = left_dim if i % 2 == 0 else right_dim
                bright_style = left_style if i % 2 == 0 else right_style
                events.append(AssDialogueLine(
                    start_ms=start, end_ms=original_start,
                    style=dim_style.name, text=text,
                ))
                events.append(AssDialogueLine(
                    start_ms=original_start, end_ms=end,
                    style=bright_style.name, text=text,
                ))
            else:
                style = left_style if i % 2 == 0 else right_style
                events.append(AssDialogueLine(
                    start_ms=start, end_ms=end,
                    style=style.name, text=text,
                ))

        return build_ass(header, styles, events)

    def _build_double_styles(self, base: AssStyle, header: AssHeader) -> tuple[AssStyle, AssStyle]:
        right_mv = (
            int(self.double_margin_v_right)
            if self.double_margin_v_right is not None
            else int(base.margin_v)
        )
        spacing = (
            int(self.double_margin_v_spacing)
            if self.double_margin_v_spacing is not None
            else int(base.font_size) + self.margin_v_spacing * 2
        )
        max_len = (
            int(self.double_margin_max_length)
            if self.double_margin_max_length is not None
            else header.play_res_x // 2
        )
        left_ml = int(self.double_margin_l) if self.double_margin_l is not None else 20
        left_mr = header.play_res_x - left_ml - max_len
        right_mr = int(self.double_margin_r) if self.double_margin_r is not None else 20
        right_ml = header.play_res_x - right_mr - max_len
        left = replace(base,
            name=base.name + "Left",
            alignment=1,
            margin_l=left_ml,
            margin_r=left_mr,
            margin_v=right_mv + spacing,
        )
        right = replace(base,
            name=base.name + "Right",
            alignment=3,
            margin_l=right_ml,
            margin_r=right_mr,
            margin_v=right_mv,
        )
        return left, right

    def _generate_plaintext(self, lyrics: Lyrics, duration_ms: int | None = None) -> str:
        orig = lyrics.get(lyrics.primary_track)
        if not orig:
            return ""
        ptext = ass_escape("".join(w.text for line in orig for w in line.words).strip())
        end_ms = duration_ms or 5000

        primary = self._adjust(lyrics.primary_style, is_primary=True, secondary_style=lyrics.secondary_style)
        styles = [primary]
        events = [AssDialogueLine(
            start_ms=0, end_ms=end_ms,
            style=primary.name, text=ptext,
        )]

        if self.secondary_enabled:
            sec = lyrics.secondary_track
            if sec:
                sdata = lyrics.get(sec)
                if sdata:
                    stext = ass_escape("".join(w.text for line in sdata for w in line.words).strip())
                    if stext and stext != ptext:
                        secondary = self._adjust(lyrics.secondary_style, is_primary=False, secondary_style=lyrics.secondary_style)
                        styles.append(secondary)
                        events.append(AssDialogueLine(
                            start_ms=0, end_ms=end_ms,
                            style=secondary.name, text=stext,
                        ))

        header = AssHeader(title=lyrics.title or "lyrics")
        return build_ass(header, styles, events)

    def _adjust(self, style: AssStyle | None, is_primary: bool, secondary_style: AssStyle | None) -> AssStyle:
        if style is None:
            style = DEFAULT_PRIMARY if is_primary else DEFAULT_SECONDARY
        if secondary_style is None:
            secondary_style = DEFAULT_SECONDARY
        spacing = int(secondary_style.font_size) + self.margin_v_spacing
        if self.primary_position == "bottom":
            mv = style.margin_v if is_primary else style.margin_v + spacing
        else:
            mv = style.margin_v + spacing if is_primary else style.margin_v
        if mv == style.margin_v:
            return style
        return replace(style, margin_v=mv)

    def _karaoke_text(self, line: FSLyricsLine) -> str:
        if len(line.words) <= 1:
            return self._plain_text(line)
        parts: list[str] = []
        for word in line.words:
            k = max((word.end - word.start) // 10, 1)
            parts.append(f"{{\\kf{k}}}{ass_escape(word.text)}")
        return "".join(parts)

    @staticmethod
    def _plain_text(line: FSLyricsLine) -> str:
        return ass_escape("".join(w.text for w in line.words))
