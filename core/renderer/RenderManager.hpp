#pragma once

#include <cstdint>
#include <memory>
#include <vector>

#include "core/renderer/IRenderer.hpp"
#include "core/types/Common.hpp"

class RenderManager {
  public:
    void addRenderer(std::unique_ptr<IRenderer> renderer);

    void setSize(int width, int height);
    void setOffset(double offsetX, double offsetY);

    RenderResult render(uint8_t *buffer, int64_t timestampMs);

  private:
    std::vector<std::unique_ptr<IRenderer>> m_renderers;
    double m_offsetX = 0.0;
    double m_offsetY = 0.0;
    int m_width = 0;
    int m_height = 0;
};
