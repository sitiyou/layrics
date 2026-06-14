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
    m_pendingAssContents.push(content);
    LAY_DEBUG("ApplicationController: queued ASS content (%zu bytes)", content.size());
}

void ApplicationController::setPaused(bool paused) {
    std::lock_guard<std::mutex> lock(m_mutex);
    m_pendingPause.push(paused);
}

void ApplicationController::setStartTime(int64_t ms) {
    std::lock_guard<std::mutex> lock(m_mutex);
    m_pendingStartTime.push(ms);
}

int ApplicationController::getStartTime() {
    return m_app.getStartTime();
}

void ApplicationController::setHidden(bool hidden) {
    std::lock_guard<std::mutex> lock(m_mutex);
    m_pendingHide.push(hidden);
}

void ApplicationController::processPendingCommands() {
    std::lock_guard<std::mutex> lock(m_mutex);

    while (!m_pendingPause.empty()) {
        bool paused = m_pendingPause.front();
        m_pendingPause.pop();
        if (paused) {
            m_app.pause();
        } else {
            m_app.resume();
        }
    }

    while (!m_pendingStartTime.empty()) {
        int64_t ms = m_pendingStartTime.front();
        m_pendingStartTime.pop();
        m_app.setStartTime(ms);
    }

    while (!m_pendingAssContents.empty()) {
        std::string content = m_pendingAssContents.front();
        m_pendingAssContents.pop();
        m_app.loadAssContent(content);
    }

    while (!m_pendingHide.empty()) {
        bool hidden = m_pendingHide.front();
        m_pendingHide.pop();
        if (hidden) {
            m_app.hide();
        } else {
            m_app.show();
        }
    }
}
