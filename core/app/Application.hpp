#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>

#include "core/input/CursorManager.hpp"
#include "core/input/DamageGrid.hpp"
#include "core/input/DragManager.hpp"
#include "core/input/InputManager.hpp"
#include "core/input/KeyboardManager.hpp"
#include "core/input/RegionManager.hpp"
#include "core/renderer/IRenderer.hpp"
#include "core/renderer/RenderManager.hpp"
#include "core/renderer/Transition.hpp"
#include "core/renderer/VulkanContext.hpp"
#include "core/ui/UIManager.hpp"
#include "core/utils/FrameRateLimiter.hpp"
#include "core/wayland/LayerSurface.hpp"
#include "core/wayland/WaylandContext.hpp"

struct wl_callback;
class AssRenderer;

class ApplicationController;

class Application {
    friend class ApplicationController;

  public:
    Application();
    ~Application();

    Application(const Application &) = delete;
    Application &operator=(const Application &) = delete;

    void run();

    void loadAssContent(const std::string &content);
    void requestStop();
    void setUiMenuItems(std::vector<UiMenuItem> items);
    // Queue a menu open at surface coordinates (tray ContextMenu); consumed by
    // processState().
    void openUiMenu(double x, double y);

    // Pure state setters — no side-effects
    void setPaused(bool v) { m_state.paused = v; }
    void setHidden(bool v) { m_state.hidden = v; }
    void setLocked(bool v) { m_state.locked = v; }
    void setStartTime(int64_t v) { m_state.startTimeMs = v; }
    void setTargetFps(int v);
    void setTransitionConfig(TransitionEffect effect, int durationMs,
                             int amplitude);

    // Explicit actions — must be called explicitly
    void hideDisplay();
    void applyLockedInputRegion();
    void updateCursor();

    const AppState &state() const { return m_state; }

    static void frameDone(void *data, wl_callback *cb, uint32_t time);

  private:
    WaylandContext m_waylandCtx;
    LayerSurface m_surface;
    VulkanContext m_vk;
    // Declared after m_vk: destroyed (shutdown) before the VulkanContext.
    UIManager m_uiMgr;
    RenderManager m_renderMgr;
    // Show/hide animation; non-identity only while a hide/unhide is in flight.
    Transition m_transition;
    bool m_hideFinalized = true;
    // First-paint entrance is a one-shot: only the very first lyrics to reach
    // the screen animate in, later content swaps appear in place. A manual
    // visibility toggle supersedes it (that fade already covers "appearing").
    bool m_introPlayed = false;
    FrameRateLimiter m_frameRateLimiter;
    DamageGrid m_damageGrid;
    InputManager m_inputMgr;
    DragManager m_dragMgr;
    RegionManager m_regionMgr;
    CursorManager m_cursorMgr;
    KeyboardManager m_keyboardMgr;

    // Current layer-surface keyboard interactivity: ON_DEMAND while the
    // pointer is inside the input region, NONE otherwise.
    bool m_keyboardInteractive = false;

    std::atomic<bool> m_running{true};
    wl_callback *m_frameCallback = nullptr;
    AssRenderer *m_assRenderer = nullptr;
    std::function<void()> m_processCommands;
    std::function<void(const KeyEvent &)> m_keyEventSink;
    std::function<void(const std::string &)> m_uiEventSink;
    bool m_uiMenuWasOpen = false;
    bool m_openMenuRequested = false;
    double m_openMenuX = 0.0;
    double m_openMenuY = 0.0;

    // Frozen rendering timestamp (CLOCK_MONOTONIC ms) while paused; captured
    // in mainLoop() when the pause command is processed.
    int64_t m_freezeTimestampMs = 0;

    AppState m_state{};

    bool initWayland();
    bool initRenderer();
    bool initInput();
    bool initVulkan();

    void mainLoop();
    void processState();
    void produceFrame(int64_t timestampMs);
    void updateInputRegion();
    void requestFrame();

    void onFrame(uint32_t time);
    void onPointerMotion(double x, double y);
    void onPointerButton(uint32_t button, uint32_t state, double x, double y);
    void onKey(uint32_t key, uint32_t state, uint32_t mods);
    void onUiAction(const std::string &action);
    void resetDrag();
    void setInputInteractive(bool on);
    void onSurfaceConfigure(int width, int height);
};
