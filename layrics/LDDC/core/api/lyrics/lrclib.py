# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only

import json

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
from layrics.LDDC.common.version import __version__
from layrics.LDDC.core.parser.lrc import lrc2data
from layrics.LDDC.core.parser.utils import judge_lyrics_type, plaintext2data

from .models import CloudAPI


class LrclibAPI(CloudAPI):
    source = Source.LRCLIB
    supported_search_types = (SearchType.SONG,)

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": f"LDDC/{__version__}",
                "Accept": "application/json",
            },
            timeout=30,
        )

    async def _make_request(self, endpoint: str, params: dict | None = None) -> dict:
        """Send an API request."""
        url = f"https://lrclib.net/api{endpoint}"
        response = await self.client.get(url, params=params)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            msg = f"lrclib API request failed: {response.status_code}"
            raise APIRequestError(msg) from e

        try:
            return response.json()
        except json.JSONDecodeError as e:
            msg = "lrclib API response could not be parsed"
            raise APIRequestError(msg) from e

    def _parse_song_info(self, data: dict) -> SongInfo:
        """Parse song info from API data."""
        return SongInfo(
            source=self.source,
            title=data["trackName"],
            artist=Artist(data["artistName"]),
            album=data["albumName"],
            duration=int(data["duration"] * 1000),  # API returns seconds, convert to ms
            id=str(data["id"]),
            language=Language.INSTRUMENTAL if data["instrumental"] else Language.OTHER,
        )

    async def get_lyrics(self, info: SongInfo) -> Lyrics:
        """Get lyrics."""
        if not info.title or not info.artist or not info.album or not info.duration:
            msg = "missing required parameters"
            raise APIParamsError(msg)

        params = {"track_name": info.title, "artist_name": info.artist.str(), "album_name": info.album, "duration": info.duration / 1000}
        data = await self._make_request("/get", params)

        if "error" in data:
            msg = f"lrclib API error: {data['error']}"
            raise APIRequestError(msg)

        lyrics = Lyrics(info)
        lyrics.tags = {
            "ti": data["trackName"],
            "ar": data["artistName"],
            "al": data["albumName"],
        }

        # handle synced lyrics
        if data.get("syncedLyrics"):
            tags, lyrics["orig"] = lrc2data(data["syncedLyrics"])
            lyrics.types["orig"] = judge_lyrics_type(lyrics["orig"])
            lyrics.tags.update(tags)

        # handle plain-text lyrics
        elif data.get("plainLyrics"):
            lyrics["orig"] = plaintext2data(data["plainLyrics"])
            lyrics.types["orig"] = judge_lyrics_type(lyrics["orig"])

        if not lyrics:
            msg = "no lyrics found"
            raise LyricsNotFoundError(msg, info)
        return lyrics

    async def search(self, keyword: str, search_type: SearchType, page: int = 1) -> APIResultList[SongInfo]:
        """Search for songs."""
        if search_type not in self.supported_search_types:
            msg = f"unsupported search type: {search_type}"
            raise NotImplementedError(msg)

        params = {"q": keyword}
        response = await self._make_request("/search", params)

        if "error" in response:
            msg = f"lrclib API error: {response['error']}"
            raise APIRequestError(msg)

        items = [self._parse_song_info(item) for item in response]
        items = items[(page - 1) * 20 : page * 20]  # paginate

        return APIResultList(items, SearchInfo(source=self.source, keyword=keyword, search_type=search_type, page=page), (0, len(items) - 1, len(items)))
