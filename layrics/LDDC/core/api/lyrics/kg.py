# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only

import hashlib
import json
import random
import time
from base64 import b64decode, b64encode
from threading import Lock
from typing import Literal

import httpx

from layrics.LDDC.common.data.cache import cache
from layrics.LDDC.common.exceptions import APIRequestError, LyricsNotFoundError
from layrics.LDDC.common.logger import logger
from layrics.LDDC.common.models import (
    APIResultList,
    Artist,
    Language,
    LyricInfo,
    Lyrics,
    MultiLyricsData,
    SearchInfo,
    SearchType,
    SongInfo,
    Source,
)
from layrics.LDDC.common.version import __version__
from layrics.LDDC.core.decryptor import krc_decrypt
from layrics.LDDC.core.parser.krc import krc2mdata
from layrics.LDDC.core.parser.utils import judge_lyrics_type, plaintext2data

from .models import CloudAPI

SEARCH_TYPE_MAPPING = {
    SearchType.SONG: ("http://complexsearch.kugou.com/v2/search/song", "SearchSong"),
}

LANGUAGE_MAPPING = {
    "伴奏": Language.INSTRUMENTAL,
    "纯音乐": Language.INSTRUMENTAL,
    "英语": Language.ENGLISH,
    "韩语": Language.KOREAN,
    "日语": Language.JAPANESE,
    "粤语": Language.CHINESE,
    "国语": Language.CHINESE,
}


