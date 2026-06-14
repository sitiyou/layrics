#pragma once

#include <cstdint>
#include <string>
#include <vector>

struct wl_display;
struct wl_registry;
struct wl_compositor;
struct wl_shm;
struct wl_seat;
struct wl_pointer;
struct wl_output;
struct wl_callback;
struct zwlr_layer_shell_v1;

struct WaylandContext {
    WaylandContext();
    ~WaylandContext();

    wl_display *display = nullptr;
    wl_registry *registry = nullptr;
    wl_compositor *compositor = nullptr;
    wl_shm *shm = nullptr;
    wl_seat *seat = nullptr;
    wl_pointer *pointer = nullptr;
    zwlr_layer_shell_v1 *layerShell = nullptr;

    struct OutputInfo {
        wl_output *output = nullptr;
        uint32_t id = 0;
        int x = 0;
        int y = 0;
        int width = 0;
        int height = 0;
        int scale = 1;
        std::string name;
        bool done = false;
    };
    std::vector<OutputInfo> outputs;

    int shmFd = -1;

    void roundtrip();
    void disconnect();
    int dispatch();
    void flush();
    int displayFd() const;

    bool prepareRead();
    void cancelRead();
    int readEvents();
    int dispatchPending();

  private:
    void connect();
};
