#include "core/input/KeyboardManager.hpp"
#include "core/utils/Logger.hpp"

#include <wayland-client.h>

#include <unistd.h>

KeyboardManager::~KeyboardManager() { release(); }

bool KeyboardManager::initialize(wl_keyboard *keyboard) {
    if (!keyboard) {
        return false;
    }

    release();

    m_keyboard = keyboard;

    static const wl_keyboard_listener listener = {
        handleKeymap,
        handleEnter,
        handleLeave,
        handleKey,
        handleModifiers,
        handleRepeatInfo,
    };

    wl_keyboard_add_listener(m_keyboard, &listener, this);
    LAY_DEBUG("keyboard manager initialized");
    return true;
}

void KeyboardManager::release() {
    if (m_keyboard) {
        LAY_DEBUG("releasing wl_keyboard");
        wl_keyboard_release(m_keyboard);
        m_keyboard = nullptr;
    }
    m_hasFocus = false;
}

void KeyboardManager::handleKeymap(void *data, wl_keyboard * /*keyboard*/,
                                   uint32_t format, int32_t fd,
                                   uint32_t /*size*/) {
    (void)data;
    LAY_DEBUG("keyboard keymap format=%u", format);
    // Keymap parsing (xkb) is out of scope for now; keys are forwarded as raw
    // evdev keycodes via handleKey.
    if (fd >= 0) {
        close(fd);
    }
}

void KeyboardManager::handleEnter(void *data, wl_keyboard * /*keyboard*/,
                                  uint32_t /*serial*/,
                                  wl_surface * /*surface*/,
                                  wl_array * /*keys*/) {
    auto *self = static_cast<KeyboardManager *>(data);
    self->m_hasFocus = true;
    LAY_DEBUG("keyboard focus entered");
    if (self->m_focusCb) {
        self->m_focusCb(true);
    }
}

void KeyboardManager::handleLeave(void *data, wl_keyboard * /*keyboard*/,
                                  uint32_t /*serial*/,
                                  wl_surface * /*surface*/) {
    auto *self = static_cast<KeyboardManager *>(data);
    self->m_hasFocus = false;
    LAY_DEBUG("keyboard focus left");
    if (self->m_focusCb) {
        self->m_focusCb(false);
    }
}

void KeyboardManager::handleKey(void *data, wl_keyboard * /*keyboard*/,
                                uint32_t /*serial*/, uint32_t /*time*/,
                                uint32_t key, uint32_t state) {
    auto *self = static_cast<KeyboardManager *>(data);
    LAY_DEBUG("key event: keycode=%u state=%s mods=0x%x", key,
              state == WL_KEYBOARD_KEY_STATE_PRESSED ? "pressed"
                                                      : "released",
              self->m_mods);
    if (self->m_keyCb) {
        self->m_keyCb(key, state, self->m_mods);
    }
}

void KeyboardManager::handleModifiers(void *data, wl_keyboard * /*keyboard*/,
                                      uint32_t /*serial*/,
                                      uint32_t modsDepressed,
                                      uint32_t /*modsLatched*/,
                                      uint32_t /*modsLocked*/,
                                      uint32_t /*group*/) {
    auto *self = static_cast<KeyboardManager *>(data);
    self->m_mods = modsDepressed;
    LAY_DEBUG("keyboard modifiers changed: mods=0x%x", modsDepressed);
}

void KeyboardManager::handleRepeatInfo(void *data, wl_keyboard * /*keyboard*/,
                                       int32_t /*rate*/,
                                       int32_t /*delay*/) {
    (void)data;
}
