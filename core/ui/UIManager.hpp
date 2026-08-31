#pragma once

#include <vulkan/vulkan.h>

#include <cstdint>
#include <functional>
#include <string>

#include "core/types/Common.hpp"

struct ImGuiContext;
class VulkanContext;

// Owns the ImGui context and the right-click lyrics menu. The menu is drawn
// as a second pass into the overlay framebuffer (no separate popup surface).
// Single-threaded: all methods run on the render thread.
class UIManager {
  public:
    UIManager() = default;
    ~UIManager();

    UIManager(const UIManager &) = delete;
    UIManager &operator=(const UIManager &) = delete;

    bool initialize(VulkanContext &vk);
    void shutdown();

    // Called once per produced frame before the render pass; builds the menu
    // and updates the open/close state (must run before the early-return
    // checks in produceFrame/onFrame).
    void newFrame();

    // Records the imgui draw data inside the render pass (after subtitles).
    void render(VkCommandBuffer cmd);

    // True while the frame chain must stay alive for the menu: open, pending
    // open/close, or one frame after closing (to clear the menu pixels).
    bool isActive() const {
        return m_menuOpen || m_openRequested || m_closeRequested || m_needsClear;
    }
    bool isMenuOpen() const { return m_menuOpen; }
    // Popup rect in surface coordinates (no drag offset); empty when closed.
    RenderRect menuRect() const { return m_menuRect; }

    // Input (render thread, from Application callbacks).
    void onPointerMotion(double x, double y);
    void openAt(double x, double y); // right-click on the subtitle
    void onPointerButton(int button, bool pressed); // fed to imgui while open
    void requestClose(); // graceful close: processed on the next frame
    void closeNow();     // immediate close (hide/lock: no frame may follow)

    // Menu content, pushed from Python (rendered on the next frame; replaces
    // the open menu's items in place when already open).
    void setMenuItems(std::vector<UiMenuItem> items) {
        m_items = std::move(items);
    }

    void setActionCallback(std::function<void(const std::string &)> cb) {
        m_actionCb = std::move(cb);
    }

  private:
    void build();
    void renderItems(const std::vector<UiMenuItem> &items,
                     std::string &action);

    VulkanContext *m_vk = nullptr;
    bool m_initialized = false;

    bool m_menuOpen = false;
    bool m_openRequested = false;
    bool m_closeRequested = false;
    bool m_needsClear = false;
    RenderRect m_menuRect{};
    std::vector<UiMenuItem> m_items;
    std::function<void(const std::string &)> m_actionCb;

    void updateMenuRect();
};
