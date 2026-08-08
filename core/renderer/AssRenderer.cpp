#include "core/renderer/AssRenderer.hpp"
#include "core/renderer/VulkanContext.hpp"
#include "core/utils/Logger.hpp"

#include <ass/ass.h>
#include <vulkan/vulkan.h>

#include <algorithm>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <utility>

AssRenderer::AssRenderer(std::string assContent)
    : m_assContent(std::move(assContent)) {}

AssRenderer::~AssRenderer() { shutdown(); }

void AssRenderer::messageCallback(int level, const char *fmt, va_list va,
                                  void *data) {
    (void)data;
    if (level > 6) {
        return;
    }
    if (::layrics::g_debugEnabled) {
        fprintf(stderr, "[DEBUG] libass/%d: ", level);
        vfprintf(stderr, fmt, va);
    }
}

bool AssRenderer::initialize(VulkanContext &vk) {
    LAY_DEBUG("initializing libass");
    m_vk = &vk;

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
        m_track = ass_read_memory(m_library, m_assContent.data(),
                                  m_assContent.size(), nullptr);
        if (!m_track) {
            LAY_ERR("Failed to load ASS content");
        } else {
            LAY_LOG("ASS track loaded (%zu bytes)", m_assContent.size());
        }
    }
    return true;
}

void AssRenderer::destroyAtlas() {
    if (m_atlas.image) {
        m_vk->destroyTexture(m_atlas);
    }
    m_atlasReady = false;
    m_uploadPending = false;
    m_quads.clear();
}

void AssRenderer::shutdown() {
    LAY_DEBUG("shutting down libass renderer");
    if (m_vk) {
        destroyAtlas();
        m_vk->destroyDynamicBuffer(m_vertexBuf);
    }
    m_vk = nullptr;
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
        m_width = width;
        m_height = height;
        // Glyph bitmaps are size-independent; the atlas survives a resize.
    }
    LAY_DEBUG("set render size %dx%d", width, height);
}

void AssRenderer::loadContent(const std::string &content) {
    m_assContent = content;
    if (!m_library) {
        return;
    }
    m_uploadPending = false;
    m_quads.clear();
    if (m_track) {
        ass_free_track(m_track);
        m_track = nullptr;
    }
    m_track = ass_read_memory(m_library, m_assContent.data(),
                              m_assContent.size(), nullptr);
    if (!m_track) {
        LAY_ERR("Failed to load ASS content");
    } else {
        LAY_LOG("ASS track reloaded (%zu bytes)", m_assContent.size());
    }
}

void AssRenderer::prepare(int64_t timestampMs) {
    if (!m_renderer || !m_track || m_width <= 0 || m_height <= 0) {
        lastRegions.clear();
        contentChanged = false;
        return;
    }

    ass_set_frame_size(m_renderer, m_width, m_height);

    int changed = 1;
    ASS_Image *img =
        ass_render_frame(m_renderer, m_track, timestampMs, &changed);
    contentChanged = changed;

    if (!changed) {
        // Same bitmaps as the previous frame: reuse packed atlas + quads
        // (no re-pack, no re-upload).
        return;
    }

    if (packImages(img)) {
        fillVertexBuffer();
    } else {
        // Never draw partial quads against a stale atlas.
        m_quads.clear();
        lastRegions.clear();
    }
}

