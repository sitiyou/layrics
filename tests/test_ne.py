import asyncio
from unittest.mock import AsyncMock

import pytest

from layrics.LDDC.common.exceptions import LyricsNotFoundError
from layrics.LDDC.common.models import LyricsType, SongInfo, Source
from layrics.LDDC.core.api.lyrics.ne import NEAPI


def get_lyrics(payload):
    api = NEAPI()
    api.request = AsyncMock(return_value=payload)
    return asyncio.run(api.get_lyrics(SongInfo(source=Source.NE, id=1)))


@pytest.mark.parametrize("yrc", [None, {}, {"lyric": None}, {"lyric": ""}])
def test_empty_yrc_uses_line_timed_original(yrc):
    lyrics = get_lyrics(
        {
            "yrc": yrc,
            "lrc": {"lyric": "[00:01.00]hello"},
            "tlyric": {"lyric": "[00:01.00]你好"},
            "romalrc": None,
        }
    )
    assert lyrics.types["orig"] == LyricsType.LINEBYLINE
    assert lyrics["orig"][0].words[0].text == "hello"
    assert lyrics["ts"][0].words[0].text == "你好"
    assert "roma" not in lyrics


def test_word_timed_original_preferred():
    lyrics = get_lyrics(
        {
            "yrc": {"lyric": "[1000,1000](1000,500,0)你(1500,500,0)好"},
            "lrc": {"lyric": "[00:01.00]你好"},
        }
    )
    assert lyrics.types["orig"] == LyricsType.VERBATIM
    assert lyrics.types["orig_lrc"] == LyricsType.LINEBYLINE


def test_empty_tracks_raise_no_lyrics():
    with pytest.raises(LyricsNotFoundError):
        get_lyrics({"yrc": {"lyric": None}, "lrc": None})
