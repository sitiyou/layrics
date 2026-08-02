# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only

"""时间工具(精简自 LDDC:仅保留 lrc 解析所需的 time2ms)"""


def time2ms(m: int | str, s: int | str, ms: int | str) -> int:
    """时间转毫秒"""
    if isinstance(ms, str) and len(ms) == 2:  # 同时支持两位和三位毫秒
        ms += "0"
    return (int(m) * 60 + int(s)) * 1000 + int(ms)
