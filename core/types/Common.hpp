#pragma once

#include <cstdint>
#include <vector>

struct RenderRect {
    int x, y, w, h;
};

struct RenderResult {
    std::vector<RenderRect> regions;
    bool contentChanged = true;
};

struct AppState {
    bool paused = false;
    bool hidden = false;
    bool locked = false;
    int64_t startTimeMs = 0;
    double dragOffsetX = 0.0;
    double dragOffsetY = 0.0;
    int targetFps = -1;
};
