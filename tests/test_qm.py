import asyncio
from base64 import b64decode
from dataclasses import replace
from unittest.mock import AsyncMock, Mock, call

import pytest

from layrics import config as config_module
from layrics import lyricsource, main
from layrics.assprovider import DefaultProvider
from layrics.LDDC.common.exceptions import APIParamsError, APIRequestError
from layrics.LDDC.common.models import SongInfo, Source
from layrics.LDDC.core.api.lyrics import qm


@pytest.fixture
def song():
    return {
        "id": 248672467,
        "mid": "000iAGZa3Fz4sB",
        "title": "風になる (幻化成风)",
        "subtitle": "《猫的报恩》电影主题曲",
        "singer": [{"name": "辻亚弥乃"}],
        "album": {"name": "風になる"},
        "interval": 276,
        "language": 3,
    }


@pytest.fixture
def api(monkeypatch, song):
    api = object.__new__(qm.QMAPI)
    api.request = AsyncMock(
        return_value={
            "lyric": "encrypted lyrics",
            "trans": "",
            "roma": "",
            "qrc_t": 1,
            "lrc_t": 0,
            "trans_t": 0,
            "roma_t": 0,
        }
    )
    api.request.side_effect = [{"track_info": song}, api.request.return_value]
    monkeypatch.setattr(qm, "qrc_decrypt", lambda _: "[00:01.00]歌詞\n")
    return api


@pytest.mark.parametrize(
    "missing",
    [("title", "album", "duration", "artist"), ("title",), ("album",), ("duration",)],
)
def test_get_lyrics_resolves_missing_metadata(api, song, missing):
    complete = api.format_songinfos([song])[0]
    info = replace(complete, **dict.fromkeys(missing))

    lyrics = asyncio.run(api.get_lyrics(info))

    assert lyrics.info.songinfo == complete
    assert lyrics["orig"][0].words[0].text == "歌詞"
    assert api.request.await_args_list[0] == call(
        "get_song_detail_yqq", "music.pf_song_detail_svr", {"song_id": 248672467}
    )
    lyric_request = api.request.await_args_list[1]
    assert lyric_request.args[:2] == (
        "GetPlayLyricInfo",
        "music.musichallSong.PlayLyricInfo",
    )
    params = lyric_request.args[2]
    assert params["songID"] == song["id"]
    assert params["interval"] == song["interval"]
    assert b64decode(params["songName"]).decode() == song["title"]
    assert b64decode(params["albumName"]).decode() == song["album"]["name"]
    assert b64decode(params["singerName"]).decode() == song["singer"][0]["name"]


def test_get_lyrics_skips_detail_for_complete_metadata(api, song):
    api.request.side_effect = None
    info = api.format_songinfos([song])[0]

    lyrics = asyncio.run(api.get_lyrics(info))

    assert lyrics.info.songinfo == info
    api.request.assert_awaited_once()
    assert api.request.await_args.args[0] == "GetPlayLyricInfo"


def test_get_lyrics_requires_id(api):
    with pytest.raises(APIParamsError, match="missing required parameters"):
        asyncio.run(api.get_lyrics(SongInfo(source=Source.QM)))
    api.request.assert_not_awaited()


@pytest.mark.parametrize("track", [None, {}, {"id": 0}, {"id": 123}])
def test_get_lyrics_rejects_unresolved_id(api, track):
    api.request.side_effect = [{"track_info": track}]
    with pytest.raises(APIRequestError, match="qm song not found: 248672467"):
        asyncio.run(api.get_lyrics(SongInfo(source=Source.QM, id="248672467")))
    api.request.assert_awaited_once()


def test_get_lyrics_propagates_detail_failure(api):
    api.request.side_effect = APIRequestError("detail request failed")
    with pytest.raises(APIRequestError, match="detail request failed"):
        asyncio.run(api.get_lyrics(SongInfo(source=Source.QM, id="248672467")))
    api.request.assert_awaited_once()


def test_ipc_fetch_by_id_uses_resolved_duration(api, tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", str(tmp_path / "missing.toml"))
    cfg = config_module.Config()
    cfg.ass_provider = "default"
    monkeypatch.setattr(lyricsource, "get_config", lambda: cfg)
    monkeypatch.setattr(lyricsource, "_lddc_get_lyrics", api.get_lyrics)
    monkeypatch.setattr(main, "_fetch_lyrics", lyricsource.fetch_lyrics)
    generate = Mock(return_value="generated ASS")
    monkeypatch.setattr(DefaultProvider, "generate", generate)
    app = object.__new__(main.LayricsApp)

    response = asyncio.run(
        app._execute(
            {"id": 1, "method": "fetch_lyrics", "params": {"song_id": "QM248672467"}}
        )
    )

    assert response == {"id": 1, "type": "result", "data": {"ass": "generated ASS"}}
    assert generate.call_args.args[1] == 276000
    assert generate.call_args.args[0].info.songinfo.title == "風になる (幻化成风)"
