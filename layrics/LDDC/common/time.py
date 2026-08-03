# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Time utilities (slimmed from LDDC: only time2ms needed by lrc parsing kept)"""


def time2ms(m: int | str, s: int | str, ms: int | str) -> int:
    """Convert m:s.ms to milliseconds."""
    if isinstance(ms, str) and len(ms) == 2:  # accept both 2- and 3-digit milliseconds
        ms += "0"
    return (int(m) * 60 + int(s)) * 1000 + int(ms)
