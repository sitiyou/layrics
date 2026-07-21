import os
import sys

_vendor = os.path.join(os.path.dirname(__file__), "vendor")
if os.path.isdir(_vendor) and _vendor not in sys.path:
    sys.path.insert(0, _vendor)

from ._layrics import ApplicationController

__all__ = ["ApplicationController"]
