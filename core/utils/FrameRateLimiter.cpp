#include "core/utils/FrameRateLimiter.hpp"
#include "core/utils/Logger.hpp"

#include <cmath>
#include <ctime>
#include <unistd.h>

static const double LOG_INTERVAL = 3.0;

static double nowSec() {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<double>(ts.tv_sec) +
           static_cast<double>(ts.tv_nsec) / 1000000000.0;
}

FrameRateLimiter::FrameRateLimiter() : m_logStart(nowSec()) {}

void FrameRateLimiter::setTargetFps(int fps) {
    m_targetFps = fps;
    if (fps > 0) {
        m_targetInterval = 1.0 / static_cast<double>(fps);
    }
    m_initialized = false;
}

void FrameRateLimiter::wait() {
    double now = nowSec();

    if (m_targetFps <= 0) {
        m_frameCount = 0;
        m_logStart = now;
        return;
    }

    if (!m_initialized) {
        m_frameTime = now;
        m_frameCount = 0;
        m_initialized = true;
        return;
    }

    m_frameCount++;
    m_frameTime += m_targetInterval;

    double sleepSec = m_frameTime - now;
    if (sleepSec > 0.0) {
        usleep(static_cast<useconds_t>(sleepSec * 1000000.0));
    }

    double elapsed = now - m_logStart;
    if (elapsed >= LOG_INTERVAL) {
        m_actualFps = static_cast<double>(m_frameCount) / elapsed;
        LAY_DEBUG("FPS: %.1f (target: %d)", m_actualFps, m_targetFps);
        m_frameCount = 0;
        m_logStart = now;
    }
}
