#define VK_USE_PLATFORM_WAYLAND_KHR 1

#include "core/renderer/VulkanContext.hpp"
#include "core/utils/Logger.hpp"

#include <wayland-client.h>

#include <algorithm>
#include <cstdio>
#include <cstring>

#define VK_CHECK(x)                                                            \
    do {                                                                       \
        VkResult _r = (x);                                                     \
        if (_r != VK_SUCCESS) {                                                \
            LAY_ERR("Vulkan call %s failed (%d)", #x, _r);                     \
            return false;                                                      \
        }                                                                      \
    } while (0)

namespace {

VkMemoryPropertyFlags wantHostVisibleMemory(VkPhysicalDevice phys,
                                            const VkMemoryRequirements &req,
                                            uint32_t &outIndex) {
    VkPhysicalDeviceMemoryProperties props;
    vkGetPhysicalDeviceMemoryProperties(phys, &props);
    VkMemoryPropertyFlags want = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
                                 VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    for (uint32_t i = 0; i < props.memoryTypeCount; i++) {
        if ((req.memoryTypeBits & (1u << i)) &&
            (props.memoryTypes[i].propertyFlags & want) == want) {
            outIndex = i;
            return want;
        }
    }
    return 0;
}

} // namespace

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

VulkanContext::~VulkanContext() { shutdown(); }

bool VulkanContext::initialize(wl_display *display, wl_surface *surface,
                               int width, int height) {
    m_display = display;
    m_wlSurface = surface;
    m_requestedWidth = width;
    m_requestedHeight = height;

    if (!initInstance(true) || !pickPhysicalDevice() || !createDevice() ||
        !pickSurfaceFormat() ||
        !createRenderPass(VK_IMAGE_LAYOUT_PRESENT_SRC_KHR) ||
        !createPipeline() || !createSyncObjects() || !createSwapchain()) {
        shutdown();
        return false;
    }
    LAY_LOG("Vulkan initialized: %ux%u", m_extent.width, m_extent.height);
    return true;
}

bool VulkanContext::initializeOffscreen(int width, int height) {
    m_requestedWidth = width;
    m_requestedHeight = height;
    m_extent = {static_cast<uint32_t>(width), static_cast<uint32_t>(height)};
    m_format = VK_FORMAT_R8G8B8A8_UNORM;
    m_offscreen = true;

    if (!initInstance(false) || !pickPhysicalDevice() || !createDevice() ||
        !createRenderPass(VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL) ||
        !createPipeline() || !createSyncObjects() ||
        !createOffscreenTarget(width, height)) {
        shutdown();
        return false;
    }
    LAY_LOG("Vulkan offscreen initialized: %ux%u", m_extent.width,
            m_extent.height);
    return true;
}

void VulkanContext::shutdown() {
    if (m_device != VK_NULL_HANDLE) {
        vkDeviceWaitIdle(m_device);
    }

    destroySwapchain();
    destroyOffscreenTarget();

    if (m_fence != VK_NULL_HANDLE) {
        vkDestroyFence(m_device, m_fence, nullptr);
        m_fence = VK_NULL_HANDLE;
    }
    for (uint32_t i = 0; i < kFramesInFlight; i++) {
        if (m_acquireSems[i]) {
            vkDestroySemaphore(m_device, m_acquireSems[i], nullptr);
            m_acquireSems[i] = VK_NULL_HANDLE;
        }
        if (m_renderSems[i]) {
            vkDestroySemaphore(m_device, m_renderSems[i], nullptr);
            m_renderSems[i] = VK_NULL_HANDLE;
        }
        destroyFrameResources(m_frameResources[i]);
    }
    if (m_cmdPool != VK_NULL_HANDLE) {
        vkDestroyCommandPool(m_device, m_cmdPool, nullptr);
        m_cmdPool = VK_NULL_HANDLE;
    }
    if (m_pipeline != VK_NULL_HANDLE) {
        vkDestroyPipeline(m_device, m_pipeline, nullptr);
        m_pipeline = VK_NULL_HANDLE;
    }
    if (m_pipelineLayout != VK_NULL_HANDLE) {
        vkDestroyPipelineLayout(m_device, m_pipelineLayout, nullptr);
        m_pipelineLayout = VK_NULL_HANDLE;
    }
    if (m_fragModule != VK_NULL_HANDLE) {
        vkDestroyShaderModule(m_device, m_fragModule, nullptr);
        m_fragModule = VK_NULL_HANDLE;
    }
    if (m_vertModule != VK_NULL_HANDLE) {
        vkDestroyShaderModule(m_device, m_vertModule, nullptr);
        m_vertModule = VK_NULL_HANDLE;
    }
    if (m_renderPass != VK_NULL_HANDLE) {
        vkDestroyRenderPass(m_device, m_renderPass, nullptr);
        m_renderPass = VK_NULL_HANDLE;
    }
    if (m_descPool != VK_NULL_HANDLE) {
        vkDestroyDescriptorPool(m_device, m_descPool, nullptr);
        m_descPool = VK_NULL_HANDLE;
    }
    if (m_descLayout != VK_NULL_HANDLE) {
        vkDestroyDescriptorSetLayout(m_device, m_descLayout, nullptr);
        m_descLayout = VK_NULL_HANDLE;
    }
    if (m_sampler != VK_NULL_HANDLE) {
        vkDestroySampler(m_device, m_sampler, nullptr);
        m_sampler = VK_NULL_HANDLE;
    }
    if (m_device != VK_NULL_HANDLE) {
        vkDestroyDevice(m_device, nullptr);
        m_device = VK_NULL_HANDLE;
    }
    if (m_vkSurface != VK_NULL_HANDLE) {
        vkDestroySurfaceKHR(m_instance, m_vkSurface, nullptr);
        m_vkSurface = VK_NULL_HANDLE;
    }
    if (m_instance != VK_NULL_HANDLE) {
        vkDestroyInstance(m_instance, nullptr);
        m_instance = VK_NULL_HANDLE;
    }
    m_swapchainDirty = false;
}

bool VulkanContext::initInstance(bool withSurface) {
    VkApplicationInfo appInfo = {
        .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
        .pApplicationName = "layrics",
        .applicationVersion = 1,
        .pEngineName = "none",
        .engineVersion = 1,
        .apiVersion = VK_API_VERSION_1_0,
    };
    const char *exts[2];
    uint32_t extCount = 0;
    if (withSurface) {
        exts[extCount++] = VK_KHR_SURFACE_EXTENSION_NAME;
        exts[extCount++] = VK_KHR_WAYLAND_SURFACE_EXTENSION_NAME;
    }
    VkInstanceCreateInfo ici = {
        .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        .pApplicationInfo = &appInfo,
        .enabledExtensionCount = extCount,
        .ppEnabledExtensionNames = extCount ? exts : nullptr,
    };
    if (vkCreateInstance(&ici, nullptr, &m_instance) != VK_SUCCESS) {
        LAY_ERR("vkCreateInstance failed");
        return false;
    }

    if (withSurface) {
        VkWaylandSurfaceCreateInfoKHR wsi = {
            .sType = VK_STRUCTURE_TYPE_WAYLAND_SURFACE_CREATE_INFO_KHR,
            .display = m_display,
            .surface = m_wlSurface,
        };
        if (vkCreateWaylandSurfaceKHR(m_instance, &wsi, nullptr,
                                      &m_vkSurface) != VK_SUCCESS) {
            LAY_ERR("vkCreateWaylandSurfaceKHR failed");
            return false;
        }
    }
    return true;
}

bool VulkanContext::pickPhysicalDevice() {
    uint32_t count = 0;
    vkEnumeratePhysicalDevices(m_instance, &count, nullptr);
    if (!count) {
        LAY_ERR("no Vulkan physical device");
        return false;
    }
    std::vector<VkPhysicalDevice> devices(count);
    vkEnumeratePhysicalDevices(m_instance, &count, devices.data());
    m_phys = devices[0];
    VkPhysicalDeviceProperties props;
    vkGetPhysicalDeviceProperties(m_phys, &props);
    LAY_LOG("Vulkan GPU: %s", props.deviceName);
    return true;
}

bool VulkanContext::pickQueueFamily(bool needPresent) {
    uint32_t count = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(m_phys, &count, nullptr);
    std::vector<VkQueueFamilyProperties> props(count);
    vkGetPhysicalDeviceQueueFamilyProperties(m_phys, &count, props.data());
    for (uint32_t i = 0; i < count; i++) {
        if (!(props[i].queueFlags & VK_QUEUE_GRAPHICS_BIT)) {
            continue;
        }
        if (needPresent) {
            VkBool32 present = VK_FALSE;
            vkGetPhysicalDeviceSurfaceSupportKHR(m_phys, i, m_vkSurface,
                                                 &present);
            if (!present) {
                continue;
            }
        }
        m_queueFamily = i;
        return true;
    }
    if (needPresent) {
        LAY_ERR("no queue family with graphics+present");
    } else {
        LAY_ERR("no graphics queue family");
    }
    return false;
}

bool VulkanContext::createDevice() {
    if (!pickQueueFamily(!m_offscreen)) {
        return false;
    }
    const float priority = 1.0f;
    VkDeviceQueueCreateInfo dqci = {
        .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
        .queueFamilyIndex = m_queueFamily,
        .queueCount = 1,
        .pQueuePriorities = &priority,
    };
    const char *devExts[2];
    uint32_t devExtCount = 0;
    devExts[devExtCount++] = VK_KHR_SWAPCHAIN_EXTENSION_NAME;
    // Optional: without it the compositor gets full-surface damage (still
    // correct, just costlier).
    bool hasIncrementalPresent = false;
    uint32_t extCount = 0;
    vkEnumerateDeviceExtensionProperties(m_phys, nullptr, &extCount, nullptr);
    std::vector<VkExtensionProperties> exts(extCount);
    vkEnumerateDeviceExtensionProperties(m_phys, nullptr, &extCount,
                                         exts.data());
    for (const auto &e : exts) {
        if (std::strcmp(e.extensionName,
                        VK_KHR_INCREMENTAL_PRESENT_EXTENSION_NAME) == 0) {
            hasIncrementalPresent = true;
            break;
        }
    }
    if (hasIncrementalPresent) {
        devExts[devExtCount++] = VK_KHR_INCREMENTAL_PRESENT_EXTENSION_NAME;
    }
    VkDeviceCreateInfo dci = {
        .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
        .queueCreateInfoCount = 1,
        .pQueueCreateInfos = &dqci,
        .enabledExtensionCount = m_offscreen ? 0u : devExtCount,
        .ppEnabledExtensionNames = m_offscreen ? nullptr : devExts,
    };
    if (vkCreateDevice(m_phys, &dci, nullptr, &m_device) != VK_SUCCESS) {
        LAY_ERR("vkCreateDevice failed");
        return false;
    }
    vkGetDeviceQueue(m_device, m_queueFamily, 0, &m_queue);
    return true;
}

// ---------------------------------------------------------------------------
// Swapchain
// ---------------------------------------------------------------------------

bool VulkanContext::pickSurfaceFormat() {
    m_format = VK_FORMAT_UNDEFINED;
    uint32_t fmtCount = 0;
    vkGetPhysicalDeviceSurfaceFormatsKHR(m_phys, m_vkSurface, &fmtCount,
                                         nullptr);
    std::vector<VkSurfaceFormatKHR> fmts(fmtCount);
    vkGetPhysicalDeviceSurfaceFormatsKHR(m_phys, m_vkSurface, &fmtCount,
                                         fmts.data());
    for (const auto &f : fmts) {
        if (f.format == VK_FORMAT_B8G8R8A8_UNORM ||
            f.format == VK_FORMAT_R8G8B8A8_UNORM) {
            m_format = f.format;
            break;
        }
    }
    if (m_format == VK_FORMAT_UNDEFINED && !fmts.empty()) {
        m_format = fmts[0].format;
    }
    if (m_format == VK_FORMAT_UNDEFINED) {
        m_format = VK_FORMAT_B8G8R8A8_UNORM;
    }
    return true;
}

bool VulkanContext::createSwapchain() {
    VkSurfaceCapabilitiesKHR caps;
    vkGetPhysicalDeviceSurfaceCapabilitiesKHR(m_phys, m_vkSurface, &caps);

    uint32_t imageCount = caps.minImageCount + 1;
    if (caps.maxImageCount > 0 && imageCount > caps.maxImageCount) {
        imageCount = caps.maxImageCount;
    }

    if (caps.supportedCompositeAlpha &
        VK_COMPOSITE_ALPHA_PRE_MULTIPLIED_BIT_KHR) {
        m_compositeAlpha = VK_COMPOSITE_ALPHA_PRE_MULTIPLIED_BIT_KHR;
    } else if (caps.supportedCompositeAlpha &
               VK_COMPOSITE_ALPHA_POST_MULTIPLIED_BIT_KHR) {
        m_compositeAlpha = VK_COMPOSITE_ALPHA_POST_MULTIPLIED_BIT_KHR;
    } else {
        m_compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
    }

    if (caps.currentExtent.width != 0xFFFFFFFFu) {
        m_extent = caps.currentExtent;
    } else {
        m_extent.width = static_cast<uint32_t>(m_requestedWidth);
        m_extent.height = static_cast<uint32_t>(m_requestedHeight);
    }

    VkPresentModeKHR presentMode = VK_PRESENT_MODE_FIFO_KHR;
    uint32_t modeCount = 0;
    vkGetPhysicalDeviceSurfacePresentModesKHR(m_phys, m_vkSurface, &modeCount,
                                              nullptr);
    std::vector<VkPresentModeKHR> modes(modeCount);
    vkGetPhysicalDeviceSurfacePresentModesKHR(m_phys, m_vkSurface, &modeCount,
                                              modes.data());
    for (const auto &m : modes) {
        if (m == VK_PRESENT_MODE_MAILBOX_KHR) {
            presentMode = VK_PRESENT_MODE_MAILBOX_KHR;
        }
    }

    VkSwapchainCreateInfoKHR sci = {
        .sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR,
        .surface = m_vkSurface,
        .minImageCount = imageCount,
        .imageFormat = m_format,
        .imageColorSpace = VK_COLOR_SPACE_SRGB_NONLINEAR_KHR,
        .imageExtent = m_extent,
        .imageArrayLayers = 1,
        .imageUsage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT |
                      VK_IMAGE_USAGE_TRANSFER_DST_BIT,
        .imageSharingMode = VK_SHARING_MODE_EXCLUSIVE,
        .preTransform = VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR,
        .compositeAlpha = m_compositeAlpha,
        .presentMode = presentMode,
        .clipped = VK_TRUE,
    };
    if (vkCreateSwapchainKHR(m_device, &sci, nullptr, &m_swapchain) !=
        VK_SUCCESS) {
        LAY_ERR("vkCreateSwapchainKHR failed");
        return false;
    }

    uint32_t imgCount = 0;
    vkGetSwapchainImagesKHR(m_device, m_swapchain, &imgCount, nullptr);
    m_images.resize(imgCount);
    vkGetSwapchainImagesKHR(m_device, m_swapchain, &imgCount, m_images.data());

    m_views.resize(imgCount);
    m_framebuffers.resize(imgCount);
    for (uint32_t i = 0; i < imgCount; i++) {
        VkImageViewCreateInfo ivi = {
            .sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,
            .image = m_images[i],
            .viewType = VK_IMAGE_VIEW_TYPE_2D,
            .format = m_format,
            .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
        };
        if (vkCreateImageView(m_device, &ivi, nullptr, &m_views[i]) !=
            VK_SUCCESS) {
            LAY_ERR("vkCreateImageView failed");
            return false;
        }
        VkFramebufferCreateInfo fbi = {
            .sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO,
            .renderPass = m_renderPass,
            .attachmentCount = 1,
            .pAttachments = &m_views[i],
            .width = m_extent.width,
            .height = m_extent.height,
            .layers = 1,
        };
        if (vkCreateFramebuffer(m_device, &fbi, nullptr, &m_framebuffers[i]) !=
            VK_SUCCESS) {
            LAY_ERR("vkCreateFramebuffer failed");
            return false;
        }
    }

    LAY_DEBUG("swapchain: format=%d extent=%ux%u images=%u", m_format,
              m_extent.width, m_extent.height, imgCount);
    m_swapchainDirty = false;
    return true;
}

void VulkanContext::destroySwapchain() {
    if (m_device == VK_NULL_HANDLE) {
        return;
    }
    for (auto fb : m_framebuffers) {
        if (fb) {
            vkDestroyFramebuffer(m_device, fb, nullptr);
        }
    }
    m_framebuffers.clear();
    for (auto v : m_views) {
        if (v) {
            vkDestroyImageView(m_device, v, nullptr);
        }
    }
    m_views.clear();
    m_images.clear();
    if (m_swapchain != VK_NULL_HANDLE) {
        vkDestroySwapchainKHR(m_device, m_swapchain, nullptr);
        m_swapchain = VK_NULL_HANDLE;
    }
}

void VulkanContext::resize(int width, int height) {
    m_requestedWidth = width;
    m_requestedHeight = height;
    vkDeviceWaitIdle(m_device);
    destroySwapchain();
    if (!createSwapchain()) {
        LAY_ERR("swapchain recreation failed");
        m_swapchainDirty = true;
        return;
    }
    LAY_LOG("swapchain recreated: %ux%u", m_extent.width, m_extent.height);
}

// ---------------------------------------------------------------------------
// Render pass / pipeline
// ---------------------------------------------------------------------------

bool VulkanContext::createRenderPass(VkImageLayout finalLayout) {
    (void)finalLayout;
    // m_format is set by the caller: surface format (windowed) or
    // R8G8B8A8_UNORM (offscreen).

    VkAttachmentDescription att = {
        .format = m_format,
        .samples = VK_SAMPLE_COUNT_1_BIT,
        .loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR,
        .storeOp = VK_ATTACHMENT_STORE_OP_STORE,
        .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
        .finalLayout = finalLayout,
    };
    VkAttachmentReference attRef = {
        .attachment = 0,
        .layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
    };
    VkSubpassDescription subpass = {
        .pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS,
        .colorAttachmentCount = 1,
        .pColorAttachments = &attRef,
    };
    VkRenderPassCreateInfo rpci = {
        .sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO,
        .attachmentCount = 1,
        .pAttachments = &att,
        .subpassCount = 1,
        .pSubpasses = &subpass,
    };
    if (vkCreateRenderPass(m_device, &rpci, nullptr, &m_renderPass) !=
        VK_SUCCESS) {
        LAY_ERR("vkCreateRenderPass failed");
        return false;
    }

    VkDescriptorSetLayoutBinding binding = {
        .binding = 0,
        .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
        .descriptorCount = 1,
        .stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT,
    };
    VkDescriptorSetLayoutCreateInfo dlci = {
        .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
        .bindingCount = 1,
        .pBindings = &binding,
    };
    if (vkCreateDescriptorSetLayout(m_device, &dlci, nullptr, &m_descLayout) !=
        VK_SUCCESS) {
        LAY_ERR("vkCreateDescriptorSetLayout failed");
        return false;
    }

    VkDescriptorPoolSize poolSize = {
        .type = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
        .descriptorCount = 2048,
    };
    VkDescriptorPoolCreateInfo dpci = {
        .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,
        .maxSets = 2048,
        .poolSizeCount = 1,
        .pPoolSizes = &poolSize,
    };
    if (vkCreateDescriptorPool(m_device, &dpci, nullptr, &m_descPool) !=
        VK_SUCCESS) {
        LAY_ERR("vkCreateDescriptorPool failed");
        return false;
    }

    VkSamplerCreateInfo sci = {
        .sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO,
        .magFilter = VK_FILTER_LINEAR,
        .minFilter = VK_FILTER_LINEAR,
        .mipmapMode = VK_SAMPLER_MIPMAP_MODE_NEAREST,
        .addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
        .addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
        .addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
    };
    if (vkCreateSampler(m_device, &sci, nullptr, &m_sampler) != VK_SUCCESS) {
        LAY_ERR("vkCreateSampler failed");
        return false;
    }
    return true;
}

bool VulkanContext::createPipeline() {
    // glslc -mfmt=c emits a bare initializer list; declare the array here.
    static const uint32_t subtitle_vert[] =
#include "subtitle_vert.inc"
        ;
    static const uint32_t subtitle_frag[] =
#include "subtitle_frag.inc"
        ;
    VkShaderModuleCreateInfo vci = {
        .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
        .codeSize = sizeof(subtitle_vert),
        .pCode = subtitle_vert,
    };
    if (vkCreateShaderModule(m_device, &vci, nullptr, &m_vertModule) !=
        VK_SUCCESS) {
        LAY_ERR("failed to create vertex shader module");
        return false;
    }
    VkShaderModuleCreateInfo fci = {
        .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
        .codeSize = sizeof(subtitle_frag),
        .pCode = subtitle_frag,
    };
    if (vkCreateShaderModule(m_device, &fci, nullptr, &m_fragModule) !=
        VK_SUCCESS) {
        LAY_ERR("failed to create fragment shader module");
        return false;
    }

    VkPipelineShaderStageCreateInfo stages[2] = {
        {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
         .stage = VK_SHADER_STAGE_VERTEX_BIT,
         .module = m_vertModule,
         .pName = "main"},
        {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
         .stage = VK_SHADER_STAGE_FRAGMENT_BIT,
         .module = m_fragModule,
         .pName = "main"},
    };

    VkVertexInputBindingDescription binding = {
        .binding = 0,
        .stride = 8 * sizeof(float), /* pos(2) uv(2) color(4) */
        .inputRate = VK_VERTEX_INPUT_RATE_VERTEX,
    };
    VkVertexInputAttributeDescription attrs[3] = {
        {.location = 0,
         .binding = 0,
         .format = VK_FORMAT_R32G32_SFLOAT,
         .offset = 0},
        {.location = 1,
         .binding = 0,
         .format = VK_FORMAT_R32G32_SFLOAT,
         .offset = 2 * sizeof(float)},
        {.location = 2,
         .binding = 0,
         .format = VK_FORMAT_R32G32B32A32_SFLOAT,
         .offset = 4 * sizeof(float)},
    };
    VkPipelineVertexInputStateCreateInfo vertexInput = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO,
        .vertexBindingDescriptionCount = 1,
        .pVertexBindingDescriptions = &binding,
        .vertexAttributeDescriptionCount = 3,
        .pVertexAttributeDescriptions = attrs,
    };
    VkPipelineInputAssemblyStateCreateInfo ia = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO,
        // 4 vertices per quad: TRIANGLE_STRIP yields both triangles;
        // TRIANGLE_LIST would draw only one.
        .topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP,
    };
    VkPipelineViewportStateCreateInfo vs = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO,
        .viewportCount = 1,
        .scissorCount = 1,
    };
    VkDynamicState dynStates[] = {VK_DYNAMIC_STATE_VIEWPORT,
                                  VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo dyn = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO,
        .dynamicStateCount = 2,
        .pDynamicStates = dynStates,
    };
    VkPipelineRasterizationStateCreateInfo rs = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO,
        .polygonMode = VK_POLYGON_MODE_FILL,
        .cullMode = VK_CULL_MODE_NONE,
        .frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE,
        .lineWidth = 1.0f,
    };
    VkPipelineMultisampleStateCreateInfo ms = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO,
        .rasterizationSamples = VK_SAMPLE_COUNT_1_BIT,
    };
    VkPipelineColorBlendAttachmentState blend = {
        // Premultiplied alpha: subtitles are premultiplied in the shader.
        .blendEnable = VK_TRUE,
        .srcColorBlendFactor = VK_BLEND_FACTOR_ONE,
        .dstColorBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA,
        .colorBlendOp = VK_BLEND_OP_ADD,
        .srcAlphaBlendFactor = VK_BLEND_FACTOR_ONE,
        .dstAlphaBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA,
        .alphaBlendOp = VK_BLEND_OP_ADD,
        .colorWriteMask = 0xF,
    };
    VkPipelineColorBlendStateCreateInfo cb = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,
        .attachmentCount = 1,
        .pAttachments = &blend,
    };
    VkPushConstantRange pushRange = {
        .stageFlags = VK_SHADER_STAGE_VERTEX_BIT,
        .offset = 0,
        .size = 4 * sizeof(float), /* offset(2) + screen(2) */
    };
    VkPipelineLayoutCreateInfo plci = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
        .setLayoutCount = 1,
        .pSetLayouts = &m_descLayout,
        .pushConstantRangeCount = 1,
        .pPushConstantRanges = &pushRange,
    };
    if (vkCreatePipelineLayout(m_device, &plci, nullptr, &m_pipelineLayout) !=
        VK_SUCCESS) {
        LAY_ERR("vkCreatePipelineLayout failed");
        return false;
    }

    VkGraphicsPipelineCreateInfo gpci = {
        .sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO,
        .stageCount = 2,
        .pStages = stages,
        .pVertexInputState = &vertexInput,
        .pInputAssemblyState = &ia,
        .pViewportState = &vs,
        .pRasterizationState = &rs,
        .pMultisampleState = &ms,
        .pColorBlendState = &cb,
        .pDynamicState = &dyn,
        .layout = m_pipelineLayout,
        .renderPass = m_renderPass,
        .subpass = 0,
    };
    if (vkCreateGraphicsPipelines(m_device, VK_NULL_HANDLE, 1, &gpci, nullptr,
                                  &m_pipeline) != VK_SUCCESS) {
        LAY_ERR("vkCreateGraphicsPipelines failed");
        return false;
    }
    return true;
}

