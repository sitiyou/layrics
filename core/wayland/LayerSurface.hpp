#pragma once

#include <cstdint>

struct wl_surface;
struct wl_buffer;
struct wl_output;
struct zwlr_layer_surface_v1;
struct WaylandContext;

struct LayerSurfaceConfig {
    uint32_t anchor = 5;        /* ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP | LEFT */
    uint32_t desiredWidth = 0;
    uint32_t desiredHeight = 0;
    int32_t exclusiveZone = -1;
    uint32_t keyboardInteractivity = 0; /* NONE */
    int marginTop = 0;
    int marginRight = 0;
    int marginBottom = 0;
    int marginLeft = 0;
};

class LayerSurface {
  public:
    LayerSurface() = default;
    ~LayerSurface();

    LayerSurface(const LayerSurface &) = delete;
    LayerSurface &operator=(const LayerSurface &) = delete;

    bool initialize(WaylandContext &ctx, wl_output *output, uint32_t layer,
                    const LayerSurfaceConfig &config);
    void destroy();

    void attach(wl_buffer *buffer, int x, int y);
    void damage(int x, int y, int width, int height);
    void damageFull();
    void commit();
    void commitFrame(wl_buffer *buffer, bool fullDamage = true);

    wl_surface *surface() const { return m_surface; }
    int width() const { return m_width; }
    int height() const { return m_height; }
    bool configured() const { return m_configured; }

    static void onConfigure(void *data, zwlr_layer_surface_v1 *surface,
                            uint32_t serial, uint32_t width, uint32_t height);
    static void onClosed(void *data, zwlr_layer_surface_v1 *surface);

  private:
    wl_surface *m_surface = nullptr;
    zwlr_layer_surface_v1 *m_layerSurface = nullptr;
    int m_width = 0;
    int m_height = 0;
    bool m_configured = false;
};
