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
#include "core/input/RegionManager.hpp"
#include "core/renderer/IRenderer.hpp"
#include "core/renderer/RenderManager.hpp"
#include "core/utils/FrameRateLimiter.hpp"
#include "core/wayland/LayerSurface.hpp"
#include "core/wayland/ShmBuffer.hpp"
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

    // Pure state setters — no side-effects
    void setPaused(bool v)       { m_state.paused = v; }
    void setHidden(bool v)       { m_state.hidden = v; }
    void setLocked(bool v)       { m_state.locked = v; }
    void setStartTime(int64_t v) { m_state.startTimeMs = v; }
    void setTargetFps(int v);

    // Explicit actions — must be called explicitly
    void hideDisplay();
    void applyLockedInputRegion();
    void updateCursor();

    const AppState& state() const { return m_state; }

    static void frameDone(void *data, wl_callback *cb, uint32_t time);

  private:
    WaylandContext m_waylandCtx;
    LayerSurface m_surface;
    ShmBuffer m_buffer;
    RenderManager m_renderMgr;
    FrameRateLimiter m_frameRateLimiter;
    DamageGrid m_damageGrid;
    InputManager m_inputMgr;
    DragManager m_dragMgr;
    RegionManager m_regionMgr;
    CursorManager m_cursorMgr;

    std::atomic<bool> m_running{true};
    wl_callback *m_frameCallback = nullptr;
    AssRenderer *m_assRenderer = nullptr;
    std::function<void()> m_processCommands;

    int64_t m_freezeTimestampMs = 0;

    AppState m_state{};

    bool initWayland();
    bool initRenderer();
    bool initInput();
    void initBuffers();

    void mainLoop();
    void requestFrame();

    void onFrame(uint32_t time);
    void onPointerMotion(double x, double y);
    void onPointerButton(uint32_t button, uint32_t state, double x, double y);
    void onSurfaceConfigure(int width, int height);
};

