# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only
"""Lyrics decryption (slimmed from LDDC: dropped qmc1 for local QRC, only cloud QRC and KRC kept)"""

from zlib import decompress

from layrics.LDDC.common.exceptions import LyricsDecryptError
from layrics.LDDC.common.logger import logger
from layrics.LDDC.core.decryptor.tripledes import (
    DECRYPT,
    tripledes_crypt,
    tripledes_key_setup,
)

QRC_KEY = b"!@#)(*$%123ZXC!@!@#)(NHL"
KRC_KEY = b"@Gaw^2tGQ61-\xce\xd2ni"


def qrc_decrypt(encrypted_qrc: str | bytearray | bytes) -> str:
    """Decrypt cloud QRC lyrics."""
    if encrypted_qrc is None or encrypted_qrc.strip() == "":
        logger.error("no data to decrypt")
        msg = "no data to decrypt"
        raise LyricsDecryptError(msg)

    if isinstance(encrypted_qrc, str):
        encrypted_text_byte = bytearray.fromhex(encrypted_qrc)  # parse the text into a byte array
    elif isinstance(encrypted_qrc, bytearray):
        encrypted_text_byte = encrypted_qrc
    elif isinstance(encrypted_qrc, bytes):
        encrypted_text_byte = bytearray(encrypted_qrc)
    else:
        logger.error("invalid encrypted data type")
        msg = "invalid encrypted data type"
        raise LyricsDecryptError(msg)

    try:
        data = bytearray()
        schedule = tripledes_key_setup(QRC_KEY, DECRYPT)

        # iterate over encrypted_text_byte in 8-byte blocks
        for i in range(0, len(encrypted_text_byte), 8):
            data += tripledes_crypt(encrypted_text_byte[i:], schedule)

        decrypted_qrc = decompress(data).decode("utf-8")
    except Exception as e:
        logger.exception("QRC decryption failed")
        msg = "QRC decryption failed"
        raise LyricsDecryptError(msg) from e
    return decrypted_qrc


def krc_decrypt(encrypted_lyrics: bytearray | bytes) -> str:
    if isinstance(encrypted_lyrics, bytes):
        encrypted_data = bytearray(encrypted_lyrics)[4:]
    elif isinstance(encrypted_lyrics, bytearray):
        encrypted_data = encrypted_lyrics[4:]
    else:
        logger.error("invalid encrypted data type")
        msg = "invalid encrypted data type"
        raise LyricsDecryptError(msg)

    try:
        decrypted_data = bytearray()
        for i, item in enumerate(encrypted_data):
            decrypted_data.append(item ^ KRC_KEY[i % len(KRC_KEY)])

        return decompress(decrypted_data).decode('utf-8')
    except Exception as e:
        logger.exception("KRC decryption failed")
        msg = "KRC decryption failed"
        raise LyricsDecryptError(msg) from e
