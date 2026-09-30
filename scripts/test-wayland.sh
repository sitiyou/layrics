#!/usr/bin/env bash
# Run the Wayland integration tests against a throwaway headless sway, so a
# test run never touches the developer's own session. Arguments replace the
# default unittest command.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
outputs=${LAY_TEST_OUTPUTS:-1}
mode=${LAY_TEST_MODE:-1280x720}

if ! command -v sway > /dev/null; then
    echo "test-wayland: sway is required (a wlroots compositor with wlr-layer-shell)" >&2
    exit 1
fi

runtime_dir=$(mktemp -d)
chmod 700 "$runtime_dir"
sway_pid=

cleanup() {
    if [[ -n $sway_pid ]]; then
        kill -- "-$sway_pid" 2> /dev/null || kill "$sway_pid" 2> /dev/null || true
        wait "$sway_pid" 2> /dev/null || true
    fi
    rm -rf "$runtime_dir"
}
trap cleanup EXIT

printf 'output * mode %s\ninput * events disabled\n' "$mode" > "$runtime_dir/sway.conf"

# The private XDG_RUNTIME_DIR keeps the compositor out of the real session, and
# dropping WAYLAND_DISPLAY stops it from nesting inside it instead.
# seat0 needs input devices because the layer-shell client takes a wl_pointer at
# startup and a headless-only seat advertises no capabilities at all; the real
# session already owns logind's seat, hence the noop libseat backend.
# Events from those devices are switched off in the sway config: capabilities
# stay, real keyboard/mouse traffic does not leak into the tests.
env -u WAYLAND_DISPLAY -u DISPLAY -u SWAYSOCK \
    XDG_RUNTIME_DIR="$runtime_dir" \
    WLR_BACKENDS=headless,libinput \
    LIBSEAT_BACKEND=noop \
    WLR_RENDERER=gles2 \
    WLR_HEADLESS_OUTPUTS="$outputs" \
    setsid sway -c "$runtime_dir/sway.conf" > "$runtime_dir/sway.log" 2>&1 &
sway_pid=$!

export XDG_RUNTIME_DIR=$runtime_dir
export WAYLAND_DISPLAY=wayland-1

sway_socket=
for _ in {1..50}; do
    for sock in "$runtime_dir"/sway-ipc.*.sock; do
        [[ -e $sock ]] && sway_socket=$sock
    done
    [[ -n $sway_socket ]] && break
    kill -0 "$sway_pid" 2> /dev/null || break
    sleep 0.1
done
if [[ -z $sway_socket ]]; then
    cat "$runtime_dir/sway.log" >&2
    echo "test-wayland: headless sway failed to start" >&2
    exit 1
fi
export SWAYSOCK=$sway_socket

cd "$repo_root"
if (($# > 0)); then
    "$@"
else
    uv run python -m unittest tests.test_wayland_state
fi
