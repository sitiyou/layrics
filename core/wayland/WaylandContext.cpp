#include "core/wayland/WaylandContext.hpp"
#include "core/wayland/LayerShellProtocol.hpp"
#include "core/utils/Logger.hpp"

#include <wayland-client.h>

#include <cstdio>
#include <cstring>
#include <ctime>
#include <errno.h>
#include <fcntl.h>
#include <stdexcept>
#include <sys/mman.h>
#include <unistd.h>

static void randname(char *buf) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    long r = ts.tv_nsec;
    for (int i = 0; i < 6; ++i) {
        buf[i] = 'A' + (r & 15) + (r & 16) * 2;
        r >>= 5;
    }
}

static int anonymousShmOpen() {
    char name[] = "/layrics-XXXXXX";
    int retries = 100;

    do {
        randname(name + strlen(name) - 6);
        --retries;
        int fd = shm_open(name, O_RDWR | O_CREAT | O_EXCL, 0600);
        if (fd >= 0) {
            shm_unlink(name);
            return fd;
        }
    } while (retries > 0 && errno == EEXIST);

    return -1;
}

static void seatHandleCapabilities(void *data, wl_seat *seat, uint32_t caps) {
    auto *ctx = static_cast<WaylandContext *>(data);
    LAY_DEBUG("seat capabilities: 0x%x", caps);
    if (caps & WL_SEAT_CAPABILITY_POINTER) {
        if (!ctx->pointer) {
            ctx->pointer = wl_seat_get_pointer(seat);
            LAY_DEBUG("wl_pointer obtained");
        }
    } else {
        if (ctx->pointer) {
            wl_pointer_release(ctx->pointer);
            ctx->pointer = nullptr;
            LAY_DEBUG("wl_pointer released");
        }
    }
}

static void seatHandleName(void *data, wl_seat *seat, const char *name) {
    (void)data;
    (void)seat;
    (void)name;
}

static const wl_seat_listener seatListener = {
    seatHandleCapabilities,
    seatHandleName,
};

static void outputHandleGeometry(void *data, wl_output *wl_output, int32_t x,
                                 int32_t y, int32_t physical_width,
                                 int32_t physical_height, int32_t subpixel,
                                 const char *make, const char *model,
                                 int32_t transform) {
    (void)physical_width;
    (void)physical_height;
    (void)subpixel;
    (void)make;
    (void)model;
    (void)transform;
    auto *ctx = static_cast<WaylandContext *>(data);
    for (auto &info : ctx->outputs) {
        if (info.output == wl_output) {
            info.x = x;
            info.y = y;
            return;
        }
    }
}

static void outputHandleMode(void *data, wl_output *wl_output, uint32_t flags,
                             int32_t width, int32_t height, int32_t refresh) {
    (void)refresh;
    if (!(flags & WL_OUTPUT_MODE_CURRENT)) {
        return;
    }
    auto *ctx = static_cast<WaylandContext *>(data);
    for (auto &info : ctx->outputs) {
        if (info.output == wl_output) {
            info.width = width;
            info.height = height;
            return;
        }
    }
}

static void outputHandleDone(void *data, wl_output *wl_output) {
    auto *ctx = static_cast<WaylandContext *>(data);
    for (auto &info : ctx->outputs) {
        if (info.output == wl_output) {
            info.done = true;
            return;
        }
    }
}

static void outputHandleScale(void *data, wl_output *wl_output,
                              int32_t factor) {
    auto *ctx = static_cast<WaylandContext *>(data);
    for (auto &info : ctx->outputs) {
        if (info.output == wl_output) {
            info.scale = factor;
            return;
        }
    }
}

static void outputHandleName(void *data, wl_output *wl_output,
                             const char *name) {
    auto *ctx = static_cast<WaylandContext *>(data);
    for (auto &info : ctx->outputs) {
        if (info.output == wl_output) {
            info.name = name ? name : "";
            return;
        }
    }
}

static void outputHandleDescription(void *data, wl_output *wl_output,
                                    const char *description) {
    (void)description;
    auto *ctx = static_cast<WaylandContext *>(data);
    for (auto &info : ctx->outputs) {
        if (info.output == wl_output) {
            return;
        }
    }
}

static const wl_output_listener outputListener = {
    outputHandleGeometry, outputHandleMode, outputHandleDone,
    outputHandleScale,    outputHandleName, outputHandleDescription,
};

