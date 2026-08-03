# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only

import json
import random
import time
from base64 import b64encode
from threading import Lock

import httpx

from layrics.LDDC.common.exceptions import (
    APIParamsError,
    APIRequestError,
    LyricsNotFoundError,
)
from layrics.LDDC.common.models import (
    APIResultList,
    Artist,
    Language,
    Lyrics,
    SearchInfo,
    SearchType,
    SongInfo,
    Source,
)
from layrics.LDDC.core.decryptor import qrc_decrypt
from layrics.LDDC.core.parser.qrc import qrc_str_parse
from layrics.LDDC.core.parser.utils import judge_lyrics_type

from .models import CloudAPI

SEARCH_TYPE_MAPPING = {
    SearchType.SONG: 0,
}

LANGUAGE_MAPPING = {
    9: Language.INSTRUMENTAL,
    5: Language.ENGLISH,
    4: Language.KOREAN,
    3: Language.JAPANESE,
    1: Language.CHINESE,  # Cantonese
    0: Language.CHINESE,  # Mandarin
}


class QMAPI(CloudAPI):
    source = Source.QM
    supported_search_types = (SearchType.SONG,)

    def __init__(self) -> None:
        self.client = httpx.Client(
            headers={
                "cookie": "tmeLoginType=-1;",
                "content-type": "application/json",
                "accept-encoding": "gzip",
                "user-agent": "okhttp/3.14.9",
            },
            http2=True,
        )
        self.comm = {
            "ct": 11,
            "cv": "1003006",
            "v": "1003006",
            "os_ver": "15",
            "phonetype": "24122RKC7C",  # REDMI K80 Pro https://mifirm.net/model/miro.ttt
            "rom": f"Redmi/miro/miro:15/AE3A.240806.005/OS2.0.10{random.choice(['5', '4', '2'])}.0.VOMCNXM:user/release-keys",
            "tmeAppID": "qqmusiclight",
            "nettype": "NETWORK_WIFI",
            "udid": "0",
        }
        self.inited = False
        self.init_lock = Lock()
        self.init()

    def init(self) -> None:
        with self.init_lock:
            if self.inited:
                return
            param = {"caller": 0, "uid": "0", "vkey": 0}
            data = self.request("GetSession", "music.getSession.session", param)
            self.comm = {
                **self.comm,
                "uid": data["session"]["uid"],
                "sid": data["session"]["sid"],
                "userip": data["session"]["userip"],
            }

    def request(self, method: str, module: str, param: dict) -> dict:
        """Send an API request.

        Args:
            method (str): request method
            module (str): request module
            param (dict): request parameters

        Returns:
            dict: response data

        """
        if not self.inited and method != "GetSession":
            self.init()
        data = json.dumps(
            {
                "comm": self.comm,
                "request": {
                    "method": method,
                    "module": module,
                    "param": param,
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        domains = [
            "u.y.qq.com",
        ]
        response = self.client.post(
            f"https://{random.choice(domains)}/cgi-bin/musicu.fcg",
            content=data,
        )
        response.raise_for_status()
        response_data = response.json()
        if response_data["code"] != 0 or response_data["request"]["code"] != 0:
            raise APIRequestError("qm API request error, code: " + str(response_data["code"] if response_data["code"] != 0 else response_data["request"]["code"]))
        return response_data["request"]["data"]

    def format_songinfos(self, songinfos: list) -> list[SongInfo]:
        return [
            SongInfo(
                source=self.source,
                id=str(info["id"]),
                mid=info["mid"],
                title=info["title"],
                subtitle=info["subtitle"],
                artist=Artist(singer["name"] for singer in info["singer"] if singer["name"] != ""),
                album=info["album"]["name"],
                duration=info["interval"] * 1000,
                language=LANGUAGE_MAPPING.get(info["language"], Language.OTHER),
            )
            for info in songinfos
        ]

    def search(self, keyword: str, search_type: SearchType, page: int = 1) -> APIResultList[SongInfo]:
        """Search for songs.

        Args:
            keyword (str): search keyword
            search_type (SearchType): search type
            page (int, optional): page number. Defaults to 1.

        Returns:
            APIResultList[SongInfo]: search results

        """
        pagesize = 20
        param = {
            "search_id": str(random.randint(1, 20) * 18014398509481984 + random.randint(0, 4194304) * 4294967296 + round(time.time() * 1000) % 86400000),
            "remoteplace": "search.android.keyboard",
            "query": keyword,
            "search_type": SEARCH_TYPE_MAPPING[search_type],
            "num_per_page": pagesize,
            "page_num": page,
            "highlight": 0,
            "nqc_flag": 0,
            "page_id": 1,
            "grp": 1,
        }
        data = self.request(
            "DoSearchForQQMusicLite",
            "music.search.SearchCgiService",
            param,
        )

        start_index = (page - 1) * pagesize
        return APIResultList(
            self.format_songinfos(data["body"]["item_song"]),
            SearchInfo(
                source=self.source,
                keyword=keyword,
                search_type=search_type,
                page=page,
            ),
            (
                start_index,
                start_index + len(data["body"]["item_song"]) - 1,
                data["meta"]["sum"] if len(data["body"]["item_song"]) == pagesize else start_index + len(data["body"]["item_song"]),
            ),
        )

    def get_lyrics(self, info: SongInfo) -> Lyrics:
        """Get lyrics.

        Args:
            info (SongInfo): song info

        Returns:
            Lyrics: the lyrics

        """
        if info.title is None or info.album is None or not info.id or info.duration is None:
            msg = "missing required parameters"
            raise APIParamsError(msg)

        param = {
            "albumName": b64encode(info.album.encode()).decode(),
            "crypt": 1,
            "ct": 19,
            "cv": 2111,
            "interval": info.duration // 1000,  # in seconds
            "lrc_t": 0,
            "qrc": 1,
            "qrc_t": 0,
            "roma": 1,
            "roma_t": 0,
            "singerName": b64encode(str(info.artist).encode()).decode() if info.artist else b64encode(b"").decode(),
            "songID": int(info.id),
            "songName": b64encode(info.title.encode()).decode(),
            "trans": 1,
            "trans_t": 0,
            "type": 0,
        }

        response = self.request("GetPlayLyricInfo", "music.musichallSong.PlayLyricInfo", param)
        lyrics = Lyrics(info)
        for key, value in [("orig", "lyric"), ("ts", "trans"), ("roma", "roma")]:
            lrc = response[value]
            lrc_t = (response["qrc_t"] if response["qrc_t"] != 0 else response["lrc_t"]) if value == "lyric" else response[value + "_t"]
            if lrc != "" and lrc_t != "0":
                encrypted_lyric = lrc

                lyric = qrc_decrypt(encrypted_lyric)

                if lyric is not None:
                    tags, lyric = qrc_str_parse(lyric)

                    if key == "orig":
                        lyrics.tags = tags

                    lyrics[key] = lyric
                    lyrics.types[key] = judge_lyrics_type(lyric)
        if not lyrics:
            msg = "no lyrics found"
            raise LyricsNotFoundError(msg, info)
        return lyrics
