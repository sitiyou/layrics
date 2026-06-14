#pragma once

#include <cstdint>

class DragManager {
  public:
    struct DragState {
        double offsetX = 0.0;
        double offsetY = 0.0;
    };

    void onButton(uint32_t button, uint32_t wlState, double x, double y);
    void onMotion(double x, double y);

    const DragState &state() const { return m_state; }
    bool dragging() const { return m_dragging; }
    void reset();

  private:
    bool m_dragging = false;
    double m_dragPrevX = 0;
    double m_dragPrevY = 0;
    DragState m_state;
};