static void registryHandleGlobal(void *data, wl_registry *registry,
                                 uint32_t name, const char *interface,
                                 uint32_t version) {
    (void)version;
    auto *ctx = static_cast<WaylandContext *>(data);

    if (strcmp(interface, wl_compositor_interface.name) == 0) {
        ctx->compositor = static_cast<wl_compositor *>(
            wl_registry_bind(registry, name, &wl_compositor_interface, 4));
        LAY_DEBUG("bound compositor v4");
    } else if (strcmp(interface, wl_shm_interface.name) == 0) {
        ctx->shm = static_cast<wl_shm *>(
            wl_registry_bind(registry, name, &wl_shm_interface, 1));
        LAY_DEBUG("bound shm v1");
    } else if (strcmp(interface, wl_seat_interface.name) == 0) {
        ctx->seat = static_cast<wl_seat *>(
            wl_registry_bind(registry, name, &wl_seat_interface, 5));
        wl_seat_add_listener(ctx->seat, &seatListener, ctx);
        LAY_DEBUG("bound seat v5");
    } else if (strcmp(interface, zwlr_layer_shell_v1_interface.name) == 0) {
        uint32_t layerShellVersion = version;
        if (layerShellVersion > ZWLR_LAYER_SHELL_V1_DESTROY_SINCE_VERSION) {
            layerShellVersion = ZWLR_LAYER_SHELL_V1_DESTROY_SINCE_VERSION;
        }
        ctx->layerShell = static_cast<zwlr_layer_shell_v1 *>(wl_registry_bind(
            registry, name, &zwlr_layer_shell_v1_interface,
            layerShellVersion));
        LAY_DEBUG("bound layer_shell v%u", layerShellVersion);
    } else if (strcmp(interface, wl_output_interface.name) == 0) {
        ctx->outputs.emplace_back();
        auto &info = ctx->outputs.back();
        info.id = name;
        info.output = static_cast<wl_output *>(
            wl_registry_bind(registry, name, &wl_output_interface, 4));
        wl_output_add_listener(info.output, &outputListener, ctx);
        LAY_DEBUG("bound output id=%u v4", name);
    }
}

static void registryHandleGlobalRemove(void *data, wl_registry *registry,
                                       uint32_t name) {
    (void)registry;
    auto *ctx = static_cast<WaylandContext *>(data);

    for (auto it = ctx->outputs.begin(); it != ctx->outputs.end(); ++it) {
        if (it->id == name) {
            LAY_DEBUG("output removed: id=%u", name);
            if (it->output) {
                wl_output_release(it->output);
            }
            ctx->outputs.erase(it);
            return;
        }
    }
}

static const wl_registry_listener registryListener = {
    registryHandleGlobal,
    registryHandleGlobalRemove,
};

WaylandContext::WaylandContext() { connect(); }

void WaylandContext::connect() {
    LAY_DEBUG("connecting to Wayland");
    display = wl_display_connect(nullptr);
    if (!display) {
        LAY_ERR("Failed to connect to Wayland display");
        throw std::runtime_error("Failed to connect to Wayland display");
    }

    registry = wl_display_get_registry(display);
    if (!registry) {
        LAY_ERR("Failed to get Wayland registry");
        wl_display_disconnect(display);
        display = nullptr;
        throw std::runtime_error("Failed to get Wayland registry");
    }

    wl_registry_add_listener(registry, &registryListener, this);

    if (wl_display_roundtrip(display) < 0) {
        LAY_ERR("Roundtrip failed");
        disconnect();
        throw std::runtime_error("Roundtrip failed");
    }
    LAY_DEBUG("roundtrip done");

    if (!compositor || !shm || !layerShell) {
        LAY_ERR("Missing required Wayland protocols (compositor=%p "
                "shm=%p layer_shell=%p)",
                (void *)compositor, (void *)shm, (void *)layerShell);
        disconnect();
        throw std::runtime_error("Missing required Wayland protocols");
    }

    shmFd = anonymousShmOpen();
    if (shmFd < 0) {
        LAY_ERR("Failed to create anonymous SHM file");
        disconnect();
        throw std::runtime_error("Failed to create anonymous SHM file");
    }

    LAY_LOG("Wayland connected, %zu output(s) discovered", outputs.size());
}

void WaylandContext::roundtrip() {
    wl_display_roundtrip(display);
}

int WaylandContext::dispatch() {
    return wl_display_dispatch(display);
}

void WaylandContext::flush() {
    wl_display_flush(display);
}

int WaylandContext::displayFd() const {
    return wl_display_get_fd(display);
}

bool WaylandContext::prepareRead() {
    return wl_display_prepare_read(display) == 0;
}

void WaylandContext::cancelRead() {
    wl_display_cancel_read(display);
}

int WaylandContext::readEvents() {
    return wl_display_read_events(display);
}

int WaylandContext::dispatchPending() {
    return wl_display_dispatch_pending(display);
}

void WaylandContext::disconnect() {
    LAY_DEBUG("disconnecting");
    if (shmFd >= 0) {
        close(shmFd);
        shmFd = -1;
    }

    for (auto &info : outputs) {
        if (info.output) {
            wl_output_release(info.output);
        }
    }
    outputs.clear();

    if (pointer) {
        wl_pointer_destroy(pointer);
        pointer = nullptr;
    }
    if (seat) {
        wl_seat_destroy(seat);
        seat = nullptr;
    }
    if (layerShell) {
        if (zwlr_layer_shell_v1_get_version(layerShell) >=
            ZWLR_LAYER_SHELL_V1_DESTROY_SINCE_VERSION) {
            zwlr_layer_shell_v1_destroy(layerShell);
        } else {
            wl_proxy_destroy(
                reinterpret_cast<struct wl_proxy *>(layerShell));
        }
        layerShell = nullptr;
    }
    if (shm) {
        wl_shm_destroy(shm);
        shm = nullptr;
    }
    if (compositor) {
        wl_compositor_destroy(compositor);
        compositor = nullptr;
    }
    if (registry) {
        wl_registry_destroy(registry);
        registry = nullptr;
    }
    if (display) {
        wl_display_roundtrip(display);
        wl_display_disconnect(display);
        display = nullptr;
    }
}

WaylandContext::~WaylandContext() { disconnect(); }
