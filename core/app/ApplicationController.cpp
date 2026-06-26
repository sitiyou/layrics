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

    m_app.setPreFrameCallback([this]() { processPendingCommands(); });

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
    LAY_DEBUG("ApplicationController: pending ASS content (%zu bytes)", content.size());
}

void ApplicationController::setStatus(const PendingUpdate &update) {
    std::lock_guard<std::mutex> lock(m_mutex);
    if (update.mask & PendingUpdate::PAUSED)     m_pending.paused     = update.paused;
    if (update.mask & PendingUpdate::HIDDEN)     m_pending.hidden     = update.hidden;
    if (update.mask & PendingUpdate::LOCKED)     m_pending.locked     = update.locked;
    if (update.mask & PendingUpdate::START_TIME) m_pending.startTimeMs = update.startTimeMs;
    if (update.mask & PendingUpdate::TARGET_FPS) m_pending.targetFps   = update.targetFps;
    m_pending.mask |= update.mask;
}

int ApplicationController::getStartTime() {
    return m_app.getStartTime();
}

AppState ApplicationController::getStatus() {
    return m_app.getStatus();
}

void ApplicationController::processPendingCommands() {
    PendingUpdate pending;
    std::string assContent;
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        pending = m_pending;
        m_pending = {};
        assContent = std::move(m_pendingAssContent);
    }

    if (pending.mask & PendingUpdate::PAUSED)     m_app.setPaused(pending.paused);
    if (pending.mask & PendingUpdate::HIDDEN)     m_app.setHidden(pending.hidden);
    if (pending.mask & PendingUpdate::LOCKED)     m_app.setLocked(pending.locked);
    if (pending.mask & PendingUpdate::START_TIME) m_app.setStartTime(pending.startTimeMs);
    if (pending.mask & PendingUpdate::TARGET_FPS) m_app.setTargetFps(pending.targetFps);
    if (!assContent.empty())                      m_app.loadAssContent(std::move(assContent));
}
