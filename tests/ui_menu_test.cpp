// Headless UI test: initializes the imgui right-click menu on the offscreen
// Vulkan target and checks that (1) the popup renders non-transparent pixels
// through the premultiplied pipeline, and (2) the popup is clamped inside the
// screen when opened near an edge.
#include "core/renderer/VulkanContext.hpp"
#include "core/ui/UIManager.hpp"

#include <cstdint>
#include <cstdio>
#include <vector>

static int failures = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        if (!(cond)) {                                                         \
            std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__,       \
                         #cond);                                               \
            failures++;                                                        \
        }                                                                      \
    } while (0)

int main() {
    const int W = 800, H = 600;

    VulkanContext vk;
    if (!vk.initializeOffscreen(W, H)) {
        std::fprintf(stderr, "offscreen init failed\n");
        return 1;
    }

    UIManager ui;
    if (!ui.initialize(vk)) {
        std::fprintf(stderr, "ui init failed\n");
        return 1;
    }

    AppState state{};

    ui.closeNow();
    CHECK(!ui.menuOpen());

    // Menu content mirrors the Python-side tree (leaf actions + a nested
    // submenu); replaced the old hard-coded test entries.
    ui.setMenuItems({
        {"测试 1", "test_1", {}},
        {"测试 2", "test_2", {}},
        {"播放器", "", {{"播放器 A", "player:A"}, {"播放器 B", "player:B"}}},
        {"退出", "quit", {}},
    });

    // Open the menu near the bottom-right corner: it must be clamped inside.
    // The popup's first frame is hidden while its size is computed, so build
    // two frames before rendering.
    ui.openAt(W - 10, H - 10);
    ui.newFrame(state);
    ui.newFrame(state);
    CHECK(ui.menuOpen());

    const RenderRect r = ui.menuRect();
    CHECK(r.w > 0 && r.h > 0);
    CHECK(r.x >= 0 && r.y >= 0);
    CHECK(r.x + r.w <= W && r.y + r.h <= H);

    vk.beginOffscreenFrame();
    vk.beginRenderPass();
    ui.render(vk.commandBuffer());
    vk.endOffscreenFrame();
    const std::vector<uint8_t> pixels = vk.readbackOffscreen();

    // Menu background is semi-transparent dark; a center pixel must be
    // non-transparent (the imgui pipeline rendered into the framebuffer).
    const int cx = r.x + r.w / 2;
    const int cy = r.y + r.h / 2;
    const size_t off = (static_cast<size_t>(cy) * W + cx) * 4;
    const int alpha = pixels[off + 3];
    CHECK(alpha > 0);

    if (failures == 0) {
        std::printf("ui menu test passed (rect=%dx%d+%d+%d alpha=%d)\n", r.w,
                    r.h, r.x, r.y, alpha);
    }
    return failures == 0 ? 0 : 1;
}
