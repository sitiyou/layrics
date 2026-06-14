#pragma once

#include <atomic>
#include <mutex>
#include <queue>
#include <string>
#include <thread>

#include "core/app/Application.hpp"

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
    void setPaused(bool paused);
    void setStartTime(int64_t ms);
    int getStartTime();
    void setHidden(bool hidden);

  private:
    void processPendingCommands();

    Application m_app;
    std::thread m_thread;

    std::mutex m_mutex;
    std::queue<std::string> m_pendingAssContents;
    std::queue<bool> m_pendingPause;
    std::queue<int64_t> m_pendingStartTime;
    std::queue<bool> m_pendingHide;
};
