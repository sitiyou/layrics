from __future__ import annotations

from typing import Any

from layrics.LDDC.common.models import FSLyrics, LyricsType

from ._base import DefaultProvider
from ._protocol import AssTrigger, Lyrics


class KaraTemplaterProvider(DefaultProvider):
    PROVIDER = "kara-templater"
    priority = 50
    trigger = AssTrigger(lyrics_types={LyricsType.VERBATIM})

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.template_config = (config or {}).get("template", {})

    def _generate_timed(self, lyrics: Lyrics, fslyrics: FSLyrics) -> str:
        ass = super()._generate_timed(lyrics, fslyrics)
        if (
            not self.karaoke
            or lyrics.types.get(lyrics.primary_track) != LyricsType.VERBATIM
        ):
            return ass

        from kara_templater import Document

        from layrics.karaoke.effect import render

        rows = fslyrics[lyrics.primary_track]
        return render(
            Document.parse(ass), lyrics.primary_style, rows, self.template_config
        )