// ---------------------------------------------------------------------------
// Sync
// ---------------------------------------------------------------------------

bool VulkanContext::createSyncObjects() {
    VkCommandPoolCreateInfo cpci = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
        .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,
        .queueFamilyIndex = m_queueFamily,
    };
    if (vkCreateCommandPool(m_device, &cpci, nullptr, &m_cmdPool) !=
        VK_SUCCESS) {
        LAY_ERR("vkCreateCommandPool failed");
        return false;
    }
    VkCommandBufferAllocateInfo cbai = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
        .commandPool = m_cmdPool,
        .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
        .commandBufferCount = 1,
    };
    if (vkAllocateCommandBuffers(m_device, &cbai, &m_cmd) != VK_SUCCESS) {
        LAY_ERR("vkAllocateCommandBuffers failed");
        return false;
    }
    VkSemaphoreCreateInfo sci = {
        .sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO,
    };
    for (uint32_t i = 0; i < kFramesInFlight; i++) {
        if (vkCreateSemaphore(m_device, &sci, nullptr, &m_acquireSems[i]) !=
                VK_SUCCESS ||
            vkCreateSemaphore(m_device, &sci, nullptr, &m_renderSems[i]) !=
                VK_SUCCESS) {
            LAY_ERR("vkCreateSemaphore failed");
            return false;
        }
    }
    VkFenceCreateInfo fci = {
        .sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO,
        .flags = VK_FENCE_CREATE_SIGNALED_BIT,
    };
    if (vkCreateFence(m_device, &fci, nullptr, &m_fence) != VK_SUCCESS) {
        LAY_ERR("vkCreateFence failed");
        return false;
    }
    return true;
}

