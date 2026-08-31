#include "core/ui/UIManager.hpp"
#include "core/renderer/VulkanContext.hpp"
#include "core/utils/Logger.hpp"

#include "imgui.h"
#include "imgui_impl_vulkan.h"
#include "imgui_internal.h" // ClosePopupToLevel

#include <linux/input-event-codes.h>
#include <vulkan/vulkan.h>

#include <algorithm>
#include <climits>
#include <unistd.h>
#include <utility>

#include <fontconfig/fontconfig.h>

UIManager::~UIManager() { shutdown(); }

bool UIManager::initialize(VulkanContext &vk) {
    shutdown();
    m_vk = &vk;

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGui::StyleColorsDark();
    ImGuiIO &io = ImGui::GetIO();
    io.IniFilename = nullptr; // do not persist layout to imgui.ini

    // Resolve a CJK-capable system font through fontconfig (sans:lang=zh)
    // instead of hard-coded paths: the ttc index is honored via FontNo, and
    // corrupt candidates fall through to the next match. The embedded
    // ProggyClean font has no CJK glyphs, so it is only a last resort; since
    // 1.92 glyphs are rasterized on demand, no glyph ranges are needed.
    FcInit();
    FcPattern *fontPat =
        FcNameParse(reinterpret_cast<const FcChar8 *>("sans:lang=zh"));
    FcConfigSubstitute(nullptr, fontPat, FcMatchPattern);
    FcDefaultSubstitute(fontPat);
    FcResult matchResult;
    FcFontSet *set =
        FcFontSort(nullptr, fontPat, FcFalse, nullptr, &matchResult);
    FcPatternDestroy(fontPat);
    bool cjkFontLoaded = false;
    if (set != nullptr) {
        for (int i = 0; i < set->nfont; i++) {
            FcChar8 *file = nullptr;
            if (FcPatternGetString(set->fonts[i], FC_FILE, 0, &file) !=
                FcResultMatch) {
                continue;
            }
            int index = 0;
            FcPatternGetInteger(set->fonts[i], FC_INDEX, 0, &index);
            ImFontConfig cfg;
            cfg.FontNo = index;
            if (io.Fonts->AddFontFromFileTTF(
                    reinterpret_cast<const char *>(file), 20.0f, &cfg) !=
                nullptr) {
                LAY_LOG("UI font: %s (index %d)", file, index);
                cjkFontLoaded = true;
                break;
            }
        }
        FcFontSetDestroy(set);
    }
    if (!cjkFontLoaded) {
        // Fallback to the embedded font; scale it for readability.
        ImGui::GetStyle().FontScaleMain = 1.4f;
        LAY_LOG("UI font: embedded (no CJK system font found)");
    }

    // Layrics local patch: imgui 1.92.9b splits texture/sampler into separate
    // descriptor types; DescriptorPoolSize > 0 makes the backend create its
    // own pool, isolated from the subtitle atlas pool in VulkanContext.
    static const uint32_t imgui_frag[] =
#include "imgui_frag.inc"
        ;
    ImGui_ImplVulkan_InitInfo info = {};
    info.ApiVersion = VK_API_VERSION_1_0;
    info.Instance = vk.instance();
    info.PhysicalDevice = vk.physicalDevice();
    info.Device = vk.device();
    info.QueueFamily = vk.queueFamily();
    info.Queue = vk.queue();
    info.DescriptorPoolSize = 8; // backend requires >= 8 sampled-image sets
    info.MinImageCount = 2;
    info.ImageCount = 2; // == kFramesInFlight; single fence, strictly serial
    info.PipelineInfoMain.RenderPass = vk.renderPass();
    // Premultiplied fragment shader (see core/renderer/shaders/imgui.frag);
    // the backend blend was patched to ONE to match it.
    info.CustomShaderFragCreateInfo = {
        .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
        .codeSize = sizeof(imgui_frag),
        .pCode = imgui_frag,
    };
    if (!ImGui_ImplVulkan_Init(&info)) {
        LAY_ERR("ImGui_ImplVulkan_Init failed");
        ImGui::DestroyContext();
        return false;
    }
    m_initialized = true;
    LAY_LOG("UI manager initialized");
    return true;
}

void UIManager::shutdown() {
    if (!m_initialized) {
        return;
    }
    ImGui_ImplVulkan_Shutdown();
    ImGui::DestroyContext();
    m_vk = nullptr;
    m_initialized = false;
    m_menuOpen = false;
    m_openRequested = false;
    m_closeRequested = false;
    m_needsClear = false;
    m_menuRect = {};
}

void UIManager::newFrame() {
    if (!isActive()) {
        return; // closed and idle: zero per-frame cost
    }
    ImGuiIO &io = ImGui::GetIO();
    io.DisplaySize =
        ImVec2(static_cast<float>(m_vk->width()),
               static_cast<float>(m_vk->height()));
    ImGui_ImplVulkan_NewFrame();
    ImGui::NewFrame();
    build();
    ImGui::Render();
    updateMenuRect();
}

