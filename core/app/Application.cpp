#include "core/app/Application.hpp"
#include "core/renderer/AssRenderer.hpp"
#include "core/utils/Logger.hpp"
#include "core/wayland/LayerShellProtocol.hpp"
#include "wlr-layer-shell-unstable-v1-cpp.h"

#include <wayland-client.h>

#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <poll.h>
#include <stdexcept>
#include <unistd.h>

static const wl_callback_listener frameListener = {
    Application::frameDone};

Application::Application() {
    if (!initWayland()) {
        throw std::runtime_error("Failed to initialize Wayland");
    }
    if (!initInput()) {
        throw std::runtime_error("Failed to initialize input");
    }
    LAY_LOG("application initialized");
}

Application::~Application() {
    LAY_LOG("application shutting down");
    if (m_frameCallback) {
        wl_callback_destroy(m_frameCallback);
        m_frameCallback = nullptr;
    }
}

void Application::run() {
    LAY_LOG("starting application");
    m_running = true;

    if (m_state.startTimeMs == 0) {
        struct timespec ts;
        clock_gettime(CLOCK_MONOTONIC, &ts);
        m_state.startTimeMs = ts.tv_sec * 1000LL + ts.tv_nsec / 1000000LL;
    }

    while (m_running) {
        if (!m_surface.configured()) {
            LAY_LOG("layer surface re-initializing");
            m_frameCallback = nullptr;
            if (!initWayland()) {
                LAY_ERR("failed to re-initialize layer surface");
                m_running = false;
                break;
            }
            if (m_state.locked || m_state.hidden) {
                m_regionMgr.clear(m_waylandCtx.compositor, m_surface.surface());
            }
        }

        requestFrame();
        m_surface.commitFrame(m_buffer.buffer());

        LAY_LOG("entering main loop");
        mainLoop();

        if (!m_running) {
            LAY_DEBUG("clean up for stop");
            m_buffer.clear();
            if (m_surface.configured()) {
                m_regionMgr.clear(m_waylandCtx.compositor, m_surface.surface());
                m_surface.commitFrame(m_buffer.buffer());
                m_waylandCtx.dispatch();
            }
        }
    }
}

bool Application::initWayland() {
    wl_output *output = nullptr;
    if (!m_waylandCtx.outputs.empty()) {
        output = m_waylandCtx.outputs[0].output;
    }

    LayerSurfaceConfig surfCfg;
    surfCfg.anchor = ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP |
                     ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT |
                     ZWLR_LAYER_SURFACE_V1_ANCHOR_BOTTOM |
                     ZWLR_LAYER_SURFACE_V1_ANCHOR_RIGHT;
    surfCfg.exclusiveZone = -1;
    surfCfg.keyboardInteractivity =
        ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_NONE;

    if (!m_surface.initialize(m_waylandCtx, output,
                              ZWLR_LAYER_SHELL_V1_LAYER_OVERLAY, surfCfg)) {
        LAY_ERR("Failed to initialize layer surface");
        return false;
    }

    initBuffers();

    m_damageGrid.setSurfaceSize(m_surface.width(), m_surface.height());

    m_surface.setConfigureCallback([this](int width, int height) {
        onSurfaceConfigure(width, height);
    });

    return m_buffer.operator bool();
}

bool Application::initRenderer(const char *assFile) {
    auto renderer = std::make_unique<AssRenderer>(assFile);
    if (!renderer->initialize()) {
        LAY_ERR("Failed to initialize ASS renderer");
        return false;
    }

    m_assRenderer = renderer.get();
    m_renderMgr.setSize(m_surface.width(), m_surface.height());
    m_renderMgr.addRenderer(std::move(renderer));

    LAY_LOG("ASS renderer initialized");
    return true;
}

bool Application::initInput() {
    if (!m_inputMgr.initialize(m_waylandCtx.seat)) {
        LAY_ERR("Failed to initialize input manager");
        return false;
    }

    m_cursorMgr.initialize(m_waylandCtx.compositor, m_waylandCtx.shm);

    m_inputMgr.setMotionCallback([this](double x, double y) {
        onPointerMotion(x, y);
    });

    m_inputMgr.setButtonCallback([this](uint32_t button, uint32_t state,
                                         double x, double y) {
        onPointerButton(button, state, x, y);
    });

    m_inputMgr.setEnterCallback([this](uint32_t) {
        updateCursor();
    });

    LAY_LOG("input initialized");
    return true;
}

void Application::initBuffers() {
    if (!m_buffer.allocate(m_waylandCtx.shmFd, m_waylandCtx.shm,
                           m_surface.width(), m_surface.height())) {
        LAY_ERR("Failed to allocate SHM buffer");
    }
}

void Application::mainLoop() {
    while (m_running && m_surface.configured()) {
        while (!m_waylandCtx.prepareRead()) {
            if (m_waylandCtx.dispatchPending() < 0) {
                LAY_ERR("Wayland dispatch error");
                m_running = false;
                return;
            }
        }
        m_waylandCtx.flush();

        struct pollfd fd = {};
        fd.fd = m_waylandCtx.displayFd();
        fd.events = POLLIN;

        int ret = poll(&fd, 1, 16);
        if (ret < 0) {
            if (errno == EINTR) {
                m_waylandCtx.cancelRead();
                continue;
            }
            LAY_ERR("poll failed: %s", strerror(errno));
            m_waylandCtx.cancelRead();
            break;
        }

        if (fd.revents & POLLIN) {
            if (m_waylandCtx.readEvents() < 0) {
                LAY_ERR("Wayland read events error");
                m_running = false;
                break;
            }
            m_waylandCtx.dispatchPending();
        } else {
            m_waylandCtx.cancelRead();
        }
    }
}