// ---------------------------------------------------------------------------
// Frame flow
// ---------------------------------------------------------------------------

bool VulkanContext::beginFrame() {
    if (!ready()) {
        m_swapchainDirty = true;
        return false;
    }

    vkWaitForFences(m_device, 1, &m_fence, VK_TRUE, UINT64_MAX);
    vkResetFences(m_device, 1, &m_fence);

    // Fence wait: frames older than kFramesInFlight are complete, so their
    // staging buffers can be freed.
    reclaimFrameResources();

    // Bounded acquire: an UINT64_MAX wait would wedge the render thread when
    // the compositor stops consuming images (locked screen, suspended output).
    VkResult r =
        vkAcquireNextImageKHR(m_device, m_swapchain, 100'000'000 /* 100ms */,
                              m_acquireSems[m_frameIndex % kFramesInFlight],
                              VK_NULL_HANDLE, &m_imageIndex);
    if (r == VK_ERROR_OUT_OF_DATE_KHR || r == VK_SUBOPTIMAL_KHR) {
        m_swapchainDirty = true;
        return false;
    }
    if (r == VK_TIMEOUT) {
        // No image available: bail so the main loop can poll for stop.
        return false;
    }
    m_frameIndex++;

    VkCommandBufferBeginInfo begin = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
    };
    if (vkBeginCommandBuffer(m_cmd, &begin) != VK_SUCCESS) {
        LAY_ERR("vkBeginCommandBuffer failed");
        return false;
    }
    return true;
}

