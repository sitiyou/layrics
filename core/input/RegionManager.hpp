#pragma once

#include <vector>

#include "core/types/Common.hpp"

struct wl_compositor;
struct wl_surface;

class RegionManager {
  public:
    void update(wl_compositor *compositor, wl_surface *surface,
                const std::vector<RenderRect> &rects, int surfaceWidth,
                int surfaceHeight);

    void clear(wl_compositor *compositor, wl_surface *surface);
};
