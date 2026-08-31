#pragma once

#include <cstdint>
#include <string>
#include <vector>

struct RenderRect {
    int x, y, w, h;
};

// Right-click menu item as pushed from Python. Leaf items carry an action id
// that is reported back on click; items with children render as submenus.
// The C++ side is a pure renderer: menu content and handling live in Python.
struct UiMenuItem {
    std::string label;
    std::string action;                // leaf action; empty for submenus
    std::vector<UiMenuItem> children;  // submenu entries
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

struct KeyEvent {
    uint32_t key;    // raw evdev keycode
    uint32_t state;  // WL_KEYBOARD_KEY_STATE_PRESSED / _RELEASED
    uint32_t mods;   // wl_keyboard modifier mask
};
