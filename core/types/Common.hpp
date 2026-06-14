#pragma once

#include <cstdint>
#include <vector>

struct RenderRect {
    int x, y, w, h;
};

struct RenderResult {
    std::vector<RenderRect> regions;
};
