#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>

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

class Application {
  public:
    Application();
    ~Application();

    Application(const Application &) = delete;
    Application &operator=(const Application &) = delete;

    void run();

    void loadAssContent(const std::string &content);
    void clearRenderer();
    void clearInputRegions();
    void setPreFrameCallback(std::function<void()> cb);
    void requestStop();
    void pause();
    void resume();
    void setStartTime(int64_t ms);
    void setTargetFps(int fps);
    void hide();
    void show();
    void lock();
    void unlock();
    void clear();
    int getStartTime() { return m_startTimeMs; };
    AppStatus getStatus();

    static void frameDone(void *data, wl_callback *cb, uint32_t time);

  private:
    WaylandContext m_waylandCtx;
    LayerSurface m_surface;
    ShmBuffer m_buffer;
    RenderManager m_renderMgr;
    FrameRateLimiter m_frameRateLimiter;
    InputManager m_inputMgr;
    DragManager m_dragMgr;
    RegionManager m_regionMgr;

    std::atomic<bool> m_running{true};
    int64_t m_startTimeMs = 0;
    wl_callback *m_frameCallback = nullptr;
    AssRenderer *m_assRenderer = nullptr;
    std::function<void()> m_preFrameCallback;

    bool m_paused = false;
    bool m_hidden = false;
    bool m_locked = false;
    int64_t m_freezeTimestampMs = 0;

    bool initWayland();
    bool initRenderer(const char *assFile);
    bool initInput();
    void initBuffers();

    void mainLoop();
    void requestFrame();

    void onFrame();
    void onPointerMotion(double x, double y);
    void onPointerButton(uint32_t button, uint32_t state, double x, double y);
};