// mpv-style shelf packer: w+2 x h+2 slots with a 1px edge-pixel ring so
// linear sampling never bleeds between glyphs; doubles the atlas on overflow.
bool AssRenderer::packImages(const ASS_Image *img) {
    if (!m_atlasReady) {
        m_atlasW = kAtlasMin;
        m_atlasH = kAtlasMin;
        m_atlas = m_vk->createTexture(m_atlasW, m_atlasH);
        if (!m_atlas.image) {
            LAY_ERR("failed to create atlas texture");
            return false;
        }
        m_atlasData.assign(static_cast<size_t>(m_atlasW) * m_atlasH, 0);
        m_atlasReady = true;
    }

    while (true) {
        int x = 1, y = 1, rowH = 0;
        m_quads.clear();
        lastRegions.clear();
        bool overflow = false;

        for (const ASS_Image *cur = img; cur != nullptr; cur = cur->next) {
            if (cur->w == 0 || cur->h == 0) {
                continue;
            }
            // Shelf packing with padding reserved (w+2 x h+2, bitmap at +1).
            if (x + cur->w + 2 > m_atlasW) {
                x = 1;
                y += rowH;
                rowH = 0;
            }
            if (y + cur->h + 2 > m_atlasH) {
                overflow = true;
                break;
            }

            // Copy the bitmap (row-by-row, honoring the ASS stride) into the
            // atlas slot [x, x+w) x [y, y+h).
            uint8_t *dst = m_atlasData.data() + y * m_atlasW + x;
            const uint8_t *src = cur->bitmap;
            for (int r = 0; r < cur->h; r++) {
                memcpy(dst + r * m_atlasW, src + r * cur->stride,
                       static_cast<size_t>(cur->w));
            }
            // 1px duplicated edge ring (mpv fill_padding_1): no sampler bleed
            // between neighboring atlas slots.
            for (int r = 0; r < cur->h; r++) {
                uint8_t *row = m_atlasData.data() + (y + r) * m_atlasW + x;
                row[-1] = row[0];
                row[cur->w] = row[cur->w - 1];
            }
            memcpy(m_atlasData.data() + (y - 1) * m_atlasW + x - 1,
                   m_atlasData.data() + y * m_atlasW + x - 1,
                   static_cast<size_t>(cur->w) + 2);
            memcpy(m_atlasData.data() + (y + cur->h) * m_atlasW + x - 1,
                   m_atlasData.data() + (y + cur->h - 1) * m_atlasW + x - 1,
                   static_cast<size_t>(cur->w) + 2);

            unsigned int color = cur->color;
            float r = static_cast<float>((color >> 24) & 0xFF) / 255.0f;
            float g = static_cast<float>((color >> 16) & 0xFF) / 255.0f;
            float b = static_cast<float>((color >> 8) & 0xFF) / 255.0f;
            float a = static_cast<float>(0xFF - (color & 0xFF)) / 255.0f;

            Quad q;
            q.x = static_cast<float>(cur->dst_x);
            q.y = static_cast<float>(cur->dst_y);
            q.w = static_cast<float>(cur->w);
            q.h = static_cast<float>(cur->h);
            // Sample exactly the bitmap slot; the padding ring is never
            // sampled directly.
            q.u0 = static_cast<float>(x) / m_atlasW;
            q.v0 = static_cast<float>(y) / m_atlasH;
            q.u1 = static_cast<float>(x + cur->w) / m_atlasW;
            q.v1 = static_cast<float>(y + cur->h) / m_atlasH;
            // Premultiply rgb by alpha for the shader output.
            q.r = r * a;
            q.g = g * a;
            q.b = b * a;
            q.a = a;
            m_quads.push_back(q);

            lastRegions.push_back({cur->dst_x, cur->dst_y, cur->w, cur->h});

            x += cur->w + 2;
            if (cur->h + 2 > rowH) {
                rowH = cur->h + 2;
            }
        }

        if (!overflow) {
            m_packedH = y + rowH;
            m_uploadPending = true;
            return true;
        }

        // Atlas full: double it (mpv-style) and re-pack from scratch.
        if (m_atlasW >= kAtlasMax && m_atlasH >= kAtlasMax) {
            LAY_ERR("atlas exceeds max size %dx%d", m_atlasW, m_atlasH);
            return false;
        }
        int newW = std::min(m_atlasW * 2, kAtlasMax);
        int newH = std::min(m_atlasH * 2, kAtlasMax);
        if (newH == m_atlasH && newW == m_atlasW) {
            return false;
        }
        m_vk->destroyTexture(m_atlas);
        m_atlas = m_vk->createTexture(newW, newH);
        if (!m_atlas.image) {
            LAY_ERR("failed to grow atlas texture");
            return false;
        }
        m_atlasW = newW;
        m_atlasH = newH;
        m_atlasData.assign(static_cast<size_t>(m_atlasW) * m_atlasH, 0);
        LAY_LOG("atlas grown to %dx%d", m_atlasW, m_atlasH);
    }
}

void AssRenderer::fillVertexBuffer() {
    if (m_quads.empty()) {
        return;
    }
    const size_t vertexCount = m_quads.size() * 4;
    const size_t stride = 8 * sizeof(float);
    if (!m_vk->ensureDynamicBuffer(m_vertexBuf, vertexCount * stride,
                                   VK_BUFFER_USAGE_VERTEX_BUFFER_BIT)) {
        return;
    }
    float *dst = static_cast<float *>(m_vertexBuf.mapped);
    for (const auto &q : m_quads) {
        // TRIANGLE_STRIP (TL, TR, BL, BR) tiles the quad; (TL, TR, BR, BL)
        // leaves a wedge hole between the two diagonals.
        float verts[4][8] = {
            {q.x, q.y, q.u0, q.v0, q.r, q.g, q.b, q.a},
            {q.x + q.w, q.y, q.u1, q.v0, q.r, q.g, q.b, q.a},
            {q.x, q.y + q.h, q.u0, q.v1, q.r, q.g, q.b, q.a},
            {q.x + q.w, q.y + q.h, q.u1, q.v1, q.r, q.g, q.b, q.a},
        };
        memcpy(dst, verts, sizeof(verts));
        dst += 8 * 4;
    }
}

void AssRenderer::recordUploads(VkCommandBuffer cmd) {
    if (!m_uploadPending || !m_atlasReady || m_packedH <= 0) {
        return;
    }
    // Upload the used region of the atlas (full width x packed height).
    m_vk->recordUploadTexture(cmd, m_atlas, m_atlasW, m_packedH,
                              m_atlasData.data(), m_atlasW);
    m_uploadPending = false;
}

void AssRenderer::recordDraws(VkCommandBuffer cmd, float offsetX, float offsetY,
                              int screenW, int screenH) {
    if (m_quads.empty() || !m_vertexBuf.buffer || !m_atlas.image) {
        return;
    }
    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, m_vk->pipeline());

    float push[4] = {offsetX, offsetY, static_cast<float>(screenW),
                     static_cast<float>(screenH)};
    vkCmdPushConstants(cmd, m_vk->pipelineLayout(), VK_SHADER_STAGE_VERTEX_BIT,
                       0, sizeof(push), push);

    VkDescriptorSet set = m_atlas.set;
    vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS,
                            m_vk->pipelineLayout(), 0, 1, &set, 0, nullptr);

    VkDeviceSize offset = 0;
    vkCmdBindVertexBuffers(cmd, 0, 1, &m_vertexBuf.buffer, &offset);
    // One draw per quad: consecutive strips must not share triangles.
    for (size_t i = 0; i < m_quads.size(); i++) {
        vkCmdDraw(cmd, 4, 1, static_cast<uint32_t>(i * 4), 0);
    }
}
