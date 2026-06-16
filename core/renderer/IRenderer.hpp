#pragma once

#include <cairo.h>
#include <cstdint>
#include <vector>

#include "core/types/Common.hpp"

class IRenderer {
  public:
    virtual ~IRenderer() = default;

    virtual bool initialize() = 0;
    virtual void shutdown() = 0;

    virtual cairo_surface_t *render(int64_t timestampMs) = 0;
    virtual void setSize(int width, int height) = 0;

    std::vector<RenderRect> lastRegions;
    bool contentChanged = true;
};