void UIManager::build() {
    if (m_openRequested) {
        // ImGui positions mouse-triggered popups at the pointer and clamps
        // them to the screen (FindBestWindowPosForPopup), so no manual
        // positioning/clamping is needed.
        ImGui::OpenPopup("lyrics_menu");
        m_openRequested = false;
    }

    std::string action;
    if (ImGui::BeginPopup("lyrics_menu")) {
        if (m_closeRequested) {
            ImGui::CloseCurrentPopup();
        }
        // Content is defined on the Python side (rendered as-is, submenus
        // for items with children; disabled entries have an empty action).
        renderItems(m_items, action);
        ImGui::EndPopup();
        m_menuOpen = true;
    } else if (m_menuOpen) {
        // Popup closed (outside click / item activation / ESC / leave):
        // one more frame without the menu clears its pixels.
        m_menuOpen = false;
        m_needsClear = true;
        m_menuRect = {};
    }
    m_closeRequested = false;

    if (!action.empty() && m_actionCb) {
        m_actionCb(action);
    }
}

void UIManager::renderItems(const std::vector<UiMenuItem> &items,
                            std::string &action) {
    for (const auto &item : items) {
        if (!item.children.empty()) {
            if (ImGui::BeginMenu(item.label.c_str())) {
                renderItems(item.children, action);
                ImGui::EndMenu();
            }
        } else if (ImGui::MenuItem(item.label.c_str(), nullptr, false,
                                   !item.action.empty())) {
            if (!item.action.empty()) {
                action = item.action;
            }
        }
    }
}

// Captures the menu rect from the rendered draw data: window rect queries
// return pre-fit values on the popup's first visible frame (the popup is
// created hidden while its size is computed). The union of vertex positions
// matches the actual drawn area (clip rects can span the whole screen on
// that frame).
void UIManager::updateMenuRect() {
    if (!m_menuOpen) {
        m_menuRect = {};
        return;
    }
    const ImDrawData *dd = ImGui::GetDrawData();
    int x0 = INT_MAX, y0 = INT_MAX, x1 = 0, y1 = 0;
    bool any = false;
    for (int li = 0; li < dd->CmdListsCount; li++) {
        const ImDrawList *list = dd->CmdLists[li];
        for (int vi = 0; vi < list->VtxBuffer.Size; vi++) {
            const ImVec2 &p = list->VtxBuffer[vi].pos;
            any = true;
            x0 = std::min(x0, static_cast<int>(std::floor(p.x)));
            y0 = std::min(y0, static_cast<int>(std::floor(p.y)));
            x1 = std::max(x1, static_cast<int>(std::ceil(p.x)));
            y1 = std::max(y1, static_cast<int>(std::ceil(p.y)));
        }
    }
    m_menuRect = any ? RenderRect{x0, y0, x1 - x0, y1 - y0} : RenderRect{};
}

void UIManager::render(VkCommandBuffer cmd) {
    if (!m_menuOpen && !m_needsClear) {
        return;
    }
    ImGui_ImplVulkan_RenderDrawData(ImGui::GetDrawData(), cmd);
    m_needsClear = false;
}

void UIManager::onPointerMotion(double x, double y) {
    ImGui::GetIO().AddMousePosEvent(static_cast<float>(x),
                                    static_cast<float>(y));
}

void UIManager::openAt(double x, double y) {
    // Feed the pointer position so the popup opens exactly at the click point
    // (FindBestWindowPosForPopup positions mouse-triggered popups at the
    // pointer and clamps them to the screen).
    ImGui::GetIO().AddMousePosEvent(static_cast<float>(x),
                                    static_cast<float>(y));
    m_openRequested = true;
}

void UIManager::onPointerButton(int button, bool pressed) {
    // ImGui mouse buttons: 0 = left, 1 = right.
    int idx = (button == BTN_LEFT) ? 0 : (button == BTN_RIGHT ? 1 : -1);
    if (idx >= 0) {
        ImGui::GetIO().AddMouseButtonEvent(idx, pressed);
    }
}

void UIManager::requestClose() {
    // Cancel a pending open so a close arriving between openAt() and the next
    // frame is not dropped (build() clears m_closeRequested unconditionally).
    m_openRequested = false;
    m_closeRequested = true;
}

void UIManager::closeNow() {
    m_openRequested = false;
    m_closeRequested = false;
    m_needsClear = false;
    m_menuOpen = false;
    m_menuRect = {};
    ImGuiContext *ctx = ImGui::GetCurrentContext();
    if (ctx != nullptr && ctx->OpenPopupStack.Size > 0) {
        ImGui::ClosePopupToLevel(0, true);
    }
}
