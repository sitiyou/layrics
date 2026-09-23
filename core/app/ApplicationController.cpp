#include "core/app/ApplicationController.hpp"
#include "core/utils/Logger.hpp"

ApplicationController::~ApplicationController() {
    stop();
    if (m_thread.joinable()) {
        m_thread.detach();
    }
}

void ApplicationController::start() {
    if (m_thread.joinable()) {
        m_thread.join();
    }

    m_app.m_processCommands = [this]() { processPendingCommands(); };
    m_app.m_keyEventSink = [this](const KeyEvent &event) {
        pushKeyEvent(event);
    };
    m_app.m_uiEventSink = [this](const std::string &event) {
        pushUiEvent(event);
    };

    m_thread = std::thread([this]() {
        LAY_LOG("ApplicationController: thread started");
        m_app.run();
        LAY_LOG("ApplicationController: thread exited");
    });
}

void ApplicationController::stop() {
    LAY_LOG("ApplicationController: clear and stop");
    m_app.requestStop();
}

void ApplicationController::join() {
    if (m_thread.joinable()) {
        m_thread.join();
    }
}

void ApplicationController::setAssInput(const std::string &content) {
    std::lock_guard<std::mutex> lock(m_mutex);
    m_pendingAssContent = content;
    LAY_DEBUG("ApplicationController: pending ASS content (%zu bytes)",
              content.size());
}

void ApplicationController::setUiMenu(std::vector<UiMenuItem> items) {
    std::lock_guard<std::mutex> lock(m_mutex);
    m_pendingUiMenu = std::move(items);
    m_hasPendingUiMenu = true;
}

void ApplicationController::openUiMenu(double x, double y) {
    std::lock_guard<std::mutex> lock(m_mutex);
    m_pendingMenuX = x;
    m_pendingMenuY = y;
    m_hasPendingOpenMenu = true;
}

void ApplicationController::setStatus(const PendingUpdate &update) {
    std::lock_guard<std::mutex> lock(m_mutex);
    if (update.mask & PendingUpdate::PAUSED)
        m_pending.paused = update.paused;
    if (update.mask & PendingUpdate::HIDDEN)
        m_pending.hidden = update.hidden;
    if (update.mask & PendingUpdate::LOCKED)
        m_pending.locked = update.locked;
    if (update.mask & PendingUpdate::START_TIME)
        m_pending.startTimeMs = update.startTimeMs;
    if (update.mask & PendingUpdate::TARGET_FPS)
        m_pending.targetFps = update.targetFps;
    if (update.mask & PendingUpdate::TRANSITION) {
        m_pending.transitionEffect = update.transitionEffect;
        m_pending.transitionDurationMs = update.transitionDurationMs;
        m_pending.transitionAmplitude = update.transitionAmplitude;
    }
    m_pending.mask |= update.mask;
}

void ApplicationController::setTransition(TransitionEffect effect,
                                         int durationMs, int amplitude) {
    PendingUpdate update;
    update.transitionEffect = effect;
    update.transitionDurationMs = durationMs;
    update.transitionAmplitude = amplitude;
    update.mask = PendingUpdate::TRANSITION;
    setStatus(update);
}

void ApplicationController::processPendingCommands() {
    PendingUpdate pending;
    std::string assContent;
    std::vector<UiMenuItem> uiMenu;
    bool hasUiMenu = false;
    double menuX = 0.0;
    double menuY = 0.0;
    bool hasOpenMenu = false;
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        pending = m_pending;
        m_pending = {};
        assContent = std::move(m_pendingAssContent);
        hasUiMenu = m_hasPendingUiMenu;
        m_hasPendingUiMenu = false;
        uiMenu = std::move(m_pendingUiMenu);
        hasOpenMenu = m_hasPendingOpenMenu;
        m_hasPendingOpenMenu = false;
        menuX = m_pendingMenuX;
        menuY = m_pendingMenuY;
    }

    if (pending.mask & PendingUpdate::PAUSED)
        m_app.setPaused(pending.paused);
    if (pending.mask & PendingUpdate::HIDDEN)
        m_app.setHidden(pending.hidden);
    if (pending.mask & PendingUpdate::LOCKED)
        m_app.setLocked(pending.locked);
    if (pending.mask & PendingUpdate::START_TIME)
        m_app.setStartTime(pending.startTimeMs);
    if (pending.mask & PendingUpdate::TARGET_FPS)
        m_app.setTargetFps(pending.targetFps);
    if (pending.mask & PendingUpdate::TRANSITION)
        m_app.setTransitionConfig(pending.transitionEffect,
                                  pending.transitionDurationMs,
                                  pending.transitionAmplitude);
    if (!assContent.empty())
        m_app.loadAssContent(std::move(assContent));
    if (hasUiMenu)
        m_app.setUiMenuItems(std::move(uiMenu));
    if (hasOpenMenu)
        m_app.openUiMenu(menuX, menuY);
}

void ApplicationController::pushKeyEvent(const KeyEvent &event) {
    std::lock_guard<std::mutex> lock(m_mutex);
    if (m_keyEvents.size() >= kMaxKeyEvents) {
        m_keyEvents.pop_front();
    }
    m_keyEvents.push_back(event);
}

std::vector<KeyEvent> ApplicationController::pollKeyEvents() {
    std::lock_guard<std::mutex> lock(m_mutex);
    std::vector<KeyEvent> events;
    events.reserve(m_keyEvents.size());
    while (!m_keyEvents.empty()) {
        events.push_back(m_keyEvents.front());
        m_keyEvents.pop_front();
    }
    return events;
}

void ApplicationController::pushUiEvent(const std::string &event) {
    std::lock_guard<std::mutex> lock(m_mutex);
    if (m_uiEvents.size() >= kMaxUiEvents) {
        m_uiEvents.pop_front();
    }
    m_uiEvents.push_back(event);
}

std::vector<std::string> ApplicationController::pollUiEvents() {
    std::lock_guard<std::mutex> lock(m_mutex);
    std::vector<std::string> events;
    events.reserve(m_uiEvents.size());
    while (!m_uiEvents.empty()) {
        events.push_back(m_uiEvents.front());
        m_uiEvents.pop_front();
    }
    return events;
}
