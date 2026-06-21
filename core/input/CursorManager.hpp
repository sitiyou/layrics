#pragma once

#include <cstdint>

struct wl_compositor;
struct wl_cursor_theme;
struct wl_pointer;
struct wl_shm;
struct wl_surface;

class CursorManager {
  public:
    CursorManager() = default;
    ~CursorManager();

    CursorManager(const CursorManager &) = delete;
    CursorManager &operator=(const CursorManager &) = delete;

    bool initialize(wl_compositor *compositor, wl_shm *shm);
    void release();

    void setGrabCursor(wl_pointer *pointer, uint32_t serial);
    void setGrabbingCursor(wl_pointer *pointer, uint32_t serial);
    void restoreCursor(wl_pointer *pointer, uint32_t serial);

  private:
    wl_surface *m_cursorSurface = nullptr;
    wl_cursor_theme *m_cursorTheme = nullptr;

    void applyCursor(wl_pointer *pointer, uint32_t serial, const char *name);
};
