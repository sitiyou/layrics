#include "core/renderer/Transition.hpp"

#include <algorithm>

namespace {

struct EffectName {
    TransitionEffect effect;
    const char *name;
};

constexpr EffectName kEffectNames[] = {
    {TransitionEffect::None, "none"},       {TransitionEffect::Fade, "fade"},
    {TransitionEffect::Rise, "rise"},       {TransitionEffect::Zoom, "zoom"},
    {TransitionEffect::Cascade, "cascade"}, {TransitionEffect::Wave, "wave"},
    {TransitionEffect::Scatter, "scatter"}, {TransitionEffect::Flip, "flip"},
    {TransitionEffect::Wipe, "wipe"},       {TransitionEffect::BlurIn, "blur"},
    {TransitionEffect::Flash, "flash"},
};

} // namespace

const char *Transition::nameOf(TransitionEffect effect) {
    for (const auto &entry : kEffectNames) {
        if (entry.effect == effect) {
            return entry.name;
        }
    }
    return "none";
}

bool Transition::fromName(const std::string &name, TransitionEffect &out) {
    for (const auto &entry : kEffectNames) {
        if (name == entry.name) {
            out = entry.effect;
            return true;
        }
    }
    return false;
}

void Transition::configure(TransitionEffect effect, int durationMs,
                           int amplitude) {
    m_effect = effect;
    m_durationMs = std::max(durationMs, 0);
    m_amplitude = std::max(amplitude, 0);
    if (m_effect == TransitionEffect::None) {
        m_phase = m_target;
    }
}

void Transition::start(bool showing, int64_t nowMs) {
    m_target = showing ? 1.0f : 0.0f;
    // Rebase the clock so an animation started after an idle period does not
    // consume a huge dt.
    m_lastMs = nowMs;
    if (m_effect == TransitionEffect::None || m_durationMs <= 0) {
        m_phase = m_target;
    }
}

void Transition::reveal(int64_t nowMs) {
    if (m_effect == TransitionEffect::None || m_durationMs <= 0) {
        m_phase = 1.0f;
        m_target = 1.0f;
        return;
    }
    m_phase = 0.0f;
    m_target = 1.0f;
    m_lastMs = nowMs;
}

void Transition::update(int64_t nowMs) {
    if (!isActive()) {
        m_lastMs = nowMs;
        return;
    }
    int64_t dt = nowMs - m_lastMs;
    m_lastMs = nowMs;
    if (dt <= 0) {
        return;
    }
    // Only the target changes on interruption, so reversing mid-flight keeps
    // the current phase and never snaps.
    float step = static_cast<float>(dt) / static_cast<float>(m_durationMs);
    m_phase = (m_target > m_phase) ? std::min(m_target, m_phase + step)
                                   : std::max(m_target, m_phase - step);
}