void VulkanContext::beginRenderPass() {
    VkClearValue clear = {
        .color = {{0.0f, 0.0f, 0.0f, 0.0f}}, // transparent
    };
    VkRenderPassBeginInfo rpbi = {
        .sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,
        .renderPass = m_renderPass,
        .framebuffer =
            m_offscreen ? m_offFramebuffer : m_framebuffers[m_imageIndex],
        .renderArea = {{0, 0}, m_extent},
        .clearValueCount = 1,
        .pClearValues = &clear,
    };
    vkCmdBeginRenderPass(m_cmd, &rpbi, VK_SUBPASS_CONTENTS_INLINE);

    VkViewport viewport = {
        .x = 0,
        .y = 0,
        .width = static_cast<float>(m_extent.width),
        .height = static_cast<float>(m_extent.height),
        .minDepth = 0.0f,
        .maxDepth = 1.0f,
    };
    vkCmdSetViewport(m_cmd, 0, 1, &viewport);
    VkRect2D scissor = {{0, 0}, m_extent};
    vkCmdSetScissor(m_cmd, 0, 1, &scissor);
}

void VulkanContext::endFrame(const std::vector<RenderRect> &damage) {
    vkCmdEndRenderPass(m_cmd);
    if (vkEndCommandBuffer(m_cmd) != VK_SUCCESS) {
        LAY_ERR("vkEndCommandBuffer failed");
        return;
    }

    uint32_t f = (m_frameIndex - 1) % kFramesInFlight;
    VkPipelineStageFlags waitStage =
        VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    VkSubmitInfo submit = {
        .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
        .waitSemaphoreCount = 1,
        .pWaitSemaphores = &m_acquireSems[f],
        .pWaitDstStageMask = &waitStage,
        .commandBufferCount = 1,
        .pCommandBuffers = &m_cmd,
        .signalSemaphoreCount = 1,
        .pSignalSemaphores = &m_renderSems[f],
    };
    if (vkQueueSubmit(m_queue, 1, &submit, m_fence) != VK_SUCCESS) {
        LAY_ERR("vkQueueSubmit failed");
        return;
    }

    // VK_KHR_incremental_present: re-composite only the changed regions
    // (current+previous grid cells; empty = full surface).
    std::vector<VkRectLayerKHR> rects;
    rects.reserve(damage.size());
    const int32_t w = static_cast<int32_t>(m_extent.width);
    const int32_t h = static_cast<int32_t>(m_extent.height);
    for (const auto &r : damage) {
        int32_t x0 = std::max(r.x, 0);
        int32_t y0 = std::max(r.y, 0);
        int32_t x1 = std::min(r.x + r.w, w);
        int32_t y1 = std::min(r.y + r.h, h);
        if (x1 > x0 && y1 > y0) {
            rects.push_back(VkRectLayerKHR{{x0, y0},
                                           {static_cast<uint32_t>(x1 - x0),
                                            static_cast<uint32_t>(y1 - y0)},
                                           0});
        }
    }
    VkPresentRegionKHR region = {};
    VkPresentRegionsKHR regions = {};
    VkPresentInfoKHR present = {
        .sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR,
        .waitSemaphoreCount = 1,
        .pWaitSemaphores = &m_renderSems[f],
        .swapchainCount = 1,
        .pSwapchains = &m_swapchain,
        .pImageIndices = &m_imageIndex,
    };
    if (!rects.empty()) {
        region.rectangleCount = static_cast<uint32_t>(rects.size());
        region.pRectangles = rects.data();
        regions.sType = VK_STRUCTURE_TYPE_PRESENT_REGIONS_KHR;
        regions.swapchainCount = 1;
        regions.pRegions = &region;
        present.pNext = &regions;
    }
    VkResult r = vkQueuePresentKHR(m_queue, &present);
    if (r == VK_ERROR_OUT_OF_DATE_KHR || r == VK_SUBOPTIMAL_KHR) {
        m_swapchainDirty = true;
    }
}

