#include "core/input/CursorManager.hpp"
#include "core/utils/Logger.hpp"

#include <wayland-client.h>
#include <wayland-cursor.h>

#include <cstring>

CursorManager::~CursorManager() { release(); }

bool CursorManager::initialize(wl_compositor *compositor, wl_shm *shm) {
    if (!compositor || !shm) {
        return false;
    }

    m_cursorSurface = wl_compositor_create_surface(compositor);
    if (!m_cursorSurface) {
        LAY_ERR("failed to create cursor surface");
        return false;
    }

    m_cursorTheme = wl_cursor_theme_load(nullptr, 32, shm);
    if (!m_cursorTheme) {
        LAY_ERR("failed to load cursor theme");
        wl_surface_destroy(m_cursorSurface);
        m_cursorSurface = nullptr;
        return false;
    }

    LAY_LOG("cursor manager initialized");
    return true;
}

void CursorManager::release() {
    if (m_cursorTheme) {
        wl_cursor_theme_destroy(m_cursorTheme);
        m_cursorTheme = nullptr;
    }
    if (m_cursorSurface) {
        wl_surface_destroy(m_cursorSurface);
        m_cursorSurface = nullptr;
    }
}

void CursorManager::applyCursor(wl_pointer *pointer, uint32_t serial,
                                const char *name) {
    if (!pointer || !serial || !m_cursorSurface || !m_cursorTheme) {
        return;
    }

    wl_cursor *cursor = wl_cursor_theme_get_cursor(m_cursorTheme, name);
    if (!cursor) {
        LAY_DEBUG("cursor '%s' not found in theme", name);
        return;
    }

    wl_cursor_image *image = cursor->images[0];
    wl_buffer *buffer = wl_cursor_image_get_buffer(image);
    if (!buffer) {
        return;
    }

    wl_pointer_set_cursor(pointer, serial, m_cursorSurface, image->hotspot_x,
                          image->hotspot_y);
    wl_surface_attach(m_cursorSurface, buffer, 0, 0);
    wl_surface_damage_buffer(m_cursorSurface, 0, 0, image->width,
                             image->height);
    wl_surface_commit(m_cursorSurface);
}

void CursorManager::setGrabCursor(wl_pointer *pointer, uint32_t serial) {
    applyCursor(pointer, serial, "grab");
}

void CursorManager::setGrabbingCursor(wl_pointer *pointer, uint32_t serial) {
    applyCursor(pointer, serial, "grabbing");
}

void CursorManager::restoreCursor(wl_pointer *pointer, uint32_t serial) {
    if (!pointer || !serial || !m_cursorSurface) {
        return;
    }
    wl_pointer_set_cursor(pointer, serial, nullptr, 0, 0);
}
