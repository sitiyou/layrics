#include "core/input/RegionManager.hpp"
#include "core/utils/Logger.hpp"

#include <wayland-client.h>

#include <algorithm>

void RegionManager::update(wl_compositor *compositor, wl_surface *surface,
                           const std::vector<RenderRect> &rects,
                           int surfaceWidth, int surfaceHeight) {
    if (!compositor || !surface) {
        return;
    }

    wl_region *region = wl_compositor_create_region(compositor);
    if (!region) {
        return;
    }

    for (const auto &r : rects) {
        int rx = r.x;
        int ry = r.y;
        int rw = r.w;
        int rh = r.h;

        if (rx < 0) {
            rw += rx;
            rx = 0;
        }
        if (ry < 0) {
            rh += ry;
            ry = 0;
        }
        if (rx + rw > surfaceWidth) {
            rw = surfaceWidth - rx;
        }
        if (ry + rh > surfaceHeight) {
            rh = surfaceHeight - ry;
        }

        if (rw > 0 && rh > 0) {
            wl_region_add(region, rx, ry, rw, rh);
        }
    }

    wl_surface_set_input_region(surface, region);
    wl_region_destroy(region);

    // LAY_DEBUG("input region updated: %zu rects (clamped to %dx%d)", rects.size(), surfaceWidth, surfaceHeight);
}

void RegionManager::clear(wl_compositor *compositor, wl_surface *surface) {
    if (!compositor || !surface) {
        return;
    }

    wl_region *region = wl_compositor_create_region(compositor);
    if (!region) {
        return;
    }

    wl_surface_set_input_region(surface, region);
    wl_region_destroy(region);

    LAY_DEBUG("input region cleared");
}
