#pragma once

#include <cstdint>
#include <functional>

struct wl_seat;
struct wl_pointer;
struct wl_surface;

class InputManager {
  public:
    struct PointerState {
        double x = 0;
        double y = 0;
        bool buttonLeft = false;
    };

    using MotionCallback = std::function<void(double x, double y)>;
    using ButtonCallback =
        std::function<void(uint32_t button, uint32_t state, double x, double y)>;
    using AxisCallback = std::function<void(double dx, double dy)>;
    using EnterCallback = std::function<void(uint32_t serial)>;
    using LeaveCallback = std::function<void()>;

    InputManager() = default;
    ~InputManager();

    InputManager(const InputManager &) = delete;
    InputManager &operator=(const InputManager &) = delete;

    bool initialize(wl_seat *seat);
    void release();

    void setMotionCallback(MotionCallback cb) { m_motionCb = std::move(cb); }
    void setButtonCallback(ButtonCallback cb) { m_buttonCb = std::move(cb); }
    void setAxisCallback(AxisCallback cb) { m_axisCb = std::move(cb); }
    void setEnterCallback(EnterCallback cb) { m_enterCb = std::move(cb); }
    void setLeaveCallback(LeaveCallback cb) { m_leaveCb = std::move(cb); }

    const PointerState &state() const { return m_state; }
    uint32_t enterSerial() const { return m_enterSerial; }
    bool hasSurface() const { return m_hasSurface; }
    wl_pointer *pointer() const { return m_pointer; }

  private:
    wl_pointer *m_pointer = nullptr;
    PointerState m_state;
    uint32_t m_enterSerial = 0;
    bool m_hasSurface = false;

    MotionCallback m_motionCb;
    ButtonCallback m_buttonCb;
    AxisCallback m_axisCb;
    EnterCallback m_enterCb;
    LeaveCallback m_leaveCb;

    static void handleEnter(void *data, wl_pointer *pointer, uint32_t serial,
                            wl_surface *surface, int32_t x, int32_t y);
    static void handleLeave(void *data, wl_pointer *pointer, uint32_t serial,
                            wl_surface *surface);
    static void handleMotion(void *data, wl_pointer *pointer, uint32_t time,
                             int32_t x, int32_t y);
    static void handleButton(void *data, wl_pointer *pointer, uint32_t serial,
                             uint32_t time, uint32_t button, uint32_t state);
    static void handleAxis(void *data, wl_pointer *pointer, uint32_t time,
                           uint32_t axis, int32_t value);
};
