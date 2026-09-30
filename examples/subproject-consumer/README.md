# subproject-consumer

Minimal project showing how another meson-python project reuses the layrics
overlay core as a meson subproject, compiled into its **own** package under its
**own** module name — no `consumer.core`, no separate `layrics-core` distribution.

## Layout

```
meson.build                          project + subproject('layrics') + package install
consumer/__init__.py                 re-exports the compiled extension
consumer/_overlay.<abi>.so           produced by the subproject
subprojects/layrics -> ../../..      local stand-in for a git submodule
```

`subprojects/layrics` is a symlink to this repository so the sample runs in
place. In a real project replace it with a submodule:

```bash
git submodule add https://github.com/sitiyou/layrics subprojects/layrics
```

## Build

```bash
meson setup build
meson compile -C build
DESTDIR=/tmp/out meson install -C build
```

or install it as a Python package:

```bash
pip install .
```

## Use

```python
from consumer import ApplicationController, StateView

ctrl = ApplicationController()
ctrl.start()
ctrl.set_ass_input("[Script Info]\nScriptType: v4.00+\n")
# ...
ctrl.stop()
ctrl.join()
```

## Customization

Two subproject options drive the build (`meson.options` in the layrics repo):

| option | default | meaning |
| --- | --- | --- |
| `core_module_name` | `core` | extension module / `.so` filename / `PyInit_<name>` symbol |
| `core_install_subdir` | `layrics` | package directory the extension is installed into |

Only the extension is built when layrics is a subproject: its app package and
the C++ tests are skipped. `core_module_name` must be a valid C identifier
(it becomes a preprocessor token) and should not collide with an existing
meson target name.
