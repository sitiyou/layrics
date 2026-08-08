#include "core/renderer/RenderManager.hpp"
#include "core/utils/Logger.hpp"

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

void RenderManager::reset() {
    m_everRendered = false;
    m_regions.clear();
    m_contentChanged = false;
}

void RenderManager::prepare(int64_t timestampMs) {
    m_regions.clear();
    m_contentChanged = false;
    for (auto &r : m_renderers) {
        r->prepare(timestampMs);
        m_contentChanged |= r->contentChanged;
        for (const auto &rect : r->lastRegions) {
            m_regions.push_back({rect.x + static_cast<int>(m_offsetX),
                                 rect.y + static_cast<int>(m_offsetY), rect.w,
                                 rect.h});
        }
    }
}

void RenderManager::recordUploads(VkCommandBuffer cmd) {
    for (auto &r : m_renderers) {
        r->recordUploads(cmd);
    }
}

void RenderManager::recordDraws(VkCommandBuffer cmd) {
    for (auto &r : m_renderers) {
        r->recordDraws(cmd, static_cast<float>(m_offsetX),
                       static_cast<float>(m_offsetY), m_width, m_height);
    }
    m_everRendered = true;
}
