import os

if "core" in {name.strip() for name in os.environ.get("LAYRICS_DEBUG", "").split(",")}:
    os.environ["ASSLAYER_DEBUG"] = "1"

from asslayer import ApplicationController

__all__ = ["ApplicationController"]
