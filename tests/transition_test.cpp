// Headless unit test for the show/hide transition clock: name<->effect map,
// phase progression, and mid-flight reversal.

#include <cstdio>
#include <cstring>

#include "core/renderer/Transition.hpp"

namespace {

int g_failures = 0;

void check(bool ok, const char *what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL: %s\n", what);
        g_failures++;
    }
}

void testNames() {
    TransitionEffect parsed = TransitionEffect::None;
    check(Transition::fromName("scatter", parsed) &&
              parsed == TransitionEffect::Scatter,
          "fromName(scatter)");
    check(Transition::fromName("blur", parsed) &&
              parsed == TransitionEffect::BlurIn,
          "fromName(blur)");
    check(!Transition::fromName("bogus", parsed), "fromName rejects unknown");
    check(std::strcmp(Transition::nameOf(TransitionEffect::Wipe), "wipe") == 0,
          "nameOf(wipe)");
}

void testNoneSnaps() {
    Transition t;
    t.configure(TransitionEffect::None, 200, 48);
    t.start(false, 1000);
    check(!t.isActive() && t.progress() == 0.0f, "none hides immediately");
    t.start(true, 1000);
    check(!t.isActive() && t.progress() == 1.0f, "none shows immediately");
}

void testZeroDurationSnaps() {
    Transition t;
    t.configure(TransitionEffect::Fade, 0, 48);
    t.start(false, 1000);
    check(!t.isActive() && t.progress() == 0.0f, "zero duration snaps");
}

void testProgress() {
    Transition t;
    t.configure(TransitionEffect::Fade, 200, 48);
    check(!t.isActive() && t.progress() == 1.0f, "starts shown");

    t.start(false, 0);
    check(t.isActive(), "hide animation is active");
    t.update(100);
    check(t.progress() > 0.4f && t.progress() < 0.6f,
          "halfway after half time");
    t.update(200);
    check(!t.isActive() && t.progress() == 0.0f, "settles hidden");

    t.start(true, 200);
    t.update(400);
    check(!t.isActive() && t.progress() == 1.0f, "settles shown");
}

void testReversal() {
    Transition t;
    t.configure(TransitionEffect::Rise, 200, 48);
    t.start(false, 0);
    t.update(100);
    float mid = t.progress();
    check(mid > 0.0f && mid < 1.0f, "midway value");

    // Interrupting must continue from the current phase, never snap.
    t.start(true, 100);
    check(t.progress() == mid, "reversal keeps phase");
    t.update(150);
    check(t.progress() > mid, "reversal moves back up");
}

void testReveal() {
    Transition t;
    t.configure(TransitionEffect::Fade, 200, 48);
    t.reveal(0);
    check(t.isActive() && t.progress() == 0.0f, "reveal restarts from hidden");
    t.update(100);
    check(t.progress() > 0.4f && t.progress() < 0.6f, "reveal animates in");
    t.update(200);
    check(!t.isActive() && t.progress() == 1.0f, "reveal settles shown");

    // reveal() must never leave the overlay stuck invisible when animations are
    // disabled: the glyphs have to be usable immediately.
    Transition off;
    off.configure(TransitionEffect::None, 200, 48);
    off.reveal(0);
    check(!off.isActive() && off.progress() == 1.0f, "none reveal stays shown");

    Transition instant;
    instant.configure(TransitionEffect::Fade, 0, 48);
    instant.reveal(0);
    check(!instant.isActive() && instant.progress() == 1.0f,
          "zero-duration reveal stays shown");
}

void testStaleClock() {
    Transition t;
    t.configure(TransitionEffect::Zoom, 200, 48);
    // A long idle gap before start() must not consume a huge dt.
    t.update(1000000);
    t.start(false, 1000000);
    t.update(1000100);
    check(t.progress() > 0.4f && t.progress() < 0.6f, "no dt jump after idle");
}

} // namespace

int main() {
    testNames();
    testNoneSnaps();
    testZeroDurationSnaps();
    testProgress();
    testReveal();
    testReversal();
    testStaleClock();
    if (g_failures == 0) {
        std::printf("PASS: transition state machine\n");
        return 0;
    }
    std::fprintf(stderr, "%d check(s) failed\n", g_failures);
    return 1;
}
