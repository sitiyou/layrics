# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Logger (slimmed from LDDC: dropped CLI args/config file/file logging, plain stdlib logging)"""

import logging

logger = logging.getLogger("LDDC")
