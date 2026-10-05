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
    assert len(effects) == 4 * word_count * 4
    assert {line.layer for line in effects} == {0, 1, 2, 3}
    for layer in range(4):
        assert len([line for line in effects if line.layer == layer]) == 4 * word_count
    assert all("\\pos(" in line.text for line in effects)
    assert all("\\shad0" in line.text for line in effects)
    assert all("\\t(0,500,0.5,\\fscx110\\fscy110)" in line.text for line in effects[:4])
    assert all("\\t(500,750,2,\\fscx100\\fscy100)" in line.text for line in effects[:4])
    assert all(line.style in result.styles for line in effects)
    assert {line.style for line in effects} == (
        {"K1", "K2"} if line_mode == "double" else {"K1"}
    )
    assert len([line for line in result.lines if line.effect == "karaoke"]) == 4
    assert result.styles["K1"].fontname == lyrics.primary_style.font_name
    assert all(
        result.styles[name].spacing == 5 for name in {line.style for line in effects}
    )
    assert (
        result.styles["K1"].fields["PrimaryColour"]
        == lyrics.primary_style.secondary_colour
    )
    base_glow = next(line for line in effects if line.layer == 0)
    assert "\\blur3" in base_glow.text
    assert "\\bord8" in base_glow.text
    assert "\\3c&H6A719E&" in base_glow.text
    assert "\\alpha&H33&" in base_glow.text
    overlay_glow = next(line for line in effects if line.layer == 1)
    assert "\\1c&HFCDD1C&\\3c&HFFEC77&" in overlay_glow.text
    assert "\\alpha&HCC&\\t(0,500,\\alpha&H33&)" in overlay_glow.text
    base_edge = next(line for line in effects if line.layer == 2)
    assert "\\3c&H222222&" in base_edge.text
    overlay_edge = next(line for line in effects if line.layer == 3)
    assert overlay_edge.start_time == 1000
    assert "\\1c&HFCDD1C&\\3c&HEFEFEF&" in overlay_edge.text
    assert "\\t(-24,0,\\clip(" in overlay_edge.text
    assert "\\t(0,88.2355,0.5,\\clip(" in overlay_edge.text
    assert "\\t(88.2355,500,\\clip(" in overlay_edge.text
    assert "\\t(500,524,\\clip(" in overlay_edge.text


@pytest.mark.parametrize("line_mode", ["single", "double"])
@pytest.mark.parametrize("spacing", [0, 2.5])
def test_template_spacing(line_mode, spacing):
    lyrics = Lyrics(make_lyrics(line_count=4), primary_override={"spacing": 1})
    provider = KaraTemplaterProvider(
        {"line_mode": line_mode, "template": {"spacing": spacing}}
    )
    result = Document.parse(provider.generate(lyrics))
    primary_styles = {"K1", "K2"} if line_mode == "double" else {"K1"}
    assert all(result.styles[name].spacing == spacing for name in primary_styles)
    assert lyrics.primary_style.spacing == 1


def test_template_timing_at_zero():
    lyrics = make_lyrics(word_count=1)
    lyrics["orig"] = [LyricsLine(0, 500, [LyricsWord(0, 500, "word")])]
    result = Document.parse(KaraTemplaterProvider().generate(lyrics))
    overlays = [line for line in result.lines if not line.comment and line.layer == 3]
    assert len(overlays) == 1
    assert overlays[0].start_time == 0
    assert "\\t(0,88.2355,0.5,\\clip(" in overlays[0].text


def test_template_preserves_translation_and_parameters():
    lyrics = make_lyrics(translation=True)
    provider = KaraTemplaterProvider(
        {
            "double": {"advance_ms": 0},
            "template": {"fade_in_ms": 123, "bord": 7, "blur_scale": 2, "spacing": 2.5},
        }
    )
    result = Document.parse(provider.generate(lyrics))
    translations = [
        line for line in result.lines if not line.comment and line.style == "Secondary"
    ]
    assert len(translations) == 2
    assert all(line.text.endswith("translation") for line in translations)
    assert all(line.effect == "fx" for line in translations)
    assert result.styles["Secondary"].spacing == pytest.approx(2.5 * 32 / 48)
    assert (
        result.styles["Secondary"].fields["PrimaryColour"]
        == lyrics.secondary_style.primary_colour
    )
    assert (
        result.styles["Secondary"].fields["OutlineColour"]
        == lyrics.secondary_style.outline_colour
    )
    effects = [
        line
        for line in result.lines
        if line.effect == "fx" and line.style != "Secondary"
    ]
    assert len(effects) == 8
    assert all("\\fad(123,200)" in line.text for line in effects)
    assert any("\\bord7" in line.text for line in effects)
    assert any("\\bord14" in line.text for line in effects)


