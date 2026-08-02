# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only

import json
import random
import secrets
import string
import time
from threading import Lock

import httpx

from layrics.LDDC.common.data.cache import cache
from layrics.LDDC.common.exceptions import APIRequestError
from layrics.LDDC.common.logger import logger
from layrics.LDDC.common.models import (
    APIResultList,
    Artist,
    Lyrics,
    SearchInfo,
    SearchType,
    SongInfo,
    Source,
)
from layrics.LDDC.common.version import __version__
from layrics.LDDC.core.decryptor.eapi import (
    eapi_params_encrypt,
    eapi_response_decrypt,
    get_anonimous_username,
)
from layrics.LDDC.core.parser.lrc import lrc2data
from layrics.LDDC.core.parser.utils import judge_lyrics_type, plaintext2data
from layrics.LDDC.core.parser.yrc import yrc2data

from .models import CloudAPI


class NEAPI(CloudAPI):
    source = Source.NE
    supported_search_types = (SearchType.SONG,)

    def __init__(self) -> None:
        self.inited = False
        self.init_lock = Lock()
        self.init()

    def init(self) -> None:
        with self.init_lock:
            if self.inited and self.expire > int(time.time()):
                return

            # 游客登录
            anonimous = cache.get(("NE_anonimous", __version__), None)  # user_id, cookies, expire_time
            if not isinstance(anonimous, dict) or time.time() > anonimous["expire"]:
                # 生成部分cookies
                # clientSign
                mac = ":".join([f"{secrets.randbelow(255):02X}" for _ in range(6)])  # MAC地址部分
                random_str = "".join(secrets.choice(string.ascii_uppercase) for _ in range(8))  # 随机大写字母部分
                hash_part = secrets.token_hex(32)  # 32字节生成64字符
                client_sign = f"{mac}@@@{random_str}@@@@@@{hash_part}"
                from layrics.LDDC.res.ne_deviceids import get_device_id

                pre_cookies = {
                    "os": "pc",
                    "deviceId": get_device_id(),
                    "osver": f"Microsoft-Windows-10--build-{random.randint(200, 300)}00-64bit",
                    "clientSign": client_sign,
                    "channel": "netease",
                    "mode": random.choice(["MS-iCraft B760M WIFI", "ASUS ROG STRIX Z790", "MSI MAG B550 TOMAHAWK", "ASRock X670E Taichi"]),  # 随机生成设备型号
                    "appver": "3.1.3.203419",
                }

                path = "/eapi/register/anonimous"
                params = {"username": get_anonimous_username(pre_cookies["deviceId"]), "e_r": True, "header": self._get_params_header(pre_cookies)}
                encrypted_params = eapi_params_encrypt(path.replace("eapi", "api").encode(), params)
                logger.info("ne 尝试游客登录")
                with httpx.Client(http2=True) as client:
                    response = client.post(
                        "https://interface.music.163.com" + path,
                        headers=self._get_header(pre_cookies),
                        content=encrypted_params,
                        timeout=15,
                    )
                response.raise_for_status()
                data = json.loads(eapi_response_decrypt(response.content))
                logger.info(f"ne 游客登录code: {data['code']}")
                response_cookies = response.cookies  # 获取响应的cookies
                self.cookies = {
                    "WEVNSM": "1.0.0",
                    "os": pre_cookies["os"],
                    "deviceId": pre_cookies["deviceId"],
                    "osver": pre_cookies["osver"],
                    "clientSign": pre_cookies["clientSign"],
                    "channel": "netease",
                    "mode": pre_cookies["mode"],
                    "NMTID": response_cookies.get("NMTID", ""),
                    "MUSIC_A": response_cookies.get("MUSIC_A", ""),
                    "__csrf": response_cookies.get("__csrf", ""),
                    "appver": pre_cookies["appver"],
                    "WNMCID": f"{''.join(random.choice(string.ascii_lowercase) for _ in range(6))}."
                    f"{int(time.time() * 1000) - random.randint(1000, 10000)}.01.0",
                }  # 合并cookies(保持顺序)
                self.user_id = data["userId"]
                self.expire = int(time.time()) + 864000
                for k in [k for k, v in self.cookies.items() if not v]:
                    logger.warning(f"ne 游客登录未获取到cookie: {k}")
                    self.cookies.pop(k)
                cache.set(("NE_anonimous", __version__), {"user_id": self.user_id, "cookies": self.cookies, "expire": self.expire})
                # csrf 15天过期 所以10天过期
            else:
                self.cookies = anonimous["cookies"]
                self.user_id = anonimous["user_id"]
                self.expire = anonimous["expire"]
                logger.info("ne 使用缓存游客登录")

            self.session = httpx.Client(http2=True)  # 创建session
            self.inited = True

            def _atexit() -> None:
                if self.expire > int(time.time()):
                    cache.set(("NE_anonimous", __version__), {"user_id": self.user_id, "cookies": self.cookies, "expire": self.expire})
            import atexit
            atexit.register(_atexit)

    def request(self, path: str, params: dict) -> dict:
        """eapi接口请求

        :param path: 请求的路径
        :param params: 请求参数
        :return dict: 请求结果
        """
        params["e_r"] = True  # 开启加密
        params["header"] = self.get_params_header()
        encrypted_params = eapi_params_encrypt(path.replace("eapi", "api").encode(), params)
        url = "https://interface.music.163.com" + path
        if not self.inited or self.expire < int(time.time()):
            self.init()
        response = self.session.post(
            url,
            params={"cache_key": params["cache_key"]} if "cache_key" in params else None,
            headers=self._get_header(self.cookies),
            content=encrypted_params,
            timeout=10,
        )
        response.raise_for_status()
        data = json.loads(eapi_response_decrypt(response.content))
        if data["code"] != 200:
            raise APIRequestError("ne API请求错误,错误码:" + str(data["code"]) + ",错误信息:" + data["message"])
        return data

    def _get_params_header(self, cookies: dict) -> str:
        return json.dumps(
            {
                "clientSign": cookies["clientSign"],
                "os": cookies["os"],
                "appver": cookies["appver"],
                "deviceId": cookies["deviceId"],
                "requestId": 0,
                "osver": cookies["osver"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def get_params_header(self) -> str:
        if not self.inited or self.expire < int(time.time()):
            self.init()
        return self._get_params_header(self.cookies)

    def _get_header(self, cookies: dict) -> list[tuple[str, str]]:
        return [
            ("accept", "*/*"),
            ("content-type", "application/x-www-form-urlencoded"),
            *[("cookie", f"{k}={v}") for k, v in cookies.items()],
            ("mconfig-info", '{"IuRPVVmc3WWul9fT":{"version":733184,"appver":"3.1.3.203419"}}'),
            ("origin", "orpheus://orpheus"),
            (
                "user-agent",
                "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Safari/537.36 Chrome/91.0.4472.164 NeteaseMusicDesktop/3.1.3.203419",
            ),
            ("sec-ch-ua", '"Chromium";v="91"'),
            ("sec-ch-ua-mobile", "?0"),
            ("sec-fetch-site", "cross-site"),
            ("sec-fetch-mode", "cors"),
            ("sec-fetch-dest", "empty"),
            ("accept-encoding", "gzip, deflate, br"),
            ("accept-language", "en-US,en;q=0.9"),
        ]

    def format_songinfos(self, songinfos: list) -> list[SongInfo]:
        return [
            SongInfo(
                source=self.source,
                id=str(info["id"]),
                title=info["name"],
                subtitle=info["alia"][0] if info["alia"] else "",
                artist=Artist(singer["name"] for singer in info["ar"] if singer["name"] != ""),
                album=info["al"]["name"],
                duration=info["dt"],
            )
            for info in songinfos
        ]

    def search(self, keyword: str, search_type: SearchType, page: int = 1) -> APIResultList[SongInfo]:
        """网易云音乐搜索

        Args:
            keyword (str): 关键字
            search_type (SearchType): 搜索类型
            page (int, optional): 页码. Defaults to 1.

        Returns:
            APIResultList[SongInfo]: 搜索结果

        """
        pagesize = 20
        params = {
            "limit": str(pagesize),  # 网易云默认是10
            "offset": str((page - 1) * pagesize),
            "keyword": keyword,
            "scene": "NORMAL",
            "needCorrect": "true",
        }
        data = self.request("/eapi/search/song/list/page", params)
        if ("result" not in data and "data" not in data) or ("data" in data and data["data"]["resources"] is None):
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
            self.format_songinfos(
                [song["baseInfo"]["simpleSongData"] for song in data["data"]["resources"]],
            ),
            SearchInfo(
                source=self.source,
                keyword=keyword,
                search_type=search_type,
                page=page,
            ),
            (
                start_index,
                start_index + len(data["data"]["resources"]) - 1,
                data["data"]["totalCount"] if len(data["data"]["resources"]) == pagesize else start_index + len(data["data"]["resources"]),
            ),
        )

    def get_lyrics(self, info: SongInfo) -> Lyrics:
        """获取歌词

        Args:
            info (SongInfo): 歌曲信息

        Returns:
            Lyrics: 歌词

        """
        if not info.id:
            msg = "歌曲id为空"
            raise ValueError(msg)
        params = {
            "id": int(info.id),
            "lv": "-1",
            "tv": "-1",
            "rv": "-1",
            "yv": "-1",
        }
        data = self.request("/eapi/song/lyric/v1", params)

        lyrics = Lyrics(info)
        tags = {}

        if info.artist:
            tags.update({"ar": "/".join(info.artist) if not isinstance(info.artist, str) else info.artist})
        if info.album:
            tags.update({"al": info.album})
        if info.title:
            tags.update({"ti": info.title})
        if "lyricUser" in data and "nickname" in data["lyricUser"]:
            tags.update({"by": data["lyricUser"]["nickname"]})
        if "transUser" in data and "nickname" in data["transUser"]:
            if "by" in tags and tags["by"] != data["transUser"]["nickname"]:
                tags["by"] += f" & {data['transUser']['nickname']}"
            elif "by" not in tags:
                tags.update({"by": data["transUser"]["nickname"]})
        lyrics.tags = tags
        if "yrc" in data and len(data["yrc"]["lyric"]) != 0:
            mapping_table = [("orig", "yrc"), ("ts", "tlyric"), ("roma", "romalrc"), ("orig_lrc", "lrc")]
        else:
            mapping_table = [("orig", "lrc"), ("ts", "tlyric"), ("roma", "romalrc")]
        for key, value in mapping_table:
            if value not in data:
                continue
            if isinstance(data[value]["lyric"], str) and len(data[value]["lyric"]) != 0:
                if value == "yrc":
                    lyrics[key] = yrc2data(data[value]["lyric"])
                elif "[" in data[value]["lyric"] and "]" in data[value]["lyric"]:
                    lyrics[key] = lrc2data(data[value]["lyric"], source=Source.NE)[1]
                else:
                    lyrics[key] = plaintext2data(data[value]["lyric"])
                lyrics.types[key] = judge_lyrics_type(lyrics[key])
        return lyrics
