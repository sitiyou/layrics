# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from .models import LyricInfo, SongInfo


class LDDCError(Exception):
    """Base LDDC error."""


class LyricsProcessingError(LDDCError):
    """Lyrics processing error."""


class LyricsDecryptError(LyricsProcessingError):
    """Lyrics decryption error."""


class LyricsFormatError(LyricsProcessingError):
    """Lyrics format error."""


class APIError(LDDCError):
    """API call error."""


class APIParamsError(APIError):
    """Invalid API parameters."""


class APIRequestError(APIError):
    """API request error."""


class LyricsNotFoundError(APIError):
    """No lyrics found for the given song."""

    def __init__(self, msg: str, info: SongInfo | LyricInfo | None = None) -> None:
        super().__init__(msg)
        self.info = info