void VulkanContext::presentTransparent() {
    if (!beginFrame()) {
        return;
    }
    beginRenderPass();
    endFrame();
}

// ---------------------------------------------------------------------------
// Offscreen (headless) rendering
// ---------------------------------------------------------------------------

bool VulkanContext::createOffscreenTarget(int width, int height) {
    VkImageCreateInfo ici = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
        .imageType = VK_IMAGE_TYPE_2D,
        .format = m_format,
        .extent = {static_cast<uint32_t>(width), static_cast<uint32_t>(height),
                   1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT |
                 VK_IMAGE_USAGE_TRANSFER_SRC_BIT,
        .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
    };
    if (vkCreateImage(m_device, &ici, nullptr, &m_offImage) != VK_SUCCESS) {
        LAY_ERR("vkCreateImage (offscreen) failed");
        return false;
    }
    VkMemoryRequirements req;
    vkGetImageMemoryRequirements(m_device, m_offImage, &req);
    VkPhysicalDeviceMemoryProperties props;
    vkGetPhysicalDeviceMemoryProperties(m_phys, &props);
    uint32_t memIndex = 0;
    bool found = false;
    for (uint32_t i = 0; i < props.memoryTypeCount; i++) {
        if ((req.memoryTypeBits & (1u << i)) &&
            (props.memoryTypes[i].propertyFlags &
             VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)) {
            memIndex = i;
            found = true;
            break;
        }
    }
    if (!found) {
        LAY_ERR("no device-local memory for offscreen image");
        return false;
    }
    VkMemoryAllocateInfo mai = {
        .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
        .allocationSize = req.size,
        .memoryTypeIndex = memIndex,
    };
    if (vkAllocateMemory(m_device, &mai, nullptr, &m_offMemory) != VK_SUCCESS ||
        vkBindImageMemory(m_device, m_offImage, m_offMemory, 0) != VK_SUCCESS) {
        LAY_ERR("offscreen image memory failed");
        return false;
    }
    VkImageViewCreateInfo ivci = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,
        .image = m_offImage,
        .viewType = VK_IMAGE_VIEW_TYPE_2D,
        .format = m_format,
        .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
    };
    if (vkCreateImageView(m_device, &ivci, nullptr, &m_offView) != VK_SUCCESS) {
        LAY_ERR("offscreen image view failed");
        return false;
    }
    VkFramebufferCreateInfo fbci = {
        .sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO,
        .renderPass = m_renderPass,
        .attachmentCount = 1,
        .pAttachments = &m_offView,
        .width = static_cast<uint32_t>(width),
        .height = static_cast<uint32_t>(height),
        .layers = 1,
    };
    if (vkCreateFramebuffer(m_device, &fbci, nullptr, &m_offFramebuffer) !=
        VK_SUCCESS) {
        LAY_ERR("offscreen framebuffer failed");
        return false;
    }

    VkBufferCreateInfo bci = {
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = static_cast<VkDeviceSize>(width) * height * 4,
        .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
    };
    if (vkCreateBuffer(m_device, &bci, nullptr, &m_offStaging) != VK_SUCCESS) {
        LAY_ERR("offscreen staging buffer failed");
        return false;
    }
    vkGetBufferMemoryRequirements(m_device, m_offStaging, &req);
    uint32_t stagingIndex = 0;
    if (!wantHostVisibleMemory(m_phys, req, stagingIndex)) {
        LAY_ERR("no host-visible memory for offscreen staging");
        return false;
    }
    mai.allocationSize = req.size;
    mai.memoryTypeIndex = stagingIndex;
    if (vkAllocateMemory(m_device, &mai, nullptr, &m_offStagingMemory) !=
            VK_SUCCESS ||
        vkBindBufferMemory(m_device, m_offStaging, m_offStagingMemory, 0) !=
            VK_SUCCESS) {
        LAY_ERR("offscreen staging memory failed");
        return false;
    }
    vkMapMemory(m_device, m_offStagingMemory, 0, VK_WHOLE_SIZE, 0,
                &m_offStagingMapped);
    return true;
}