class KGAPI(CloudAPI):
    source = Source.KG
    supported_search_types = (SearchType.SONG,)

    def __init__(self) -> None:
        self.client = httpx.Client()
        self.dfid = None
        self.init_lock = Lock()
        self.init()

    def init(self) -> None:
        with self.init_lock:
            if self.dfid is not None:
                return
            dfid = cache.get(("KG dfid", __version__))
            if not dfid:
                mid = hashlib.md5(str(int(time.time() * 1000)).encode("utf-8")).hexdigest()
                params = {"appid": "1014", "platid": "4", "mid": mid}

                # generate the signature
                sorted_values = sorted([str(v) for v in params.values() if v != ""])
                params["signature"] = hashlib.md5(f"1014{''.join(sorted_values)}1014".encode()).hexdigest()
                data = b64encode(b'{"uuid":""}').decode()

                # send the request
                response = httpx.post("https://userservice.kugou.com/risk/v1/r_register_dev", content=data, params=params)
                dfid = response.json().get("data", {}).get("dfid")
                if isinstance(dfid, str):
                    cache.set(("KG dfid", __version__), dfid, expire=1800)
                else:
                    logger.error("failed to get KG dfid")
                    dfid = "-"
            self.dfid = dfid

    def request(
        self,
        url: str,
        params: dict,
        module: str,
        method: Literal["GET", "POST"] = "GET",
        data: str | None = None,
        headers: dict | None = None,
    ) -> dict:
        headers = {
            "User-Agent": f"Android14-1070-11070-201-0-{module}-wifi",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip, deflate",
            "KG-Rec": "1",
            "KG-RC": "1",
            "KG-CLIENTTIMEMS": str(int(time.time() * 1000)),
            **(headers if headers else {}),
        }

        mid = hashlib.md5(str(int(time.time() * 1000)).encode("utf-8")).hexdigest()

        if module == "Lyric":
            params = {
                "appid": "3116",
                "clientver": "11070",
                **params,
            }
        else:
            params = {
                "userid": "0",
                "appid": "3116",
                "token": "",
                "clienttime": int(time.time()),
                "iscorrection": "1",
                "uuid": "-",
                "mid": mid,
                "dfid": "-",
                "clientver": "11070",
                "platform": "AndroidFilter",
                **params,
            }
        headers["mid"] = mid
        params["signature"] = hashlib.md5(
            (
                "LnT6xpN3khm36zse0QzvmgTZ3waWdRSA"
                + "".join([f"{k}={json.dumps(v) if isinstance(v, dict) else v}" for k, v in sorted(params.items())])
                + (data or "")
                + "LnT6xpN3khm36zse0QzvmgTZ3waWdRSA"
            ).encode(),
        ).hexdigest()

        response = (
            self.client.get(url, params=params, headers=headers) if method == "GET" else self.client.post(url, params=params, headers=headers, content=data)
        )
        response.raise_for_status()
        response_data = response.json()
        if response_data.get("error_code", 0) not in (0, 200):
            raise APIRequestError("kg API request error, code: " + str(response_data.get("error_code")) + f", message: {response_data.get('error_msg')}")
        return response_data

    def search(self, keyword: str, search_type: SearchType, page: int = 1) -> APIResultList[SongInfo]:
        pagesize = 20
        params = {
            "sorttype": "0",
            "keyword": keyword,
            "pagesize": pagesize,
            "page": page,
        }
        url, module = SEARCH_TYPE_MAPPING[search_type]
        try:
            data = self.request(url, params, module, headers={"x-router": "complexsearch.kugou.com"})
        except APIRequestError:
            logger.exception("kg API request error, falling back to the old interface")
            return self._old_search(keyword, search_type, page)

        if not data["data"]["lists"]:
            return APIResultList(
                [],
                SearchInfo(
                    source=self.source,
                    keyword=keyword,
                    search_type=search_type,
                    page=page,
                ),
                (0, 0, 0),
            )

        start_index = (page - 1) * pagesize
        return APIResultList(
            [
                SongInfo(
                    source=self.source,
                    id=str(info["ID"]),
                    hash=info["FileHash"],
                    title=info["SongName"],
                    subtitle=info["Auxiliary"],
                    artist=Artist(singer["name"] for singer in info["Singers"] if singer["name"] != ""),
                    album=info["AlbumName"],
                    duration=info["Duration"] * 1000,
                    language=LANGUAGE_MAPPING.get(info["trans_param"].get("language"), Language.OTHER),
                )
                for info in data["data"]["lists"]
            ],
            SearchInfo(
                source=self.source,
                keyword=keyword,
                search_type=search_type,
                page=page,
            ),
            (
                start_index,
                start_index + len(data["data"]["lists"]) - 1,
                data["data"]["total"] if len(data["data"]["lists"]) == pagesize else start_index + len(data["data"]["lists"]),
            ),
        )

    def _old_search(self, keyword: str, search_type: SearchType, page: int = 1) -> APIResultList[SongInfo]:
        """Fallback search API."""
        domain = random.choice(["mobiles.kugou.com", "msearchcdn.kugou.com", "mobilecdnbj.kugou.com", "msearch.kugou.com"])
        pagesize = 20

        url = f"http://{domain}/api/v3/search/song"
        params = {
            "showtype": "14",
            "highlight": "",
            "pagesize": "30",
            "tag_aggr": "1",
            "plat": "0",
            "sver": "5",
            "keyword": keyword,
            "correct": "1",
            "api_ver": "1",
            "version": "9108",
            "page": page,
        }

        response = self.client.get(url, params=params, timeout=3)
        response.raise_for_status()
        data = response.json()
        start_index = (page - 1) * pagesize
        return APIResultList(
            [
                SongInfo(
                    source=self.source,
                    id=str(info["album_audio_id"]),
                    hash=info["hash"],
                    title=info["songname"],
                    subtitle=info["topic"],
                    artist=Artist(info["singername"].split("、")),
                    album=info["album_name"],
                    duration=info["duration"] * 1000,
                    language=LANGUAGE_MAPPING.get(info["trans_param"].get("language"), Language.OTHER),
                )
                for info in data["data"]["info"]
            ],
            SearchInfo(
                source=self.source,
                keyword=keyword,
                search_type=search_type,
                page=page,
            ),
            (
                start_index,
                start_index + len(data["data"]["info"]) - 1,
                data["data"]["total"] if len(data["data"]["info"]) == pagesize else start_index + len(data["data"]["info"]),
            ),
        )

    def get_lyrics(self, info: SongInfo | LyricInfo) -> Lyrics:
        if isinstance(info, SongInfo):
            infos = self.get_lyricslist(info)
            if not infos:
                msg = "no lyrics found"
                raise LyricsNotFoundError(msg, info)
            info = infos[0]

        params = {
            "accesskey": info.accesskey,
            "charset": "utf8",
            "client": "mobi",
            "fmt": "krc",
            "id": info.id,
            "ver": "1",
        }
        url = "http://lyrics.kugou.com/download"
        data = self.request(url, params, "Lyric")
        lyrics = Lyrics(info.songinfo)
        if data["contenttype"] == 2:  # base64-encoded plaintext lyrics
            lyric = MultiLyricsData({"orig": plaintext2data(b64decode(data["content"]).decode("utf-8"))})
        else:
            lyrics.tags, lyric = krc2mdata(krc_decrypt(b64decode(data["content"])))
        lyrics.update(lyric)
        for key, lyric in lyrics.items():
            lyrics.types[key] = judge_lyrics_type(lyric)
        return lyrics

    def get_lyricslist(self, song_info: SongInfo) -> APIResultList[LyricInfo]:
        params = {
            "album_audio_id": song_info.id,
            "duration": song_info.duration,  # in milliseconds
            "hash": song_info.hash,
            "keyword": f"{'、'.join(song_info.artist) if isinstance(song_info.artist, list) else (song_info.artist or '')} - {song_info.title}",
            "lrctxt": "1",
            "man": "no",
        }
        url = "https://lyrics.kugou.com/v1/search"
        data = self.request(url, params, "Lyric")
        lyrics = data["candidates"]
        return APIResultList(
            [
                LyricInfo(
                    source=self.source,
                    id=str(lyric["id"]),
                    accesskey=lyric["accesskey"],
                    creator=lyric["nickname"],
                    duration=lyric["duration"],
                    score=lyric["score"],
                    songinfo=song_info,
                )
                for lyric in lyrics
            ],
            song_info,
            (0, len(lyrics) - 1, len(lyrics)),
        )
