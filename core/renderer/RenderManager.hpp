#pragma once

#include <cstdint>
#include <memory>
#include <vector>

#include "core/renderer/IRenderer.hpp"
#include "core/types/Common.hpp"

// Aggregates renderers and drives the frame flow:
// prepare() -> recordUploads() -> recordDraws(); aggregates per-frame
// regions (drag offset applied) for the input region update.
class RenderManager {
  public:
    void addRenderer(std::unique_ptr<IRenderer> renderer);

    void setSize(int width, int height);
    void setOffset(double offsetX, double offsetY);

    void prepare(int64_t timestampMs);
    void recordUploads(VkCommandBuffer cmd);
    void recordDraws(VkCommandBuffer cmd);

    const std::vector<RenderRect> &regions() const { return m_regions; }
    bool hasContentChanged() const { return m_contentChanged; }
    bool hasRendered() const { return m_everRendered; }

    void reset();

  private:
    std::vector<std::unique_ptr<IRenderer>> m_renderers;
    double m_offsetX = 0.0;
    double m_offsetY = 0.0;
    int m_width = 0;
    int m_height = 0;

    std::vector<RenderRect> m_regions;
    bool m_contentChanged = false;
    bool m_everRendered = false;
};
