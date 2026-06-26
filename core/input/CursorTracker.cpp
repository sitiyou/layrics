#include "core/input/CursorTracker.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace CursorTracker {

static CompositorType s_type = CompositorType::Generic;
static bool s_detected = false;

CompositorType detectCompositor() {
    if (s_detected) {
        return s_type;
    }

    if (getenv("HYPRLAND_INSTANCE_SIGNATURE")) {
        s_type = CompositorType::Hyprland;
    } else if (getenv("SWAYSOCK") || getenv("I3SOCK")) {
        s_type = CompositorType::Sway;
    } else {
        s_type = CompositorType::Generic;
    }

    s_detected = true;
    return s_type;
}

static bool getHyprlandCursor(int &x, int &y) {
    const char *sig = getenv("HYPRLAND_INSTANCE_SIGNATURE");
    if (!sig) {
        return false;
    }

    int sock = socket(AF_UNIX, SOCK_STREAM, 0);
    if (sock < 0) {
        return false;
    }

    struct sockaddr_un addr{};
    addr.sun_family = AF_UNIX;

    const char *xdg = getenv("XDG_RUNTIME_DIR");
    if (xdg) {
        snprintf(addr.sun_path, sizeof(addr.sun_path),
                 "%s/hypr/%s/.socket.sock", xdg, sig);
    } else {
        snprintf(addr.sun_path, sizeof(addr.sun_path),
                 "/tmp/hypr/%s/.socket.sock", sig);
    }

    if (connect(sock, reinterpret_cast<struct sockaddr *>(&addr),
                sizeof(addr)) < 0) {
        close(sock);
        return false;
    }

    const char *cmd = "-j/cursorpos";
    if (write(sock, cmd, strlen(cmd)) < 0) {
        close(sock);
        return false;
    }

    char buf[256] = {};
    int n = static_cast<int>(read(sock, buf, sizeof(buf) - 1));
    close(sock);

    if (n <= 0) {
        return false;
    }
    buf[n] = '\0';

    const char *xStr = strstr(buf, "\"x\":");
    const char *yStr = strstr(buf, "\"y\":");
    if (xStr && yStr) {
        x = atoi(xStr + 4);
        y = atoi(yStr + 4);
        return true;
    }

    return false;
}

bool getGlobalPosition(int &x, int &y) {
    switch (detectCompositor()) {
    case CompositorType::Hyprland:
        return getHyprlandCursor(x, y);
    case CompositorType::Sway:
    case CompositorType::Generic:
    default:
        return false;
    }
}

} // namespace CursorTracker
