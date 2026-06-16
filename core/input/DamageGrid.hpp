#pragma once

#include <cstdint>
#include <vector>

#include "core/types/Common.hpp"

class DamageGrid {
  public:
    DamageGrid() = default;
    explicit DamageGrid(int width, int height);

    void setSurfaceSize(int width, int height);

    void beginFrame();
    void addRegion(int x, int y, int w, int h);

    std::vector<RenderRect> buildRegions() const;
    std::vector<RenderRect> buildDamage() const;

  private:
    std::vector<RenderRect> cellsToRects(const std::vector<char> &cells) const;

    static constexpr int kGridSize = 16;

    int m_width = 0;
    int m_height = 0;
    int m_cellsX = 0;
    int m_cellsY = 0;
    std::vector<char> m_grid;
    std::vector<char> m_prevGrid;
};