void VulkanContext::destroyOffscreenTarget() {
    if (m_device == VK_NULL_HANDLE) {
        return;
    }
    if (m_offFramebuffer != VK_NULL_HANDLE) {
        vkDestroyFramebuffer(m_device, m_offFramebuffer, nullptr);
        m_offFramebuffer = VK_NULL_HANDLE;
    }
    if (m_offView != VK_NULL_HANDLE) {
        vkDestroyImageView(m_device, m_offView, nullptr);
        m_offView = VK_NULL_HANDLE;
    }
    if (m_offImage != VK_NULL_HANDLE) {
        vkDestroyImage(m_device, m_offImage, nullptr);
        m_offImage = VK_NULL_HANDLE;
    }
    if (m_offStaging != VK_NULL_HANDLE) {
        vkDestroyBuffer(m_device, m_offStaging, nullptr);
        m_offStaging = VK_NULL_HANDLE;
    }
    if (m_offStagingMapped) {
        vkUnmapMemory(m_device, m_offStagingMemory);
        m_offStagingMapped = nullptr;
    }
    if (m_offMemory != VK_NULL_HANDLE) {
        vkFreeMemory(m_device, m_offMemory, nullptr);
        m_offMemory = VK_NULL_HANDLE;
    }
    if (m_offStagingMemory != VK_NULL_HANDLE) {
        vkFreeMemory(m_device, m_offStagingMemory, nullptr);
        m_offStagingMemory = VK_NULL_HANDLE;
    }
}

