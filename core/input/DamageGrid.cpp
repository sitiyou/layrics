#include "core/input/DamageGrid.hpp"

#include <algorithm>
#include <cstring>

DamageGrid::DamageGrid(int width, int height) { setSurfaceSize(width, height); }

void DamageGrid::setSurfaceSize(int width, int height) {
    m_width = width;
    m_height = height;
    m_cellsX = (width + kGridSize - 1) / kGridSize;
    m_cellsY = (height + kGridSize - 1) / kGridSize;
    size_t size = static_cast<size_t>(m_cellsX) * m_cellsY;
    m_grid.assign(size, 0);
    m_prevGrid.assign(size, 0);
}

void DamageGrid::beginFrame() {
    std::swap(m_grid, m_prevGrid);
    std::fill(m_grid.begin(), m_grid.end(), 0);
}

void DamageGrid::addRegion(int x, int y, int w, int h) {
    if (m_cellsX <= 0 || m_cellsY <= 0 || w <= 0 || h <= 0) {
        return;
    }

    int cx1 = std::max(0, x / kGridSize);
    int cy1 = std::max(0, y / kGridSize);
    int cx2 = std::min(m_cellsX - 1, (x + w - 1) / kGridSize);
    int cy2 = std::min(m_cellsY - 1, (y + h - 1) / kGridSize);

    for (int cy = cy1; cy <= cy2; cy++) {
        int rowOffset = cy * m_cellsX;
        for (int cx = cx1; cx <= cx2; cx++) {
            m_grid[rowOffset + cx] = 1;
        }
    }
}

std::vector<RenderRect> DamageGrid::buildRegions() const {
    return cellsToRects(m_grid);
}

std::vector<RenderRect> DamageGrid::buildDamage() const {
    size_t size = m_grid.size();
    std::vector<char> damage(size);
    for (size_t i = 0; i < size; i++) {
        damage[i] = m_grid[i] || m_prevGrid[i];
    }
    return cellsToRects(damage);
}

std::vector<RenderRect>
DamageGrid::cellsToRects(const std::vector<char> &cells) const {

    std::vector<RenderRect> rects;
    if (m_cellsX <= 0 || m_cellsY <= 0) {
        return rects;
    }

    for (int cy = 0; cy < m_cellsY; cy++) {
        int rowOffset = cy * m_cellsX;
        int cx = 0;
        while (cx < m_cellsX) {
            if (!cells[rowOffset + cx]) {
                cx++;
                continue;
            }
            int start = cx;
            while (cx < m_cellsX && cells[rowOffset + cx]) {
                cx++;
            }
            rects.push_back({start * kGridSize, cy * kGridSize,
                             (cx - start) * kGridSize, kGridSize});
        }
    }

    return rects;
}
