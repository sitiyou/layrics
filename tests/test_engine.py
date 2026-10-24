import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("debug", "engine_debug", "expected"),
    [
        ("core", None, "1"),
        ("lyrics, core ,match", "0", "1"),
        ("lyrics", None, None),
        ("hardcore", None, None),
        ("", "1", "1"),
    ],
)
def test_engine_debug_environment(debug, engine_debug, expected):
    environment = os.environ.copy()
    environment["LAYRICS_DEBUG"] = debug
    environment.pop("ASSLAYER_DEBUG", None)
    if engine_debug is not None:
        environment["ASSLAYER_DEBUG"] = engine_debug
    initializer = Path(__file__).resolve().parents[1] / "layrics" / "__init__.py"
    probe = """
import json
import os
import runpy
import sys
import types

module = types.ModuleType("asslayer")
module.ApplicationController = object
sys.modules["asslayer"] = module
runpy.run_path(sys.argv[1])
print(json.dumps(os.environ.get("ASSLAYER_DEBUG")))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, str(initializer)],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == expected
