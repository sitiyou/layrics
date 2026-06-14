#include "core/wayland/LayerShellProtocol.hpp"
#include "core/wayland/LayerSurface.hpp"
#include "core/wayland/ShmBuffer.hpp"
#include "core/wayland/WaylandContext.hpp"

#include <wayland-client.h>

#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <unistd.h>

int main() {
    try {
        WaylandContext ctx;

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

    fprintf(stderr, "[INFO] Configured surface: %dx%d\n", surface.width(),
            surface.height());

    ShmBuffer buffer;
    if (!buffer.allocate(ctx.shmFd, ctx.shm, surface.width(),
                         surface.height())) {
        return 1;
    }

    uint8_t *pixels = static_cast<uint8_t *>(buffer.data());
    for (int y = 0; y < buffer.height(); y++) {
        for (int x = 0; x < buffer.width(); x++) {
            size_t off =
                static_cast<size_t>(y) * buffer.stride() +
                static_cast<size_t>(x) * 4;
            pixels[off + 0] = 0xCC;
            pixels[off + 1] = 0x66;
            pixels[off + 2] = 0x22;
            pixels[off + 3] = 0xFF;
        }
    }

    surface.commitFrame(buffer.buffer());

    ctx.roundtrip();

    fprintf(stderr, "[INFO] Displaying test block for 1 second...\n");
    sleep(1);

    buffer.destroy();
    surface.destroy();

    fprintf(stderr, "[INFO] Test passed.\n");
    return 0;
    } catch (const std::exception &e) {
        fprintf(stderr, "[FATAL] %s\n", e.what());
        return 1;
    }
}
