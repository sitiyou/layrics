import asyncio
import threading

import pytest
from kara_templater import Document

from layrics import config as config_module
from layrics import lyricsource
from layrics.assprovider import (
    AssTrigger,
    DefaultProvider,
    KaraTemplaterProvider,
    Lyrics,
    _protocol,
    match_provider,
    register_ass_provider,
)
from layrics.LDDC.common.models import (
    FSLyricsLine,
    FSLyricsWord,
    LyricsLine,
    LyricsType,
    LyricsWord,
    SongInfo,
    Source,
)
from layrics.LDDC.common.models import (
    Lyrics as LDDCLyrics,
)


def make_lyrics(line_count=1, word_count=2, translation=False):
    raw = LDDCLyrics(SongInfo(source=Source.QM, title="Test", duration=30000))
    raw["orig"] = [
        LyricsLine(
            start := 1000 + i * 3000,
            start + word_count * 500,
            [
                LyricsWord(start + j * 500, start + (j + 1) * 500, f"word{j}")
                for j in range(word_count)
            ],
        )
        for i in range(line_count)
    ]
    raw.types["orig"] = LyricsType.VERBATIM
    if translation:
        raw["ts"] = [
            LyricsLine(
                line.start, line.end, [LyricsWord(line.start, line.end, "translation")]
            )
            for line in raw["orig"]
        ]
        raw.types["ts"] = LyricsType.LINEBYLINE
    return Lyrics(raw)


def test_builtin_selection():
    lyrics = make_lyrics()
    assert match_provider("mpd", lyrics) is KaraTemplaterProvider
    assert match_provider("mpd", lyrics, name="default") is DefaultProvider
    assert match_provider("mpd", lyrics, name="kara-templater") is KaraTemplaterProvider
    lyrics.types["orig"] = LyricsType.LINEBYLINE
    assert match_provider("mpd", lyrics) is DefaultProvider
    with pytest.raises(ValueError, match="unknown ASS provider"):
        match_provider("mpd", lyrics, name="unknown")


def test_registration(monkeypatch):
    monkeypatch.setattr(_protocol, "_ass_providers", list(_protocol._ass_providers))

    class PlayerProvider(DefaultProvider):
        PROVIDER = "player-test"
        priority = 10
        trigger = AssTrigger(player_regex="^mpd$", source=Source.QM)

    register_ass_provider(PlayerProvider)
    assert match_provider("mpd", make_lyrics()) is PlayerProvider
    assert match_provider("spotify", make_lyrics()) is KaraTemplaterProvider
    with pytest.raises(ValueError, match="already registered"):
        register_ass_provider(PlayerProvider)


def test_trigger_uses_selected_track_and_source():
    lyrics = make_lyrics(translation=True)
    lyrics = Lyrics(lyrics, primary_track="ts")
    assert not KaraTemplaterProvider.trigger.matches("mpd", lyrics)
    assert AssTrigger(source=Source.QM).matches("mpd", lyrics)
    assert AssTrigger(source=[Source.QM, Source.NE]).matches("mpd", lyrics)
    assert not AssTrigger(source=Source.NE).matches("mpd", lyrics)


@pytest.mark.parametrize("line_mode", ["single", "double"])
@pytest.mark.parametrize("word_count", [1, 2])
def test_template_output(line_mode, word_count):
    lyrics = make_lyrics(line_count=4, word_count=word_count)
    provider = KaraTemplaterProvider(
        {"line_mode": line_mode, "double": {"advance_ms": 0}}
    )
    result = Document.parse(provider.generate(lyrics))
    effects = [
        line for line in result.lines if not line.comment and line.effect == "fx"
    ]
    assert len(effects) == 4 * word_count * 2
    assert all("\\pos(" in line.text for line in effects)
    assert all(line.style in result.styles for line in effects)
    assert {line.style for line in effects} == (
        {"K1", "K2"} if line_mode == "double" else {"K1"}
    )
    assert len([line for line in result.lines if line.effect == "karaoke"]) == 4
    assert result.styles["K1"].fontname == lyrics.primary_style.font_name
    assert (
        result.styles["K1"].fields["PrimaryColour"]
        == lyrics.primary_style.secondary_colour
    )
    overlays = [line for line in effects if line.layer == 1]
    assert "\\t(100,600," in overlays[0].text


