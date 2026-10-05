from __future__ import annotations

from typing import Any

from layrics.karaoke.header import render_karaoke_header
from layrics.LDDC.common.models import LyricsType

from ._base import DefaultProvider
from ._protocol import AssTrigger, Lyrics


class KaraTemplaterProvider(DefaultProvider):
    PROVIDER = "kara-templater"
    priority = 50
    trigger = AssTrigger(lyrics_types={LyricsType.VERBATIM})

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.template_config = (config or {}).get("template", {})

    def generate(self, lyrics: Lyrics, duration_ms: int | None = None) -> str:
        ass = super().generate(lyrics, duration_ms)
        if (
            not self.karaoke
            or lyrics.types.get(lyrics.primary_track) != LyricsType.VERBATIM
        ):
            return ass

        from kara_templater import Document, Line, Style, apply_templates

        primary = lyrics.primary_style
        overrides = {
            "OVERLAY_COLOR": primary.primary_colour.removeprefix("&H")[-6:],
            **{key.upper(): value for key, value in self.template_config.items()},
        }
        templates = Document.parse(render_karaoke_header(**overrides))
        document = Document.parse(ass)
        style_names = {"Primary": "K1", "PrimaryLeft": "K1", "PrimaryRight": "K2"}
        for record in document.records:
            if isinstance(record, Style) and record.name in style_names:
                record.name = style_names[record.name]
                record.fields["PrimaryColour"] = record.fields["SecondaryColour"]
            elif isinstance(record, Line):
                record.style = style_names.get(record.style, record.style)
        document.records.extend(templates.lines)
        return apply_templates(document).dumps()
