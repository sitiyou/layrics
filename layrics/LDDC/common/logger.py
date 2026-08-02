# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only

"""日志记录器(精简自 LDDC:去掉了 CLI 参数/配置文件/文件日志,直接使用标准 logging)"""

import logging

logger = logging.getLogger("LDDC")
