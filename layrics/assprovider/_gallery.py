from __future__ import annotations

import inspect
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from layrics.LDDC.common.models import LyricsType

from ._base import DefaultProvider
from ._protocol import Lyrics

logger = logging.getLogger("layrics.assprovider")


class GradientOutlineProvider(DefaultProvider):
    """Apply a timed Hook wipe to the base ASS style."""

    PROVIDER = "gradient-outline"
    priority = 110

    def generate_overlay(self, lyrics: Lyrics, duration_ms: int | None) -> bytes | str:
        kind = lyrics.types.get(lyrics.primary_track)
        if kind != LyricsType.VERBATIM or not self.karaoke:
            return self.generate(lyrics, duration_ms)
        timed = lyrics.get_fslyrics(duration_ms)
        source_ass = self._generate_timed(lyrics, timed)
        try:
            from kara_templater import SceneCompileError

            from layrics.karaoke.gradient_outline import build_scene
        except ImportError:
            logger.warning("Gallery Hook support unavailable, using static ASS")
            return source_ass
        try:
            scene = build_scene(source_ass, timed[lyrics.primary_track])
            if scene.objects:
                with TemporaryDirectory() as tmp:
                    path = Path(tmp) / "lyrics.hook"
                    if "overlay" in inspect.signature(scene.export).parameters:
                        scene.export(path, overlay=True)
                    else:
                        scene.export(path)
                    return path.read_bytes()
        except (TypeError, ValueError, SceneCompileError) as exc:
            logger.warning("Could not compile gallery Hook, using static ASS: %s", exc)
        return source_ass
