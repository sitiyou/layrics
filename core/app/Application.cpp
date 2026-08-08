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
#include <poll.h>
#include <stdexcept>
#include <unistd.h>

static const wl_callback_listener frameListener = {Application::frameDone};

// CLOCK_MONOTONIC milliseconds, same clock source as wl_callback timestamps.
static int64_t nowMs() {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<int64_t>(ts.tv_sec) * 1000 + ts.tv_nsec / 1000000;
}

Application::Application() {
    if (!initWayland()) {
        throw std::runtime_error("Failed to initialize Wayland");
    }
    if (!initInput()) {
        throw std::runtime_error("Failed to initialize input");
    }
    if (!initRenderer()) {
        throw std::runtime_error("Failed to initialize ASS renderer");
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
                // Non-blocking: the compositor replies nothing after this commit.
                m_waylandCtx.flush();
                m_waylandCtx.dispatchPending();
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

    m_surface.setConfigureCallback(
        [this](int width, int height) { onSurfaceConfigure(width, height); });

    return m_buffer.operator bool();
}

bool Application::initRenderer() {
    auto renderer = std::make_unique<AssRenderer>("");
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

    m_inputMgr.setMotionCallback(
        [this](double x, double y) { onPointerMotion(x, y); });

    m_inputMgr.setButtonCallback(
        [this](uint32_t button, uint32_t state, double x, double y) {
            onPointerButton(button, state, x, y);
        });

    m_inputMgr.setEnterCallback([this](uint32_t) {
        updateCursor();
        setKeyboardInteractive(true);
    });

    m_inputMgr.setLeaveCallback([this]() { setKeyboardInteractive(false); });

    m_keyboardMgr.initialize(m_waylandCtx.keyboard);
    m_keyboardMgr.setKeyCallback([this](uint32_t key, uint32_t state,
                                        uint32_t mods) {
        onKey(key, state, mods);
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
        processState();

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
            if (m_waylandCtx.dispatchPending() < 0) {
                LAY_ERR("Wayland dispatch error");
                m_running = false;
                break;
            }
        } else if (fd.revents) {
            // POLLERR/POLLHUP/POLLNVAL: connection lost
            LAY_ERR("Wayland connection lost (revents=0x%x)", fd.revents);
            m_waylandCtx.cancelRead();
            m_running = false;
            break;
        } else {
            m_waylandCtx.cancelRead();
        }
    }
}

void Application::processState() {
    // Snapshot pre-command state so first-time transitions can fire their
    // side-effects synchronously here (not tied to frame event timing).
    bool prevPaused = m_state.paused;
    bool prevHidden = m_state.hidden;
    bool prevLocked = m_state.locked;

    if (m_processCommands) {
        m_processCommands();
    }

    if (m_state.hidden && !prevHidden) {
        // Entering hidden: clear the display and commit once so the
        // compositor shows an empty surface; the frame chain then stops.
        hideDisplay();
        setKeyboardInteractive(false);
        m_surface.commitFrame(m_buffer.buffer(), true);
    }
    if (!m_state.hidden && prevHidden && m_state.paused) {
        // Unhiding while paused: render the frozen frame once so the overlay
        // shows it again, then the frame chain stops again.
        renderAndCommit(m_freezeTimestampMs);
    }
    if (m_state.paused && !prevPaused) {
        m_freezeTimestampMs = nowMs() - m_state.startTimeMs;
    }
    if (m_state.locked != prevLocked) {
        updateCursor();
        if (m_state.locked && m_surface.configured()) {
            applyLockedInputRegion();
            setKeyboardInteractive(false);
        }
    }

    // Restart the frame chain when rendering is needed again (unhide,
    // unpause, drag begins while paused) but no frame is in flight.
    // m_buffer stays valid because hideDisplay() only memsets it.
    bool needsFrame = !m_frameCallback && m_buffer && !m_state.hidden &&
                      (!m_state.paused || m_dragMgr.dragging());
    if (needsFrame) {
        requestFrame();
        m_surface.commitFrame(m_buffer.buffer(), true);
    }
}

void Application::frameDone(void *data, wl_callback * /*cb*/, uint32_t time) {
    auto *self = static_cast<Application *>(data);
    self->m_frameCallback = nullptr;
    self->onFrame(time);
}

void Application::onFrame(uint32_t time) {
    if (!m_surface.configured() || !m_buffer) {
        return;
    }

    auto dragState = m_dragMgr.state();
    m_state.dragOffsetX = dragState.offsetX;
    m_state.dragOffsetY = dragState.offsetY;
    m_renderMgr.setOffset(dragState.offsetX, dragState.offsetY);

    // No rendering while hidden (display already cleared by mainLoop); while
    // paused the frozen frame stays on screen unless a drag moves the offset.
    // Returning without requestFrame() stops the frame chain.
    if (m_state.hidden || (m_state.paused && !m_dragMgr.dragging())) {
        return;
    }

    int64_t timestampMs =
        m_state.paused
            ? m_freezeTimestampMs
            : static_cast<int64_t>(time) - m_state.startTimeMs;

    renderAndCommit(timestampMs);
}

void Application::renderAndCommit(int64_t timestampMs) {
    uint8_t *bufData = static_cast<uint8_t *>(m_buffer.data());
    RenderResult result = m_renderMgr.render(bufData, timestampMs);

    // Nothing changed: stop the frame chain (static lyrics cost ~0 GFX).
    if (!result.contentChanged && !m_dragMgr.dragging() &&
        m_renderMgr.everRendered()) {
        return;
    }

    if (result.contentChanged) {
        m_damageGrid.beginFrame();
        for (const auto &rect : result.regions) {
            m_damageGrid.addRegion(rect.x, rect.y, rect.w, rect.h);
        }

        if (!m_state.locked) {
            m_regionMgr.update(m_waylandCtx.compositor, m_surface.surface(),
                               m_damageGrid.buildRegions(), m_surface.width(),
                               m_surface.height());
        }

        requestFrame();
        m_surface.commitFrame(m_buffer.buffer(), m_damageGrid.buildDamage());
    } else {
        if (!m_state.locked) {
            m_regionMgr.update(m_waylandCtx.compositor, m_surface.surface(),
                               result.regions, m_surface.width(),
                               m_surface.height());
        }

        requestFrame();
        m_surface.commitFrame(m_buffer.buffer(), false);
    }

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

void Application::onKey(uint32_t key, uint32_t state, uint32_t mods) {
    LAY_LOG("key: keycode=%u state=%s mods=0x%x", key,
            state == WL_KEYBOARD_KEY_STATE_PRESSED ? "pressed" : "released",
            mods);
    if (m_keyEventSink) {
        m_keyEventSink(KeyEvent{key, state, mods});
    }
}

void Application::setKeyboardInteractive(bool on) {
    if (m_keyboardInteractive == on) {
        return;
    }
    m_keyboardInteractive = on;
    // ON_DEMAND instead of EXCLUSIVE: Hyprland forces full-screen pointer
    // focus onto EXCLUSIVE layer surfaces (m_exclusiveLSes fallback), which
    // would bypass the input region and never release the pointer. ON_DEMAND
    // keeps pointer focus region-bound while still granting keyboard focus on
    // hover (Hyprland allowKeyboardRefocus path) or click (sway).
    m_surface.setKeyboardInteractivity(
        on ? ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_ON_DEMAND
           : ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_NONE);
    LAY_DEBUG("keyboard interactivity -> %s", on ? "ON_DEMAND" : "NONE");
}

void Application::loadAssContent(const std::string &content) {
    m_assRenderer->loadContent(content);
    LAY_LOG("Loaded ASS content (%zu bytes)", content.size());
}

void Application::requestStop() { m_running = false; }

void Application::setTargetFps(int fps) {
    m_state.targetFps = fps;
    m_frameRateLimiter.setTargetFps(fps);
    LAY_LOG("target FPS set to %d", fps);
}

void Application::requestFrame() {
    m_frameCallback = wl_surface_frame(m_surface.surface());
    wl_callback_add_listener(m_frameCallback, &frameListener, this);
}

void Application::hideDisplay() {
    m_buffer.clear();
    m_regionMgr.clear(m_waylandCtx.compositor, m_surface.surface());
    m_renderMgr.reset();
}

void Application::applyLockedInputRegion() {
    m_regionMgr.clear(m_waylandCtx.compositor, m_surface.surface());
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
