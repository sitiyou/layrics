#pragma once

#include <atomic>
#include <cstdint>
#include <deque>
#include <mutex>
#include <string>
#include <thread>

#include "core/app/Application.hpp"

struct PendingUpdate {
    bool paused = false;
    bool hidden = false;
    bool locked = false;
    int64_t startTimeMs = 0;
    int targetFps = -1;
    uint8_t mask = 0;

    enum Mask : uint8_t {
        PAUSED = 1 << 0,
        HIDDEN = 1 << 1,
        LOCKED = 1 << 2,
        START_TIME = 1 << 3,
        TARGET_FPS = 1 << 4,
    };
};

class ApplicationController {
  public:
    ApplicationController() = default;
    ~ApplicationController();

    ApplicationController(const ApplicationController &) = delete;
    ApplicationController &operator=(const ApplicationController &) = delete;

    void start();
    void stop();
    void join();

    void setAssInput(const std::string &path);
    void setStatus(const PendingUpdate &update);
    const AppState &state() const { return m_app.state(); }

    // Keyboard events captured on the render thread, drained from Python.
    void pushKeyEvent(const KeyEvent &event);
    std::vector<KeyEvent> pollKeyEvents();

  private:
    void processPendingCommands();

    Application m_app;
    std::thread m_thread;

    std::mutex m_mutex;
    PendingUpdate m_pending;
    std::string m_pendingAssContent;

    std::deque<KeyEvent> m_keyEvents;
    static constexpr size_t kMaxKeyEvents = 128;
};
