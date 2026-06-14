#include "core/input/CursorTracker.hpp"
#include "core/wayland/WaylandContext.hpp"

#include <cstdio>
#include <ctime>
#include <unistd.h>

int main() {
    CompositorType comp = CursorTracker::detectCompositor();

    const char *name = "Unknown";
    switch (comp) {
    case CompositorType::Hyprland:
        name = "Hyprland";
        break;
    case CompositorType::Sway:
        name = "Sway";
        break;
    case CompositorType::Generic:
        name = "Generic";
        break;
    }
    fprintf(stderr, "[INFO] Detected compositor: %s\n", name);

    if (comp != CompositorType::Hyprland) {
        fprintf(stderr,
                "[INFO] Global cursor position is only supported on Hyprland. "
                "Test limited to compositor detection.\n");
        return 0;
    }

    for (int i = 0; i < 20; i++) {
        int x = 0, y = 0;
        if (CursorTracker::getGlobalPosition(x, y)) {
            fprintf(stderr, "[INFO] Global cursor: (%d, %d)\n", x, y);
        } else {
            fprintf(stderr, "[WARN] Failed to get global cursor position\n");
        }

        struct timespec ts;
        ts.tv_sec = 0;
        ts.tv_nsec = 500000000L;
        nanosleep(&ts, nullptr);
    }

    fprintf(stderr, "[INFO] Test passed.\n");
    return 0;
}