void Application::frameDone(void *data, wl_callback * /*cb*/,
                            uint32_t /*time*/) {
    auto *self = static_cast<Application *>(data);
    self->m_frameCallback = nullptr;
    self->onFrame();
}

void Application::onFrame() {
    if (!m_surface.configured() || !m_buffer) {
        return;
    }

    if (m_preFrameCallback) {
        m_preFrameCallback();
    }

    auto dragState = m_dragMgr.state();
    m_state.dragOffsetX = dragState.offsetX;
    m_state.dragOffsetY = dragState.offsetY;
    m_renderMgr.setOffset(dragState.offsetX, dragState.offsetY);

    if (m_state.hidden) {
        if (!m_wasHidden) {
            hideDisplay();
        }
        m_wasHidden = true;
        m_wasPaused = m_state.paused;
        m_wasLocked = m_state.locked;
        requestFrame();
        m_surface.commitFrame(m_buffer.buffer(), true);
        m_frameRateLimiter.wait();
        return;
    }
    m_wasHidden = false;

    int64_t timestampMs;
    if (m_state.paused) {
        if (!m_wasPaused) {
            captureFreezeTimestamp();
        }
        timestampMs = m_freezeTimestampMs;
    } else {
        timestampMs = [this]() -> int64_t {
            struct timespec ts;
            clock_gettime(CLOCK_MONOTONIC, &ts);
            return ts.tv_sec * 1000LL + ts.tv_nsec / 1000000LL;
        }() - m_state.startTimeMs;
    }

    if (m_state.locked != m_wasLocked) {
        updateCursor();
        if (m_state.locked && m_surface.configured()) {
            applyLockedInputRegion();
        }
    }

    uint8_t *bufData = static_cast<uint8_t *>(m_buffer.data());
    RenderResult result = m_renderMgr.render(bufData, timestampMs);

    if (result.contentChanged) {
        m_damageGrid.beginFrame();
        for (const auto &rect : result.regions) {
            m_damageGrid.addRegion(rect.x, rect.y, rect.w, rect.h);
        }

        if (!m_state.locked) {
            m_regionMgr.update(m_waylandCtx.compositor, m_surface.surface(),
                               m_damageGrid.buildRegions(),
                               m_surface.width(), m_surface.height());
        }

        requestFrame();
        m_surface.commitFrame(m_buffer.buffer(), m_damageGrid.buildDamage());
    } else {
        if (!m_state.locked) {
            m_regionMgr.update(m_waylandCtx.compositor, m_surface.surface(),
                               result.regions,
                               m_surface.width(), m_surface.height());
        }

        requestFrame();
        m_surface.commitFrame(m_buffer.buffer(), false);
    }

    m_wasPaused = m_state.paused;
    m_wasLocked = m_state.locked;
    m_frameRateLimiter.wait();
}

void Application::onPointerMotion(double x, double y) {
    m_dragMgr.onMotion(x, y);
}

void Application::onPointerButton(uint32_t button, uint32_t state, double x,
                                  double y) {
    m_dragMgr.onButton(button, state, x, y);
    updateCursor();
}

void Application::loadAssContent(const std::string &content) {
    if (m_assRenderer) {
        m_assRenderer->loadContent(content);
        LAY_LOG("Loaded ASS content (reused renderer, %zu bytes)", content.size());
        return;
    }

    auto renderer = std::make_unique<AssRenderer>(content);
    if (!renderer->initialize()) {
        LAY_ERR("Failed to initialize ASS renderer (%zu bytes)", content.size());
        return;
    }

    m_renderMgr.setSize(m_surface.width(), m_surface.height());
    m_assRenderer = renderer.get();
    m_renderMgr.addRenderer(std::move(renderer));

    LAY_LOG("Loaded ASS content (new renderer, %zu bytes)", content.size());
}

void Application::setPreFrameCallback(std::function<void()> cb) {
    m_preFrameCallback = std::move(cb);
}

void Application::requestStop() {
    m_running = false;
}

void Application::setTargetFps(int fps) {
    m_state.targetFps = fps;
    m_frameRateLimiter.setTargetFps(fps);
    LAY_LOG("target FPS set to %d", fps);
}

void Application::requestFrame() {
    m_frameCallback = wl_surface_frame(m_surface.surface());
    wl_callback_add_listener(m_frameCallback, &frameListener, this);
}

void Application::captureFreezeTimestamp() {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    int64_t now = ts.tv_sec * 1000LL + ts.tv_nsec / 1000000LL;
    m_freezeTimestampMs = now - m_state.startTimeMs;
}

void Application::hideDisplay() {
    m_buffer.clear();
    m_regionMgr.clear(m_waylandCtx.compositor, m_surface.surface());
    m_renderMgr.reset();
}

void Application::applyLockedInputRegion() {
    m_regionMgr.clear(m_waylandCtx.compositor, m_surface.surface());
}

AppState Application::getStatus() {
    return m_state;
}

void Application::updateCursor() {
    if (!m_inputMgr.hasSurface()) {
        return;
    }

    wl_pointer *pointer = m_inputMgr.pointer();
    uint32_t serial = m_inputMgr.enterSerial();
    if (!pointer || !serial) {
        return;
    }

    if (m_state.locked) {
        m_cursorMgr.restoreCursor(pointer, serial);
    } else if (m_dragMgr.dragging()) {
        m_cursorMgr.setGrabbingCursor(pointer, serial);
    } else {
        m_cursorMgr.setGrabCursor(pointer, serial);
    }
}

void Application::onSurfaceConfigure(int width, int height) {
    LAY_LOG("surface resized: %dx%d", width, height);
    m_buffer.allocate(m_waylandCtx.shmFd, m_waylandCtx.shm, width, height);
    m_damageGrid.setSurfaceSize(width, height);
    m_renderMgr.setSize(width, height);
}
