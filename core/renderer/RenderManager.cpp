#include "core/renderer/RenderManager.hpp"
#include "core/utils/Logger.hpp"

#include <cairo.h>

#include <cstdio>
#include <utility>

void RenderManager::addRenderer(std::unique_ptr<IRenderer> renderer) {
    if (renderer) {
        renderer->setSize(m_width, m_height);
        m_renderers.push_back(std::move(renderer));
        LAY_LOG("renderer added, total=%zu", m_renderers.size());
    }
}

void RenderManager::setSize(int width, int height) {
    m_width = width;
    m_height = height;
    LAY_DEBUG("RenderManager set size %dx%d", width, height);
    for (auto &r : m_renderers) {
        r->setSize(width, height);
    }
}

void RenderManager::setOffset(double offsetX, double offsetY) {
    m_offsetX = offsetX;
    m_offsetY = offsetY;
}

RenderResult RenderManager::render(uint8_t *buffer, int64_t timestampMs) {
    RenderResult result;

    if (!buffer || m_width <= 0 || m_height <= 0) {
        return result;
    }

    int stride = cairo_format_stride_for_width(CAIRO_FORMAT_ARGB32, m_width);

    cairo_surface_t *target = cairo_image_surface_create_for_data(
        buffer, CAIRO_FORMAT_ARGB32, m_width, m_height, stride);
    if (cairo_surface_status(target) != CAIRO_STATUS_SUCCESS) {
        LAY_ERR("RenderManager: failed to create target surface");
        cairo_surface_destroy(target);
        return result;
    }

    cairo_t *cr = cairo_create(target);

    cairo_set_operator(cr, CAIRO_OPERATOR_CLEAR);
    cairo_paint(cr);
    cairo_set_operator(cr, CAIRO_OPERATOR_OVER);

    cairo_translate(cr, m_offsetX, m_offsetY);

    for (auto &r : m_renderers) {
        cairo_surface_t *surf = r->render(timestampMs);
        if (!surf) {
            continue;
        }

        cairo_set_source_surface(cr, surf, 0, 0);
        cairo_paint(cr);
        cairo_surface_destroy(surf);

        for (const auto &rect : r->lastRegions) {
            result.regions.push_back(
                {static_cast<int>(rect.x + m_offsetX),
                 static_cast<int>(rect.y + m_offsetY), rect.w, rect.h});
        }
    }

    cairo_destroy(cr);
    cairo_surface_destroy(target);

    // LAY_DEBUG("RenderManager composed %zu region(s)", result.regions.size());
    return result;
}
