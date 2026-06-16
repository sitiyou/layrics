#pragma once

#include <cstdint>

class FrameRateLimiter {
  public:
    FrameRateLimiter();

    void setTargetFps(int fps);
    int targetFps() const { return m_targetFps; }
    double actualFps() const { return m_actualFps; }

    void wait();

  private:
    int m_targetFps = -1;
    double m_targetInterval = 0.0;
    double m_frameTime = 0.0;
    bool m_initialized = false;

    double m_actualFps = 0.0;
    int m_frameCount = 0;
    double m_logStart = 0.0;
};
