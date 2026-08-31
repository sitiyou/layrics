#pragma once

#include <vulkan/vulkan.h>

#include <cstddef>
#include <cstdint>
#include <vector>

#include "core/types/Common.hpp"

struct wl_display;
struct wl_surface;

// Owns the Vulkan instance/device/swapchain and per-frame presentation.
// Single-threaded: all methods run on the render thread.
class VulkanContext {
  public:
    VulkanContext() = default;
    ~VulkanContext();

    VulkanContext(const VulkanContext &) = delete;
    VulkanContext &operator=(const VulkanContext &) = delete;

    bool initialize(wl_display *display, wl_surface *surface, int width,
                    int height);
    void shutdown();

    // Headless mode: no Wayland surface and no swapchain. Renders into an
    // offscreen image and reads the pixels back to CPU memory (for tests).
    bool initializeOffscreen(int width, int height);
    bool beginOffscreenFrame();
    void endOffscreenFrame();
    std::vector<uint8_t> readbackOffscreen();

    bool ready() const { return m_swapchain != VK_NULL_HANDLE || m_offscreen; }
    bool dirty() const { return m_swapchainDirty; }
    void markDirty() { m_swapchainDirty = true; }

    int width() const { return static_cast<int>(m_extent.width); }
    int height() const { return static_cast<int>(m_extent.height); }

    // Recreate the swapchain (call on layer configure, outside a frame).
    void resize(int width, int height);

    // Frame flow: beginFrame() acquires an image + starts the command buffer
    // (uploads go between beginFrame and beginRenderPass); false = swapchain
    // out of date, recreate and retry later.
    bool beginFrame();
    void beginRenderPass();
    // Present the frame. damage = buffer-space rects that changed since the
    // last commit (sent via VK_KHR_incremental_present); empty = full damage.
    void endFrame(const std::vector<RenderRect> &damage = {});
    VkCommandBuffer commandBuffer() const { return m_cmd; }

    // Present a fully transparent frame (used when hiding the overlay).
    void presentTransparent();

    // --- renderer helpers ------------------------------------------------

    struct Texture {
        VkImage image = VK_NULL_HANDLE;
        VkDeviceMemory memory = VK_NULL_HANDLE;
        VkImageView view = VK_NULL_HANDLE;
        VkDescriptorSet set = VK_NULL_HANDLE;
        bool uploaded = false; // content valid (layout SHADER_READ_ONLY)
    };

    Texture createTexture(int width, int height);
    void destroyTexture(Texture &tex);

    // Reset the texture descriptor pool. Only safe after a fence wait (no
    // descriptor sets in flight); call before allocating new textures.
    void resetTexturePool();

    // Record a staging upload of R8 pixels into the texture on cmd.
    // The staging buffer is freed automatically after kFramesInFlight frames.
    void recordUploadTexture(VkCommandBuffer cmd, Texture &tex, int width,
                             int height, const void *pixels, size_t stride);

    struct DynamicBuffer {
        VkBuffer buffer = VK_NULL_HANDLE;
        VkDeviceMemory memory = VK_NULL_HANDLE;
        void *mapped = nullptr;
        VkDeviceSize capacity = 0;
    };
    bool ensureDynamicBuffer(DynamicBuffer &buf, VkDeviceSize size,
                             VkBufferUsageFlags usage);
    void destroyDynamicBuffer(DynamicBuffer &buf);

    // --- accessors -------------------------------------------------------

    VkDevice device() const { return m_device; }
    VkPhysicalDevice physicalDevice() const { return m_phys; }
    VkInstance instance() const { return m_instance; }
    VkQueue queue() const { return m_queue; }
    uint32_t queueFamily() const { return m_queueFamily; }
    VkRenderPass renderPass() const { return m_renderPass; }
    VkPipeline pipeline() const { return m_pipeline; }
    VkPipelineLayout pipelineLayout() const { return m_pipelineLayout; }

  private:
    struct FrameResources {
        std::vector<VkBuffer> buffers;
        std::vector<VkDeviceMemory> memories;
    };

    static constexpr uint32_t kFramesInFlight = 2;

    wl_display *m_display = nullptr;
    wl_surface *m_wlSurface = nullptr;

    VkInstance m_instance = VK_NULL_HANDLE;
    VkPhysicalDevice m_phys = VK_NULL_HANDLE;
    VkDevice m_device = VK_NULL_HANDLE;
    VkQueue m_queue = VK_NULL_HANDLE;
    uint32_t m_queueFamily = 0;
    VkSurfaceKHR m_vkSurface = VK_NULL_HANDLE;

    VkSwapchainKHR m_swapchain = VK_NULL_HANDLE;
    VkFormat m_format = VK_FORMAT_UNDEFINED;
    VkExtent2D m_extent = {};
    VkCompositeAlphaFlagBitsKHR m_compositeAlpha =
        VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
    std::vector<VkImage> m_images;
    std::vector<VkImageView> m_views;
    std::vector<VkFramebuffer> m_framebuffers;

    // Offscreen (headless) render target.
    bool m_offscreen = false;
    VkImage m_offImage = VK_NULL_HANDLE;
    VkDeviceMemory m_offMemory = VK_NULL_HANDLE;
    VkImageView m_offView = VK_NULL_HANDLE;
    VkFramebuffer m_offFramebuffer = VK_NULL_HANDLE;
    VkBuffer m_offStaging = VK_NULL_HANDLE;
    VkDeviceMemory m_offStagingMemory = VK_NULL_HANDLE;
    void *m_offStagingMapped = nullptr;

    VkRenderPass m_renderPass = VK_NULL_HANDLE;
    VkPipelineLayout m_pipelineLayout = VK_NULL_HANDLE;
    VkPipeline m_pipeline = VK_NULL_HANDLE;
    VkShaderModule m_vertModule = VK_NULL_HANDLE;
    VkShaderModule m_fragModule = VK_NULL_HANDLE;

    VkDescriptorPool m_descPool = VK_NULL_HANDLE;
    VkDescriptorSetLayout m_descLayout = VK_NULL_HANDLE;
    VkSampler m_sampler = VK_NULL_HANDLE;

    VkCommandPool m_cmdPool = VK_NULL_HANDLE;
    VkCommandBuffer m_cmd = VK_NULL_HANDLE;
    uint32_t m_imageIndex = 0;
    VkSemaphore m_acquireSems[kFramesInFlight] = {};
    VkSemaphore m_renderSems[kFramesInFlight] = {};
    VkFence m_fence = VK_NULL_HANDLE;
    uint32_t m_frameIndex = 0;
    FrameResources m_frameResources[kFramesInFlight];

    bool m_swapchainDirty = false;
    int m_requestedWidth = 0;
    int m_requestedHeight = 0;

    bool initInstance(bool withSurface);
    bool pickPhysicalDevice();
    bool pickQueueFamily(bool needPresent);
    bool pickSurfaceFormat();
    bool createDevice();
    bool createSwapchain();
    void destroySwapchain();
    bool createRenderPass(VkImageLayout finalLayout);
    bool createPipeline();
    bool createSyncObjects();
    bool createOffscreenTarget(int width, int height);
    void destroyOffscreenTarget();

    void destroyFrameResources(FrameResources &fr);
    void reclaimFrameResources();
};
