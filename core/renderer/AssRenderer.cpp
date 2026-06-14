#include "core/renderer/AssRenderer.hpp"
#include "core/utils/Logger.hpp"

#include <ass/ass.h>
#include <cairo.h>

#include <cstdio>
#include <cstring>
#include <cstdint>

AssRenderer::AssRenderer(std::string assContent)
    : m_assContent(std::move(assContent)) {}

AssRenderer::~AssRenderer() { shutdown(); }

void AssRenderer::messageCallback(int level, const char *fmt, va_list va,
                                  void *data) {
    (void)data;
    if (level > 6) {
        return;
    }
    if (::layrics::debugEnabled()) {
        fprintf(stderr, "[DEBUG] libass/%d: ", level);
        vfprintf(stderr, fmt, va);
    }
}

bool AssRenderer::initialize() {
    LAY_DEBUG("initializing libass");
    m_library = ass_library_init();
    if (!m_library) {
        LAY_ERR("ass_library_init failed");
        return false;
    }

    ass_set_message_cb(m_library, messageCallback, nullptr);

    m_renderer = ass_renderer_init(m_library);
    if (!m_renderer) {
        LAY_ERR("ass_renderer_init failed");
        ass_library_done(m_library);
        m_library = nullptr;
        return false;
    }

    ass_set_fonts(m_renderer, nullptr, "sans-serif",
                  ASS_FONTPROVIDER_AUTODETECT, nullptr, 1);

    if (!m_assContent.empty()) {
        m_track = ass_read_memory(m_library,
                                  m_assContent.data(), m_assContent.size(),
                                  nullptr);
        if (!m_track) {
            LAY_ERR("Failed to load ASS content");
        } else {
            LAY_LOG("ASS track loaded (%zu bytes)", m_assContent.size());
        }
    }

    return true;
}

void AssRenderer::invalidateSurface() {
    if (m_surface) {
        cairo_surface_destroy(m_surface);
        m_surface = nullptr;
    }
}

void AssRenderer::shutdown() {
    LAY_DEBUG("shutting down libass");
    invalidateSurface();
    if (m_track) {
        ass_free_track(m_track);
        m_track = nullptr;
    }
    if (m_renderer) {
        ass_renderer_done(m_renderer);
        m_renderer = nullptr;
    }
    if (m_library) {
        ass_library_done(m_library);
        m_library = nullptr;
    }
}

void AssRenderer::setSize(int width, int height) {
    if (width != m_width || height != m_height) {
        invalidateSurface();
        m_width = width;
        m_height = height;
    }
    LAY_DEBUG("set render size %dx%d", width, height);
}

void AssRenderer::loadContent(const std::string &content) {
    m_assContent = content;
    if (!m_library) {
        return;
    }
    invalidateSurface();
    if (m_track) {
        ass_free_track(m_track);
        m_track = nullptr;
    }
    m_track = ass_read_memory(m_library,
                              m_assContent.data(), m_assContent.size(),
                              nullptr);
    if (!m_track) {
        LAY_ERR("Failed to load ASS content");
    } else {
        LAY_LOG("ASS track reloaded (%zu bytes)", m_assContent.size());
    }
}

cairo_surface_t *AssRenderer::render(int64_t timestampMs) {
    if (!m_renderer || !m_track || m_width <= 0 || m_height <= 0) {
        lastRegions.clear();
        return nullptr;
    }

    ass_set_frame_size(m_renderer, m_width, m_height);

    int changed = 1;
    ASS_Image *img =
        ass_render_frame(m_renderer, m_track, timestampMs, &changed);

    if (!m_surface) {
        m_surface =
            cairo_image_surface_create(CAIRO_FORMAT_ARGB32, m_width, m_height);
        if (cairo_surface_status(m_surface) != CAIRO_STATUS_SUCCESS) {
            LAY_ERR("Failed to create surface %dx%d", m_width, m_height);
            cairo_surface_destroy(m_surface);
            m_surface = nullptr;
            lastRegions.clear();
            return nullptr;
        }
        changed = 1;
    }

    if (!changed) {
        return cairo_surface_reference(m_surface);
    }

    unsigned char *data = cairo_image_surface_get_data(m_surface);
    int stride = cairo_image_surface_get_stride(m_surface);

    memset(data, 0, static_cast<size_t>(stride) * m_height);

    lastRegions.clear();

    int numImages = 0;
    for (ASS_Image *cur = img; cur != nullptr; cur = cur->next) {
        if (cur->w == 0 || cur->h == 0) {
            continue;
        }

        unsigned int color = cur->color;
        unsigned char r = (color >> 24) & 0xFF;
        unsigned char g = (color >> 16) & 0xFF;
        unsigned char b = (color >> 8) & 0xFF;
        unsigned char a = 0xFF - (color & 0xFF);

        unsigned char *bitmap = cur->bitmap;
        int srcStride = cur->stride;

        for (int y = 0; y < cur->h; y++) {
            unsigned char *srcRow = bitmap + y * srcStride;
            unsigned char *dstRow =
                data + (cur->dst_y + y) * stride + cur->dst_x * 4;
            for (int x = 0; x < cur->w; x++) {
                unsigned long k = (unsigned)(srcRow[x] * a);
                if (!k) {
                    continue;
                }
                unsigned char *dstPixel = dstRow + 4 * x;

                dstPixel[0] =
                    (dstPixel[0] * (65025 - k) + b * k + 65025 / 2) / 65025;
                dstPixel[1] =
                    (dstPixel[1] * (65025 - k) + g * k + 65025 / 2) / 65025;
                dstPixel[2] =
                    (dstPixel[2] * (65025 - k) + r * k + 65025 / 2) / 65025;
                dstPixel[3] =
                    (dstPixel[3] * (65025 - k) + a * k + 65025 / 2) / 65025;
            }
        }

        lastRegions.push_back({cur->dst_x, cur->dst_y, cur->w, cur->h});
        numImages++;
    }

    cairo_surface_mark_dirty(m_surface);
    // LAY_DEBUG("rendered %d images ts=%lld %dx%d", numImages,
    //           (long long)timestampMs, m_width, m_height);
    return cairo_surface_reference(m_surface);
}
