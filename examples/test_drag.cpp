#include "core/input/DragManager.hpp"
#include "core/input/InputManager.hpp"
#include "core/wayland/LayerShellProtocol.hpp"
#include "core/wayland/LayerSurface.hpp"
#include "core/wayland/ShmBuffer.hpp"
#include "core/wayland/WaylandContext.hpp"

#include <wayland-client.h>

#include <cstdint>
#include <cstdio>
#include <poll.h>
#include <stdexcept>
#include <sys/timerfd.h>
#include <unistd.h>

static void fillBlock(uint8_t *pixels, int bufW, int bufH, int stride) {
    for (int y = 0; y < bufH; y++) {
        for (int x = 0; x < bufW; x++) {
            size_t off =
                static_cast<size_t>(y) * stride + static_cast<size_t>(x) * 4;
            pixels[off + 0] = 0x44;
            pixels[off + 1] = 0x88;
            pixels[off + 2] = 0xCC;
            pixels[off + 3] = 0xFF;
        }
    }
}

int main() {
    try {
        WaylandContext ctx;
        if (!ctx.seat) {
            fprintf(stderr, "[ERR] No seat available\n");
            return 1;
        }

        LayerSurfaceConfig surfCfg;
        surfCfg.anchor = ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP |
                         ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT;
        surfCfg.desiredWidth = 300;
        surfCfg.desiredHeight = 200;
        surfCfg.exclusiveZone = -1;
        surfCfg.keyboardInteractivity =
            ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_NONE;

        LayerSurface surface;
        if (!surface.initialize(ctx, nullptr, ZWLR_LAYER_SHELL_V1_LAYER_OVERLAY,
                                surfCfg)) {
            return 1;
        }

        fprintf(stderr, "[INFO] Configured: %dx%d\n", surface.width(),
                surface.height());

        ShmBuffer buffer;
        if (!buffer.allocate(ctx.shmFd, ctx.shm, surface.width(),
                             surface.height())) {
            return 1;
        }

        uint8_t *pixels = static_cast<uint8_t *>(buffer.data());
        fillBlock(pixels, buffer.width(), buffer.height(), buffer.stride());

        InputManager inputMgr;
        if (!inputMgr.initialize(ctx.seat)) {
            fprintf(stderr, "[ERR] Failed to initialize InputManager\n");
            return 1;
        }

        DragManager dragMgr;

        bool dragging = false;
        double offsetX = 0.0;
        double offsetY = 0.0;

        inputMgr.setMotionCallback(
            [&dragMgr](double x, double y) { dragMgr.onMotion(x, y); });

        inputMgr.setButtonCallback(
            [&dragMgr](uint32_t button, uint32_t state, double x, double y) {
                dragMgr.onButton(button, state, x, y);
            });

        fprintf(stderr,
                "[INFO] Drag test running. Drag the window with left mouse "
                "button. Press Ctrl+C to exit.\n");

        int displayFd = ctx.displayFd();
        int timerFd = timerfd_create(CLOCK_MONOTONIC, TFD_CLOEXEC);
        struct itimerspec its{};
        its.it_value.tv_nsec = 100000000;
        its.it_interval.tv_nsec = 100000000;
        timerfd_settime(timerFd, 0, &its, nullptr);

        surface.commitFrame(buffer.buffer());

        int iter = 0;
        while (iter < 300) {
            ctx.flush();

            struct pollfd fds[2];
            fds[0].fd = displayFd;
            fds[0].events = POLLIN;
            fds[1].fd = timerFd;
            fds[1].events = POLLIN;

            int ret = poll(fds, 2, -1);
            if (ret < 0) {
                break;
            }

            if (fds[0].revents & POLLIN) {
                wl_display_dispatch(ctx.display);
            }

            if (fds[1].revents & POLLIN) {
                uint64_t exp = 0;
                read(timerFd, &exp, sizeof(exp));
                iter++;

                bool nowDragging = dragMgr.dragging();
                const auto &st = dragMgr.state();

                if (nowDragging != dragging || st.offsetX != offsetX ||
                    st.offsetY != offsetY) {
                    dragging = nowDragging;
                    offsetX = st.offsetX;
                    offsetY = st.offsetY;
                    fprintf(stderr, "[INFO] Drag: %s  offset=(%.1f, %.1f)\n",
                            dragging ? "ACTIVE" : "idle", offsetX, offsetY);
                }
            }
        }

        close(timerFd);
        inputMgr.release();
        buffer.destroy();
        surface.destroy();

        fprintf(stderr, "[INFO] Test passed.\n");
        return 0;
    } catch (const std::exception &e) {
        fprintf(stderr, "[FATAL] %s\n", e.what());
        return 1;
    }
}