@pytest.mark.parametrize("text", ["translation", "译文\n第二行", "a | b"])
@pytest.mark.parametrize(
    ("primary_size", "secondary_size", "blur", "border", "glow_border", "spacing"),
    [
        (48, 32, "2.66667", "2.33333", "4.66667", 5 / 3),
        (56, 28, "2", "1.75", "3.5", 1.25),
        (40, 40, "4", "3.5", "7", 2.5),
    ],
)
def test_template_translation_static_style(
    text, primary_size, secondary_size, blur, border, glow_border, spacing
):
    lyrics = Lyrics(
        make_lyrics(translation=True),
        primary_override={"font_size": primary_size},
        secondary_override={
            "font_size": secondary_size,
            "spacing": 1,
            "margin_v": 19,
            "primary_colour": "&H00445566",
            "secondary_colour": "&H00665544",
            "outline_colour": "&H00778899",
            "back_colour": "&H11223344",
        },
    )
    lyrics["ts"] = [LyricsLine(1000, 2000, [LyricsWord(1000, 2000, text)])]
    options = {
        "line_mode": "single",
        "double": {"advance_ms": 0},
        "template": {
            "spacing": 2.5,
            "bord": 7,
            "blur": 8,
            "blur_scale": 2,
            "overlay_color": "A1B2C3",
            "overlay_blur_color": "112233",
            "overlay_outline_color": "332211",
            "base_blur_color": "123456",
            "base_outline_color": "654321",
        },
    }
    original = Document.parse(DefaultProvider(options).generate(lyrics))
    original_line = next(line for line in original.lines if line.style == "Secondary")
    original_style = original.styles["Secondary"]
    result = Document.parse(KaraTemplaterProvider(options).generate(lyrics))
    translations = [
        line for line in result.lines if not line.comment and line.style == "Secondary"
    ]
    assert len(translations) == 2
    assert {line.layer for line in translations} == {0, 2}
    for line in translations:
        assert line.effect == "fx"
        assert line.text.endswith(original_line.text)
        assert (line.start_time, line.end_time) == (
            original_line.start_time,
            original_line.end_time,
        )
        assert "\\shad0" in line.text
        assert all(
            tag not in line.text
            for tag in (
                "\\t(",
                "\\fad(",
                "\\clip(",
                "\\fsc",
                "\\k",
                "\\1c",
                "\\2c",
                "\\3c",
                "\\4c",
            )
        )
    glow = next(line for line in translations if line.layer == 0)
    assert f"\\blur{blur}\\bord{glow_border}\\alpha&H33&" in glow.text
    edge = next(line for line in translations if line.layer == 2)
    assert f"\\blur{blur}\\bord{border}" in edge.text
    style = result.styles["Secondary"]
    assert result.styles["K1"].spacing == 2.5
    assert style.spacing == pytest.approx(spacing)
    assert style.fontname == original_style.fontname
    assert style.fontsize == original_style.fontsize == secondary_size
    for field in ("PrimaryColour", "SecondaryColour", "OutlineColour", "BackColour"):
        assert style.fields[field] == original_style.fields[field]
    assert style.fields["PrimaryColour"] == "&H00445566"
    assert style.fields["OutlineColour"] == "&H00778899"
    assert (style.align, style.margin_l, style.margin_r, style.margin_v) == (
        original_style.align,
        original_style.margin_l,
        original_style.margin_r,
        original_style.margin_v,
    )
    assert lyrics.secondary_style.spacing == 1


def test_template_translation_disabled():
    result = Document.parse(
        KaraTemplaterProvider({"secondary": False}).generate(
            make_lyrics(translation=True)
        )
    )
    assert "Secondary" not in result.styles
    assert not any(
        not line.comment and line.style == "Secondary" for line in result.lines
    )


def test_template_furigana_layers():
    lyrics = make_lyrics(word_count=1)
    lyrics["orig"] = [LyricsLine(1000, 1500, [LyricsWord(1000, 1500, "word|ruby")])]
    provider = KaraTemplaterProvider({"double": {"advance_ms": 0}})
    result = Document.parse(provider.generate(lyrics))
    effects = [line for line in result.lines if line.effect == "fx"]
    furigana = [line for line in effects if line.style == "K1-furigana"]
    assert len(effects) == 8
    assert len(furigana) == 4
    assert result.styles["K1-furigana"].spacing == 5
    assert {line.layer for line in furigana} == {0, 1, 2, 3}
    assert all(line.text.endswith("ruby") for line in furigana)
    assert all("\\bord4" in line.text for line in furigana if line.layer in (0, 1))
    assert all("\\bord3" in line.text for line in furigana if line.layer in (2, 3))


def test_template_colours_follow_primary_style():
    lyrics = Lyrics(make_lyrics(), primary_override={"primary_colour": "&H000000FF"})
    result = Document.parse(KaraTemplaterProvider().generate(lyrics))
    effects = [line for line in result.lines if line.effect == "fx"]
    overlay_glow = next(line for line in effects if line.layer == 1)
    assert "\\1c&H0000FF&\\3c&H6666FF&" in overlay_glow.text
    base_glow = next(line for line in effects if line.layer == 0)
    assert "\\3c&H9E9E63&" in base_glow.text


def test_template_glow_overrides():
    provider = KaraTemplaterProvider(
        {
            "template": {
                "blur": 8,
                "blur_scale": 1.5,
                "clip_size": 12,
                "overlay_color": "0000FF",
                "overlay_blur_color": "123456",
                "base_blur_color": "654321",
                "base_outline_color": "112233",
                "overlay_outline_color": "332211",
            }
        }
    )
    result = Document.parse(provider.generate(make_lyrics()))
    effects = [line for line in result.lines if line.effect == "fx"]
    base_glow = next(line for line in effects if line.layer == 0)
    assert "\\blur8" in base_glow.text
    assert "\\bord8" in base_glow.text
    assert "\\3c&H654321&" in base_glow.text
    overlay_glow = next(line for line in effects if line.layer == 1)
    assert "\\1c&H0000FF&\\3c&H123456&" in overlay_glow.text
    base_edge = next(line for line in effects if line.layer == 2)
    assert "\\3c&H112233&" in base_edge.text
    overlay_edge = next(line for line in effects if line.layer == 3)
    assert "\\1c&H0000FF&\\3c&H332211&" in overlay_edge.text
    assert "\\t(-12,0,\\clip(" in overlay_edge.text


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
    lyrics = make_lyrics(translation=True)
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
