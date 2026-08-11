#pragma once

#include <cstdint>
#include <vector>

#include <vulkan/vulkan.h>

#include "core/types/Common.hpp"

class VulkanContext;

// Abstract renderer drawing into the Vulkan framebuffer.
// Lifecycle: initialize() -> setSize() -> per frame: prepare() [CPU],
// recordUploads(), recordDraws() -> shutdown()
class IRenderer {
  public:
    virtual ~IRenderer() = default;

    virtual bool initialize(VulkanContext &vk) = 0;
    virtual void shutdown() = 0;
    virtual void setSize(int width, int height) = 0;

    // CPU-side content generation (libass frame rendering).
    virtual void prepare(int64_t timestampMs) = 0;

    // Texture uploads; outside the render pass.
    virtual void recordUploads(VkCommandBuffer cmd) = 0;

    // Draw commands; inside the render pass, pipeline/push constants/viewport
    // already set up by the caller.
    virtual void recordDraws(VkCommandBuffer cmd, float offsetX, float offsetY,
                             int screenW, int screenH) = 0;

    // Renderer-local regions (no drag offset); valid after prepare().
    std::vector<RenderRect> lastRegions;
    bool contentChanged = true;
};
