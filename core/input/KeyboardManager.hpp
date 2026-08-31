#pragma once

#include <cstdint>
#include <functional>

struct wl_array;
struct wl_keyboard;
struct wl_surface;

class KeyboardManager {
  public:
    using KeyCallback = std::function<void(uint32_t key, uint32_t state,
                                           uint32_t mods)>;
    using FocusCallback = std::function<void(bool focused)>;

    KeyboardManager() = default;
    ~KeyboardManager();

    KeyboardManager(const KeyboardManager &) = delete;
    KeyboardManager &operator=(const KeyboardManager &) = delete;

    bool initialize(wl_keyboard *keyboard);
    void shutdown();

    void setKeyCallback(KeyCallback cb) { m_keyCb = std::move(cb); }
    void setFocusCallback(FocusCallback cb) { m_focusCb = std::move(cb); }

    bool hasFocus() const { return m_hasFocus; }

  private:
    wl_keyboard *m_keyboard = nullptr;
    bool m_hasFocus = false;
    uint32_t m_mods = 0;  // currently depressed modifier mask

    KeyCallback m_keyCb;
    FocusCallback m_focusCb;

    static void handleKeymap(void *data, wl_keyboard *keyboard, uint32_t format,
                             int32_t fd, uint32_t size);
    static void handleEnter(void *data, wl_keyboard *keyboard, uint32_t serial,
                            wl_surface *surface, wl_array *keys);
    static void handleLeave(void *data, wl_keyboard *keyboard, uint32_t serial,
                            wl_surface *surface);
    static void handleKey(void *data, wl_keyboard *keyboard, uint32_t serial,
                          uint32_t time, uint32_t key, uint32_t state);
    static void handleModifiers(void *data, wl_keyboard *keyboard,
                                uint32_t serial, uint32_t modsDepressed,
                                uint32_t modsLatched, uint32_t modsLocked,
                                uint32_t group);
    static void handleRepeatInfo(void *data, wl_keyboard *keyboard,
                                 int32_t rate, int32_t delay);
};
