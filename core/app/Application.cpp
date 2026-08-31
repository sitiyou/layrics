#include "core/app/Application.hpp"
#include "core/renderer/AssRenderer.hpp"
#include "core/utils/Logger.hpp"
#include "core/wayland/LayerShellProtocol.hpp"
#include "wlr-layer-shell-unstable-v1-cpp.h"

#include <wayland-client.h>

#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include <linux/input-event-codes.h>
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

        mainLoop();

        if (!m_running) {
            LAY_DEBUG("clean up for stop");
            if (m_surface.configured()) {
                m_regionMgr.clear(m_waylandCtx.compositor, m_surface.surface());
                m_surface.commit();
                // Non-blocking: the compositor replies nothing after this
                // commit.
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

    if (!initVulkan()) {
        LAY_ERR("Failed to initialize Vulkan");
        return false;
    }

    m_damageGrid.setSurfaceSize(m_surface.width(), m_surface.height());

    m_surface.setConfigureCallback(
        [this](int width, int height) { onSurfaceConfigure(width, height); });

    return true;
}

bool Application::initVulkan() {
    return m_vk.initialize(m_waylandCtx.display, m_surface.surface(),
                           m_surface.width(), m_surface.height());
}

bool Application::initRenderer() {
    auto renderer = std::make_unique<AssRenderer>("");
    if (!renderer->initialize(m_vk)) {
        LAY_ERR("Failed to initialize ASS renderer");
        return false;
    }

    m_assRenderer = renderer.get();
    m_renderMgr.setSize(m_vk.width(), m_vk.height());
    m_renderMgr.addRenderer(std::move(renderer));

    if (!m_uiMgr.initialize(m_vk)) {
        LAY_ERR("Failed to initialize UI manager");
        return false;
    }
    m_uiMgr.setActionCallback(
        [this](const std::string &action) { onUiAction(action); });

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

    m_inputMgr.setLeaveCallback([this]() {
        m_uiMgr.requestClose(); // pointer left the input region
        setKeyboardInteractive(false);
    });

    m_keyboardMgr.initialize(m_waylandCtx.keyboard);
    m_keyboardMgr.setKeyCallback(
        [this](uint32_t key, uint32_t state, uint32_t mods) {
            onKey(key, state, mods);
        });

    LAY_LOG("input initialized");
    return true;
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
    // Fire first-time transition side effects here, not on frame timing.
    bool prevPaused = m_state.paused;
    bool prevHidden = m_state.hidden;
    bool prevLocked = m_state.locked;

    if (m_processCommands) {
        m_processCommands();
    }

    if (m_state.hidden && !prevHidden) {
        // Entering hidden: close the menu (no frame may follow), clear the
        // display, then stop the frame chain.
        m_uiMgr.closeNow();
        hideDisplay();
        setKeyboardInteractive(false);
    }
    if (!m_state.hidden && prevHidden && m_state.paused) {
        // Unhiding while paused: re-present the frozen frame once.
        produceFrame(m_freezeTimestampMs);
    }
    if (m_state.paused && !prevPaused) {
        m_freezeTimestampMs = nowMs() - m_state.startTimeMs;
    }
    if (m_state.locked != prevLocked) {
        if (m_state.locked) {
            m_uiMgr.closeNow();
        }
        updateCursor();
        if (m_state.locked && m_surface.configured()) {
            applyLockedInputRegion();
            setKeyboardInteractive(false);
        }
    }

    // Swapchain recreation on layer configure (safe here, outside dispatch).
    if (m_vk.dirty() && m_surface.configured()) {
        m_vk.resize(m_surface.width(), m_surface.height());
        m_renderMgr.setSize(m_vk.width(), m_vk.height());
    }

    // Restart the frame chain when needed (unhide, unpause, drag, menu) with
    // no frame in flight.
    bool needsFrame = !m_frameCallback && m_vk.ready() && !m_state.hidden &&
                      (!m_state.paused || m_dragMgr.dragging() ||
                       m_uiMgr.isActive());
    if (needsFrame) {
        int64_t ts = m_state.paused ? m_freezeTimestampMs
                                    : nowMs() - m_state.startTimeMs;
        produceFrame(ts);
    }
}

void Application::frameDone(void *data, wl_callback * /*cb*/, uint32_t time) {
    auto *self = static_cast<Application *>(data);
    self->m_frameCallback = nullptr;
    self->onFrame(time);
}

void Application::onFrame(uint32_t time) {
    if (!m_surface.configured() || !m_vk.ready()) {
        return;
    }

    auto dragState = m_dragMgr.state();
    m_state.dragOffsetX = dragState.offsetX;
    m_state.dragOffsetY = dragState.offsetY;
    m_renderMgr.setOffset(dragState.offsetX, dragState.offsetY);

    // Hidden/paused: frozen frame stays unless dragging or the menu is open.
    // Returning without requestFrame() stops the frame chain.
    if (m_state.hidden ||
        (m_state.paused && !m_dragMgr.dragging() && !m_uiMgr.isActive())) {
        return;
    }

    int64_t timestampMs =
        m_state.paused ? m_freezeTimestampMs
                       : static_cast<int64_t>(time) - m_state.startTimeMs;

    produceFrame(timestampMs);
}

void Application::produceFrame(int64_t timestampMs) {
    m_renderMgr.prepare(timestampMs);
    // Menu state (open/close) is updated here, so this must run before the
    // early-return checks below.
    m_uiMgr.newFrame(m_state);

    // Switch between the default cursor (menu open) and the hover cursor.
    if (m_uiMenuWasOpen != m_uiMgr.menuOpen()) {
        m_uiMenuWasOpen = m_uiMgr.menuOpen();
        updateCursor();
    }

    // Nothing changed: stop the frame chain (static lyrics cost ~0 GFX).
    // needsFrame restarts it when libass or the menu reports new content.
    if (!m_renderMgr.contentChanged() && !m_dragMgr.dragging() &&
        !m_uiMgr.isActive() && m_renderMgr.everRendered()) {
        return;
    }

    // wl_surface_frame must precede the present commit (WSI attaches inside
    // vkQueuePresentKHR).
    requestFrame();

    if (!m_vk.beginFrame()) {
        // Swapchain out of date; drop the callback so processState can
        // recreate the swapchain and restart the chain.
        if (m_frameCallback) {
            wl_callback_destroy(m_frameCallback);
            m_frameCallback = nullptr;
        }
        return;
    }

    m_renderMgr.recordUploads(m_vk.commandBuffer());
    m_vk.beginRenderPass();
    m_renderMgr.recordDraws(m_vk.commandBuffer());
    // Menu is drawn in surface coordinates (no drag offset), so it stays put
    // while the subtitles are dragged.
    m_uiMgr.render(m_vk.commandBuffer());

    // Damage grid (current+previous cells) so moved-away content is
    // re-composited too.
    m_damageGrid.beginFrame();
    for (const auto &rect : m_renderMgr.regions()) {
        m_damageGrid.addRegion(rect.x, rect.y, rect.w, rect.h);
    }
    if (m_uiMgr.menuOpen()) {
        m_damageGrid.addRegion(m_uiMgr.menuRect().x, m_uiMgr.menuRect().y,
                               m_uiMgr.menuRect().w, m_uiMgr.menuRect().h);
    }
    updateInputRegion();
    m_vk.endFrame(m_damageGrid.buildDamage());

    if (m_vk.dirty() && m_frameCallback) {
        // Present failed: no commit happened, so the frame callback never
        // fires; drop it and let processState restart after resize.
        wl_callback_destroy(m_frameCallback);
        m_frameCallback = nullptr;
    }

    m_frameRateLimiter.wait();
}

void Application::updateInputRegion() {
    if (m_state.locked || !m_surface.configured()) {
        return;
    }

    std::vector<RenderRect> regions;
    if (m_renderMgr.contentChanged()) {
        // Grid cells were populated in produceFrame (before the present).
        regions = m_damageGrid.buildRegions();
    } else {
        regions = m_renderMgr.regions();
    }
    // The menu must stay interactive: merge its rect into the input region.
    if (m_uiMgr.menuOpen()) {
        regions.push_back(m_uiMgr.menuRect());
    }
    m_regionMgr.update(m_waylandCtx.compositor, m_surface.surface(), regions,
                       m_surface.width(), m_surface.height());
}

void Application::onPointerMotion(double x, double y) {
    m_uiMgr.onPointerMotion(x, y);
    m_dragMgr.onMotion(x, y);
}

void Application::onPointerButton(uint32_t button, uint32_t state, double x,
                                  double y) {
    const bool pressed = (state == WL_POINTER_BUTTON_STATE_PRESSED);
    if (m_uiMgr.menuOpen()) {
        // The menu owns the pointer: item clicks and outside-clicks are fed
        // to imgui (outside clicks close the popup); never start a drag here.
        m_uiMgr.onPointerButton(static_cast<int>(button), pressed);
        updateCursor();
        return;
    }
    if (button == BTN_RIGHT && pressed && !m_dragMgr.dragging()) {
        // Open the cached menu instantly; ask Python to rebuild the content
        // with fresh state, which replaces the items on the next frame.
        m_uiMgr.openAt(x, y);
        if (m_uiEventSink) {
            m_uiEventSink("menu_requested");
        }
        updateCursor();
        return;
    }
    m_dragMgr.onButton(button, state, x, y);
    updateCursor();
}

void Application::onKey(uint32_t key, uint32_t state, uint32_t mods) {
    LAY_LOG("key: keycode=%u state=%s mods=0x%x", key,
            state == WL_KEYBOARD_KEY_STATE_PRESSED ? "pressed" : "released",
            mods);
    // ESC is consumed by the open menu (never forwarded to Python).
    if (m_uiMgr.menuOpen() && key == KEY_ESC &&
        state == WL_KEYBOARD_KEY_STATE_PRESSED) {
        m_uiMgr.requestClose();
        return;
    }
    if (m_keyEventSink) {
        m_keyEventSink(KeyEvent{key, state, mods});
    }
}

void Application::setKeyboardInteractive(bool on) {
    if (m_keyboardInteractive == on) {
        return;
    }
    m_keyboardInteractive = on;
    // ON_DEMAND keeps pointer focus region-bound: EXCLUSIVE forces full-screen
    // focus in Hyprland, bypassing the input region.
    m_surface.setKeyboardInteractivity(
        on ? ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_ON_DEMAND
           : ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_NONE);
    LAY_DEBUG("keyboard interactivity -> %s", on ? "ON_DEMAND" : "NONE");
}

void Application::loadAssContent(const std::string &content) {
    m_assRenderer->loadContent(content);
    LAY_LOG("Loaded ASS content (%zu bytes)", content.size());
}

void Application::setUiMenuItems(std::vector<UiMenuItem> items) {
    m_uiMgr.setMenuItems(std::move(items));
    LAY_DEBUG("UI menu items updated");
}

void Application::onUiAction(const std::string &action) {
    if (action == "reset_drag") {
        resetDrag();
        return;
    }
    if (m_uiEventSink) {
        m_uiEventSink(action);
    }
}

void Application::resetDrag() {
    m_dragMgr.reset();
    m_renderMgr.setOffset(0.0, 0.0);
    LAY_DEBUG("drag offset reset");
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
    m_regionMgr.clear(m_waylandCtx.compositor, m_surface.surface());
    m_renderMgr.reset();
    // Present one fully transparent frame so the overlay clears; if the
    // swapchain is not ready, drop the callback (chain restarts on unhide).
    requestFrame();
    if (m_vk.ready()) {
        m_vk.presentTransparent();
    } else if (m_frameCallback) {
        wl_callback_destroy(m_frameCallback);
        m_frameCallback = nullptr;
    }
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
        m_cursorMgr.restoreCursor(pointer, serial); // locked: hidden cursor
    } else if (m_uiMgr.menuOpen()) {
        // Menu open: show the default arrow instead of the hover hand.
        m_cursorMgr.setDefaultCursor(pointer, serial);
    } else if (m_dragMgr.dragging()) {
        m_cursorMgr.setGrabbingCursor(pointer, serial);
    } else {
        m_cursorMgr.setGrabCursor(pointer, serial);
    }
}

void Application::onSurfaceConfigure(int width, int height) {
    LAY_LOG("surface resized: %dx%d", width, height);
    m_damageGrid.setSurfaceSize(width, height);
    m_vk.markDirty();
}
