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

// Overlay show/hide transition effects. The numeric values are the dispatch ids
// used by subtitle.vert; keep both sides in sync.
enum class TransitionEffect : int {
    None = 0,
    Fade = 1,
    Rise = 2,
    Zoom = 3,
    Cascade = 4,
    Wave = 5,
    Scatter = 6,
    Flip = 7,
    Wipe = 8,
    BlurIn = 9,
    Flash = 10,
};

inline constexpr int kTransitionEffectCount = 11;

// Per-frame overlay transform: progress 0 = hidden, 1 = fully shown.
struct RenderTransition {
    TransitionEffect effect = TransitionEffect::None;
    float progress = 1.0f;
    float amplitude = 48.0f;
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