def test_template_timing_at_zero():
    lyrics = make_lyrics(word_count=1)
    lyrics["orig"] = [LyricsLine(0, 500, [LyricsWord(0, 500, "word")])]
    result = Document.parse(KaraTemplaterProvider().generate(lyrics))
    overlays = [line for line in result.lines if not line.comment and line.layer == 1]
    assert len(overlays) == 1
    assert overlays[0].start_time == 0
    assert "\\t(0,500," in overlays[0].text


def test_template_preserves_translation_and_parameters():
    lyrics = make_lyrics(translation=True)
    provider = KaraTemplaterProvider(
        {"double": {"advance_ms": 0}, "template": {"fade_in_ms": 123, "bord": 7}}
    )
    result = Document.parse(provider.generate(lyrics))
    translations = [
        line for line in result.lines if not line.comment and line.style == "Secondary"
    ]
    assert len(translations) == 1
    assert translations[0].text == "translation"
    assert translations[0].effect == ""
    effects = [line for line in result.lines if line.effect == "fx"]
    assert all("\\fad(123,200)" in line.text for line in effects)
    assert any("\\bord7" in line.text for line in effects)


@pytest.mark.parametrize(
    ("lyrics_type", "karaoke"),
    [
        (kind, enabled)
        for kind in LyricsType
        for enabled in (True, False)
        if kind != LyricsType.VERBATIM or not enabled
    ],
)
def test_template_fallback(lyrics_type, karaoke):
    lyrics = make_lyrics()
    lyrics.types["orig"] = lyrics_type
    options = {"karaoke": karaoke}
    assert KaraTemplaterProvider(options).generate(lyrics) == DefaultProvider(
        options
    ).generate(lyrics)


def test_karaoke_timing():
    line = FSLyricsLine(
        1000,
        2500,
        [FSLyricsWord(1200, 1500, "a"), FSLyricsWord(2000, 2500, "b")],
    )
    assert DefaultProvider()._karaoke_text(line) == r"{\k20}{\kf30}a{\k50}{\kf50}b"


def test_provider_config(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(
        '[assprovider]\nprovider = "kara-templater"\n'
        "[assprovider.default]\nsecondary = false\n"
        "[assprovider.default.double]\nmargin_l = 123\n"
        '[assprovider.kara-templater]\nline_mode = "double"\n'
        "[assprovider.kara-templater.double]\nadvance_ms = 0\n"
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", str(path))
    cfg = config_module.Config()
    assert cfg.ass_provider == "kara-templater"
    assert cfg.get_provider_config()["karaoke"] is True
    assert cfg.get_provider_config()["secondary"] is False
    assert cfg.get_provider_config()["line_mode"] == "double"
    assert cfg.get_provider_config()["double"] == {"margin_l": 123, "advance_ms": 0}
    cfg.set_provider_option("karaoke", False)
    assert cfg.get_provider_config()["karaoke"] is False
    assert cfg.get_provider_config("default")["karaoke"] is True


def test_fetch_dispatches_provider_off_event_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", str(tmp_path / "missing.toml"))
    cfg = config_module.Config()
    cfg.ass_provider = "kara-templater"
    lyrics = make_lyrics()
    event_thread = threading.get_ident()

    async def get_lyrics(song_info):
        return lyrics

    def generate(self, lyrics, duration_ms=None):
        assert threading.get_ident() != event_thread
        assert duration_ms == 30000
        assert self.karaoke is True
        return "generated ASS"

    monkeypatch.setattr(lyricsource, "_lddc_get_lyrics", get_lyrics)
    monkeypatch.setattr(lyricsource, "get_config", lambda: cfg)
    monkeypatch.setattr(KaraTemplaterProvider, "generate", generate)
    assert (
        asyncio.run(lyricsource.fetch_lyrics(lyrics.info.songinfo)) == "generated ASS"
    )
