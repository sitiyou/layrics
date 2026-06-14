#include "core/input/InputManager.hpp"
#include "core/utils/Logger.hpp"

#include <linux/input-event-codes.h>
#include <wayland-client.h>

#include <cstdio>

namespace {

void noopFrame(void *, wl_pointer *) {}
void noopAxisSource(void *, wl_pointer *, uint32_t) {}
void noopAxisStop(void *, wl_pointer *, uint32_t, uint32_t) {}
void noopAxisDiscrete(void *, wl_pointer *, uint32_t, int32_t) {}
void noopAxisValue120(void *, wl_pointer *, uint32_t, int32_t) {}
void noopAxisRelativeDirection(void *, wl_pointer *, uint32_t, uint32_t) {}

} // namespace

InputManager::~InputManager() { release(); }

bool InputManager::initialize(wl_seat *seat) {
    if (!seat) {
        return false;
    }

    release();

    m_pointer = wl_seat_get_pointer(seat);
    if (!m_pointer) {
        return false;
    }

    static const wl_pointer_listener listener = {
        handleEnter,
        handleLeave,
        handleMotion,
        handleButton,
        handleAxis,
        noopFrame,
        noopAxisSource,
        noopAxisStop,
        noopAxisDiscrete,
        noopAxisValue120,
        noopAxisRelativeDirection,
    };

    wl_pointer_add_listener(m_pointer, &listener, this);
    LAY_DEBUG("input manager initialized");
    return true;
}

void InputManager::release() {
    if (m_pointer) {
        LAY_DEBUG("releasing wl_pointer");
        wl_pointer_release(m_pointer);
        m_pointer = nullptr;
    }
}

void InputManager::handleEnter(void *data, wl_pointer *, uint32_t /*serial*/,
                               wl_surface * /*surface*/, wl_fixed_t x,
                               wl_fixed_t y) {
    auto *self = static_cast<InputManager *>(data);
    self->m_state.x = wl_fixed_to_double(x);
    self->m_state.y = wl_fixed_to_double(y);
    LAY_DEBUG("pointer enter: %.1f %.1f", self->m_state.x, self->m_state.y);
}

void InputManager::handleLeave(void *data, wl_pointer *, uint32_t /*serial*/,
                               wl_surface * /*surface*/) {
    auto *self = static_cast<InputManager *>(data);
    self->m_state.buttonLeft = false;
    LAY_DEBUG("pointer leave");
}

void InputManager::handleMotion(void *data, wl_pointer *, uint32_t /*time*/,
                                wl_fixed_t x, wl_fixed_t y) {
    auto *self = static_cast<InputManager *>(data);
    double dx = wl_fixed_to_double(x);
    double dy = wl_fixed_to_double(y);
    self->m_state.x = dx;
    self->m_state.y = dy;
    if (self->m_motionCb) {
        self->m_motionCb(dx, dy);
    }
}

void InputManager::handleButton(void *data, wl_pointer *, uint32_t /*serial*/,
                                uint32_t /*time*/, uint32_t button,
                                uint32_t state) {
    auto *self = static_cast<InputManager *>(data);
    if (button == BTN_LEFT) {
        self->m_state.buttonLeft = (state == WL_POINTER_BUTTON_STATE_PRESSED);
    }
    if (self->m_buttonCb) {
        self->m_buttonCb(button, state, self->m_state.x, self->m_state.y);
    }
}

void InputManager::handleAxis(void *data, wl_pointer *, uint32_t /*time*/,
                              uint32_t axis, wl_fixed_t value) {
    auto *self = static_cast<InputManager *>(data);
    if (self->m_axisCb) {
        double dx = 0.0, dy = 0.0;
        double v = wl_fixed_to_double(value);
        if (axis == WL_POINTER_AXIS_VERTICAL_SCROLL) {
            dy = v;
        } else if (axis == WL_POINTER_AXIS_HORIZONTAL_SCROLL) {
            dx = v;
        }
        self->m_axisCb(dx, dy);
    }
}

