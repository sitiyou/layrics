# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from .models import LyricInfo, SongInfo


class LDDCError(Exception):
    """LDDC 基础错误"""


class LyricsProcessingError(LDDCError):
    """歌词处理错误"""


class LyricsDecryptError(LyricsProcessingError):
    """歌词解密错误"""


class LyricsFormatError(LyricsProcessingError):
    """歌词格式错误"""


class APIError(LDDCError):
    """API调用错误"""


class APIParamsError(APIError):
    """API参数错误"""


class APIRequestError(APIError):
    """API请求错误"""


class LyricsNotFoundError(APIError):
    """没有歌词错误"""

    def __init__(self, msg: str, info: SongInfo | LyricInfo | None = None) -> None:
        super().__init__(msg)
        self.info = info
