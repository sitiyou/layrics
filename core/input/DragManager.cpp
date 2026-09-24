#include "core/input/DragManager.hpp"
#include "core/utils/Logger.hpp"

#include <linux/input-event-codes.h>
#include <wayland-client.h>

#include <cstdlib>

void DragManager::onButton(uint32_t button, uint32_t wlState, double x,
                           double y) {
    if (button != BTN_LEFT) {
        return;
    }

    if (wlState == WL_POINTER_BUTTON_STATE_PRESSED) {
        m_dragging = true;
        m_dragPrevX = x;
        m_dragPrevY = y;
        LAY_DEBUG("drag start: %.1f %.1f", x, y);
    } else {
        m_dragging = false;
        LAY_DEBUG("drag end: offset=(%.1f, %.1f)", m_state.offsetX,
                  m_state.offsetY);
    }
}

void DragManager::onMotion(double x, double y) {
    if (!m_dragging) {
        return;
    }

    double deltaX = x - m_dragPrevX;
    double deltaY = y - m_dragPrevY;

    if (deltaX != 0.0 || deltaY != 0.0) {
        m_state.offsetX += deltaX;
        m_state.offsetY += deltaY;
    }

    m_dragPrevX = x;
    m_dragPrevY = y;
}

void DragManager::reset() {
    m_state.offsetX = 0.0;
    m_state.offsetY = 0.0;
    // If a drag is in flight, keep m_dragPrevX/Y at the cursor: the next
    // motion rebases the offset to zero instead of jumping by (x - 0).
}
