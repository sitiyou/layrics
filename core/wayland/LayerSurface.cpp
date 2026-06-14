#include "core/wayland/LayerSurface.hpp"
#include "core/wayland/LayerShellProtocol.hpp"
#include "core/wayland/WaylandContext.hpp"
#include "core/utils/Logger.hpp"

#include <wayland-client.h>

#include <climits>

void LayerSurface::onConfigure(void *data, zwlr_layer_surface_v1 *surface,
                               uint32_t serial, uint32_t width,
                               uint32_t height) {
    auto *self = static_cast<LayerSurface *>(data);
    zwlr_layer_surface_v1_ack_configure(surface, serial);
    self->m_width = static_cast<int>(width);
    self->m_height = static_cast<int>(height);
    self->m_configured = true;
    LAY_DEBUG("configured: %dx%d serial=%u", width, height, serial);
}

void LayerSurface::onClosed(void *data, zwlr_layer_surface_v1 *surface) {
    (void)surface;
    auto *self = static_cast<LayerSurface *>(data);
    self->m_width = 0;
    self->m_height = 0;
    self->m_configured = false;
    LAY_LOG("layer surface closed");
}

static const zwlr_layer_surface_v1_listener layerSurfaceListener = {
    LayerSurface::onConfigure,
    LayerSurface::onClosed,
};

LayerSurface::~LayerSurface() { destroy(); }

bool LayerSurface::initialize(WaylandContext &ctx, wl_output *output,
                               uint32_t layer, const LayerSurfaceConfig &config) {
    if (!ctx.compositor || !ctx.layerShell) {
        LAY_ERR("WaylandContext not connected, missing compositor or layer_shell");
        return false;
    }

    destroy();

    m_surface = wl_compositor_create_surface(ctx.compositor);
    if (!m_surface) {
        LAY_ERR("wl_compositor_create_surface failed");
        return false;
    }

    m_layerSurface = zwlr_layer_shell_v1_get_layer_surface(
        ctx.layerShell, m_surface, output, layer, "layrics");
    if (!m_layerSurface) {
        LAY_ERR("zwlr_layer_shell_v1_get_layer_surface failed");
        wl_surface_destroy(m_surface);
        m_surface = nullptr;
        return false;
    }

    zwlr_layer_surface_v1_add_listener(m_layerSurface, &layerSurfaceListener, this);

    zwlr_layer_surface_v1_set_anchor(m_layerSurface, config.anchor);
    zwlr_layer_surface_v1_set_size(m_layerSurface, config.desiredWidth,
                                    config.desiredHeight);
    zwlr_layer_surface_v1_set_exclusive_zone(m_layerSurface, config.exclusiveZone);
    zwlr_layer_surface_v1_set_keyboard_interactivity(m_layerSurface,
                                                      config.keyboardInteractivity);
    if (config.marginTop || config.marginRight || config.marginBottom ||
        config.marginLeft) {
        zwlr_layer_surface_v1_set_margin(m_layerSurface, config.marginTop,
                                          config.marginRight, config.marginBottom,
                                          config.marginLeft);
    }

    wl_surface_commit(m_surface);
    ctx.roundtrip();

    if (!m_configured) {
        LAY_ERR("Layer surface did not receive configure");
        destroy();
        return false;
    }

    LAY_LOG("layer surface initialized: %dx%d", m_width, m_height);
    return true;
}

void LayerSurface::destroy() {
    if (m_layerSurface) {
        zwlr_layer_surface_v1_destroy(m_layerSurface);
        m_layerSurface = nullptr;
    }
    if (m_surface) {
        wl_surface_destroy(m_surface);
        m_surface = nullptr;
    }
    m_width = 0;
    m_height = 0;
    m_configured = false;
}

void LayerSurface::attach(wl_buffer *buffer, int x, int y) {
    wl_surface_attach(m_surface, buffer, x, y);
}

void LayerSurface::damage(int x, int y, int width, int height) {
    wl_surface_damage_buffer(m_surface, x, y, width, height);
}

void LayerSurface::damageFull() {
    wl_surface_damage_buffer(m_surface, 0, 0, INT32_MAX, INT32_MAX);
}

void LayerSurface::commit() {
    wl_surface_commit(m_surface);
}

void LayerSurface::commitFrame(wl_buffer *buffer) {
    wl_surface_attach(m_surface, buffer, 0, 0);
    wl_surface_damage_buffer(m_surface, 0, 0, INT32_MAX, INT32_MAX);
    wl_surface_commit(m_surface);
}