bool VulkanContext::beginOffscreenFrame() {
    if (vkResetCommandBuffer(m_cmd, 0) != VK_SUCCESS) {
        LAY_ERR("vkResetCommandBuffer failed");
        return false;
    }
    VkCommandBufferBeginInfo begin = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
    };
    if (vkBeginCommandBuffer(m_cmd, &begin) != VK_SUCCESS) {
        LAY_ERR("vkBeginCommandBuffer failed");
        return false;
    }
    return true;
}

void VulkanContext::endOffscreenFrame() {
    vkCmdEndRenderPass(m_cmd);

    // Make the color writes visible to the transfer and copy the rendered
    // image into the host-visible staging buffer.
    VkImageMemoryBarrier barrier = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
        .srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT,
        .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
        .oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
        .newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .image = m_offImage,
        .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
    };
    vkCmdPipelineBarrier(m_cmd, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
                         VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0,
                         nullptr, 1, &barrier);
    VkBufferImageCopy region = {
        .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
        .imageExtent = {m_extent.width, m_extent.height, 1},
    };
    vkCmdCopyImageToBuffer(m_cmd, m_offImage,
                           VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, m_offStaging,
                           1, &region);

    if (vkEndCommandBuffer(m_cmd) != VK_SUCCESS) {
        LAY_ERR("vkEndCommandBuffer failed");
        return;
    }
    VkSubmitInfo submit = {
        .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
        .commandBufferCount = 1,
        .pCommandBuffers = &m_cmd,
    };
    if (vkQueueSubmit(m_queue, 1, &submit, m_fence) != VK_SUCCESS) {
        LAY_ERR("vkQueueSubmit failed");
        return;
    }
    vkWaitForFences(m_device, 1, &m_fence, VK_TRUE, UINT64_MAX);
    vkResetFences(m_device, 1, &m_fence);
}

std::vector<uint8_t> VulkanContext::readbackOffscreen() {
    std::vector<uint8_t> pixels(static_cast<size_t>(m_extent.width) *
                                m_extent.height * 4);
    if (m_offscreen && m_offStagingMapped) {
        memcpy(pixels.data(), m_offStagingMapped, pixels.size());
    }
    return pixels;
}

// ---------------------------------------------------------------------------
// Texture helpers
// ---------------------------------------------------------------------------

VulkanContext::Texture VulkanContext::createTexture(int width, int height) {
    Texture tex;
    VkImageCreateInfo ici = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
        .imageType = VK_IMAGE_TYPE_2D,
        .format = VK_FORMAT_R8_UNORM,
        .extent = {static_cast<uint32_t>(width), static_cast<uint32_t>(height),
                   1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
        .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
        .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
    };
    if (vkCreateImage(m_device, &ici, nullptr, &tex.image) != VK_SUCCESS) {
        LAY_ERR("vkCreateImage failed");
        return tex;
    }
    VkMemoryRequirements req;
    vkGetImageMemoryRequirements(m_device, tex.image, &req);
    uint32_t memIndex = 0;
    if (!wantHostVisibleMemory(m_phys, req, memIndex)) {
        // Images use device-local memory; fall back to any compatible type.
        VkPhysicalDeviceMemoryProperties props;
        vkGetPhysicalDeviceMemoryProperties(m_phys, &props);
        for (uint32_t i = 0; i < props.memoryTypeCount; i++) {
            if (req.memoryTypeBits & (1u << i)) {
                memIndex = i;
                break;
            }
        }
    }
    VkMemoryAllocateInfo mai = {
        .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
        .allocationSize = req.size,
        .memoryTypeIndex = memIndex,
    };
    if (vkAllocateMemory(m_device, &mai, nullptr, &tex.memory) != VK_SUCCESS ||
        vkBindImageMemory(m_device, tex.image, tex.memory, 0) != VK_SUCCESS) {
        LAY_ERR("image memory allocation failed");
        destroyTexture(tex);
        return {};
    }
    VkImageViewCreateInfo ivi = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,
        .image = tex.image,
        .viewType = VK_IMAGE_VIEW_TYPE_2D,
        .format = VK_FORMAT_R8_UNORM,
        .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
    };
    if (vkCreateImageView(m_device, &ivi, nullptr, &tex.view) != VK_SUCCESS) {
        destroyTexture(tex);
        return {};
    }
    VkDescriptorSetAllocateInfo dai = {
        .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
        .descriptorPool = m_descPool,
        .descriptorSetCount = 1,
        .pSetLayouts = &m_descLayout,
    };
    if (vkAllocateDescriptorSets(m_device, &dai, &tex.set) != VK_SUCCESS) {
        LAY_ERR("vkAllocateDescriptorSets failed");
        destroyTexture(tex);
        return {};
    }
    VkDescriptorImageInfo dii = {
        .sampler = m_sampler,
        .imageView = tex.view,
        .imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
    };
    VkWriteDescriptorSet wds = {
        .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
        .dstSet = tex.set,
        .dstBinding = 0,
        .descriptorCount = 1,
        .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
        .pImageInfo = &dii,
    };
    vkUpdateDescriptorSets(m_device, 1, &wds, 0, nullptr);
    return tex;
}

void VulkanContext::resetTexturePool() {
    if (m_descPool != VK_NULL_HANDLE) {
        vkResetDescriptorPool(m_device, m_descPool, 0);
    }
}

void VulkanContext::destroyTexture(Texture &tex) {
    if (m_device == VK_NULL_HANDLE) {
        return;
    }
    if (tex.set) {
        vkFreeDescriptorSets(m_device, m_descPool, 1, &tex.set);
        tex.set = VK_NULL_HANDLE;
    }
    if (tex.view) {
        vkDestroyImageView(m_device, tex.view, nullptr);
        tex.view = VK_NULL_HANDLE;
    }
    if (tex.image) {
        vkDestroyImage(m_device, tex.image, nullptr);
        tex.image = VK_NULL_HANDLE;
    }
    if (tex.memory) {
        vkFreeMemory(m_device, tex.memory, nullptr);
        tex.memory = VK_NULL_HANDLE;
    }
    tex.uploaded = false;
}

