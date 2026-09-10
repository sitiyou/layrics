#pragma once

#include <cstdint>
#include <string>

#include "core/types/Common.hpp"

// Overlay show/hide animation clock. Render-thread only.
// progress() is linear (0 = hidden, 1 = shown); each effect applies its own
// easing in subtitle.vert so they all share one clock.
class Transition {
  public:
    void configure(TransitionEffect effect, int durationMs, int amplitude);
    void start(bool showing, int64_t nowMs);

    // First-paint entrance: play from fully hidden without a preceding hide.
    void reveal(int64_t nowMs);

    // Advance toward the target; call once per main-loop iteration, before
    // the frame is produced.
    void update(int64_t nowMs);

    bool isActive() const { return m_phase != m_target; }
    TransitionEffect effect() const { return m_effect; }
    float progress() const { return m_phase; }
    float amplitude() const { return static_cast<float>(m_amplitude); }

    // Config-facing name tables (examples/config.toml, IPC).
    static const char *nameOf(TransitionEffect effect);
    static bool fromName(const std::string &name, TransitionEffect &out);

  private:
    TransitionEffect m_effect = TransitionEffect::None;
    int m_durationMs = 0;
    int m_amplitude = 0;
    float m_phase = 1.0f;
    float m_target = 1.0f;
    int64_t m_lastMs = 0;
};