void VulkanContext::recordUploadTexture(VkCommandBuffer cmd, Texture &tex,
                                        int width, int height,
                                        const void *pixels, size_t stride) {
    VkDeviceSize size = static_cast<VkDeviceSize>(width) * height;
    VkBufferCreateInfo bci = {
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size,
        .usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
        .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
    };
    VkBuffer staging = VK_NULL_HANDLE;
    VkDeviceMemory stagingMem = VK_NULL_HANDLE;
    if (vkCreateBuffer(m_device, &bci, nullptr, &staging) != VK_SUCCESS) {
        LAY_ERR("vkCreateBuffer failed");
        return;
    }
    VkMemoryRequirements req;
    vkGetBufferMemoryRequirements(m_device, staging, &req);
    uint32_t memIndex = 0;
    if (!wantHostVisibleMemory(m_phys, req, memIndex)) {
        LAY_ERR("no host-visible memory for staging");
        vkDestroyBuffer(m_device, staging, nullptr);
        return;
    }
    VkMemoryAllocateInfo mai = {
        .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
        .allocationSize = req.size,
        .memoryTypeIndex = memIndex,
    };
    if (vkAllocateMemory(m_device, &mai, nullptr, &stagingMem) != VK_SUCCESS ||
        vkBindBufferMemory(m_device, staging, stagingMem, 0) != VK_SUCCESS) {
        LAY_ERR("staging memory allocation failed");
        vkDestroyBuffer(m_device, staging, nullptr);
        if (stagingMem) {
            vkFreeMemory(m_device, stagingMem, nullptr);
        }
        return;
    }
    void *mapped = nullptr;
    vkMapMemory(m_device, stagingMem, 0, size, 0, &mapped);
    const uint8_t *src = static_cast<const uint8_t *>(pixels);
    if (stride == static_cast<size_t>(width)) {
        memcpy(mapped, src, size);
    } else {
        uint8_t *dst = static_cast<uint8_t *>(mapped);
        for (int y = 0; y < height; y++) {
            memcpy(dst + y * width, src + y * stride,
                   static_cast<size_t>(width));
        }
    }
    vkUnmapMemory(m_device, stagingMem);

    // Layout transition into TRANSFER_DST (first upload) or from
    // SHADER_READ_ONLY (content update).
    VkImageMemoryBarrier barrier = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
        .srcAccessMask =
            tex.uploaded ? VK_ACCESS_SHADER_READ_BIT : VK_ACCESS_NONE,
        .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
        .oldLayout = tex.uploaded ? VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL
                                  : VK_IMAGE_LAYOUT_UNDEFINED,
        .newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .image = tex.image,
        .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
    };
    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
                         VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0,
                         nullptr, 1, &barrier);

    VkBufferImageCopy region = {
        .bufferOffset = 0,
        .bufferRowLength = static_cast<uint32_t>(width),
        .bufferImageHeight = static_cast<uint32_t>(height),
        .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
        .imageExtent = {static_cast<uint32_t>(width),
                        static_cast<uint32_t>(height), 1},
    };
    vkCmdCopyBufferToImage(cmd, staging, tex.image,
                           VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);

    VkImageMemoryBarrier barrier2 = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
        .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
        .dstAccessMask = VK_ACCESS_SHADER_READ_BIT,
        .oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
        .newLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .image = tex.image,
        .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
    };
    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TRANSFER_BIT,
                         VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT, 0, 0, nullptr,
                         0, nullptr, 1, &barrier2);
    tex.uploaded = true;

    FrameResources &fr = m_frameResources[m_frameIndex % kFramesInFlight];
    fr.buffers.push_back(staging);
    fr.memories.push_back(stagingMem);
}

bool VulkanContext::ensureDynamicBuffer(DynamicBuffer &buf, VkDeviceSize size,
                                        VkBufferUsageFlags usage) {
    if (buf.buffer && buf.capacity >= size) {
        return true;
    }
    destroyDynamicBuffer(buf);
    VkBufferCreateInfo bci = {
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size,
        .usage = usage,
        .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
    };
    if (vkCreateBuffer(m_device, &bci, nullptr, &buf.buffer) != VK_SUCCESS) {
        LAY_ERR("vkCreateBuffer failed");
        return false;
    }
    VkMemoryRequirements req;
    vkGetBufferMemoryRequirements(m_device, buf.buffer, &req);
    uint32_t memIndex = 0;
    if (!wantHostVisibleMemory(m_phys, req, memIndex)) {
        LAY_ERR("no host-visible memory for dynamic buffer");
        destroyDynamicBuffer(buf);
        return false;
    }
    VkMemoryAllocateInfo mai = {
        .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
        .allocationSize = req.size,
        .memoryTypeIndex = memIndex,
    };
    if (vkAllocateMemory(m_device, &mai, nullptr, &buf.memory) != VK_SUCCESS ||
        vkBindBufferMemory(m_device, buf.buffer, buf.memory, 0) != VK_SUCCESS) {
        LAY_ERR("dynamic buffer memory allocation failed");
        destroyDynamicBuffer(buf);
        return false;
    }
    vkMapMemory(m_device, buf.memory, 0, size, 0, &buf.mapped);
    buf.capacity = size;
    return true;
}

void VulkanContext::destroyDynamicBuffer(DynamicBuffer &buf) {
    if (m_device == VK_NULL_HANDLE) {
        return;
    }
    if (buf.buffer) {
        vkDestroyBuffer(m_device, buf.buffer, nullptr);
        buf.buffer = VK_NULL_HANDLE;
    }
    if (buf.memory) {
        vkFreeMemory(m_device, buf.memory, nullptr);
        buf.memory = VK_NULL_HANDLE;
    }
    buf.mapped = nullptr;
    buf.capacity = 0;
}

// ---------------------------------------------------------------------------
// Resource reclamation
// ---------------------------------------------------------------------------

void VulkanContext::destroyFrameResources(FrameResources &fr) {
    for (size_t i = 0; i < fr.buffers.size(); i++) {
        vkDestroyBuffer(m_device, fr.buffers[i], nullptr);
        vkFreeMemory(m_device, fr.memories[i], nullptr);
    }
    fr.buffers.clear();
    fr.memories.clear();
}

void VulkanContext::reclaimFrameResources() {
    // Fence wait: frames older than kFramesInFlight are done, so their
    // staging buffers can be freed.
    FrameResources &fr = m_frameResources[m_frameIndex % kFramesInFlight];
    destroyFrameResources(fr);
}
