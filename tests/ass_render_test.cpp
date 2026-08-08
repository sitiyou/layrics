// Headless test: render an ASS frame through the real Vulkan pipeline and
// compare GPU pixels bit-for-bit against a CPU reference. Nothing touches
// the screen. Usage: ass-render-test [--dump <dir>] [--ts <ms>]

#include <ass/ass.h>
#include <vulkan/vulkan.h>

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include <memory>
#include <string>
#include <vector>

#include "core/renderer/AssRenderer.hpp"
#include "core/renderer/RenderManager.hpp"
#include "core/renderer/VulkanContext.hpp"

namespace {

const int kWidth = 1280;
const int kHeight = 720;

// PlayRes matches the render size: glyphs with outline+shadow, a bordered
// rect, and a \clip split.
const char *kTestAss = R"ASS(
[Script Info]
Script Type: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK SC,48,&H00FFFFFF,&H000000FF,&H00FF0000,&H00000000,0,0,0,0,100,100,0,0,1,3,2,2,20,20,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,1:00:00.00,Default,,0,0,0,,{\an7\pos(80,60)\bord3\shad3}Hello 文字
Dialogue: 1,0:00:00.00,1:00:00.00,Default,,0,0,0,,{\an7\pos(100,300)\p1}m 0 0 l 400 0 l 400 200 l 0 200 l 0 0{\p0}
Dialogue: 2,0:00:00.00,1:00:00.00,Default,,0,0,0,,{\an7\pos(600,420)\bord0\clip(600,420,900,560)}Clip 文字
)ASS";

// CPU reference: composite the libass bitmaps over transparent black with
// straight-alpha source-over (the same math the shader+blend implement).
std::vector<uint8_t> cpuReference(int64_t tsMs) {
    std::vector<uint8_t> frame(static_cast<size_t>(kWidth) * kHeight * 4, 0);

    ASS_Library *lib = ass_library_init();
    ASS_Renderer *rend = ass_renderer_init(lib);
    // Same font setup as AssRenderer so the bitmaps match exactly.
    ass_set_fonts(rend, nullptr, "sans-serif", ASS_FONTPROVIDER_AUTODETECT,
                  nullptr, 1);
    ass_set_frame_size(rend, kWidth, kHeight);

    ASS_Track *track = ass_read_memory(lib, const_cast<char *>(kTestAss),
                                       std::strlen(kTestAss), nullptr);
    if (!track) {
        ass_renderer_done(rend);
        ass_library_done(lib);
        return frame;
    }

    int changed = 0;
    ASS_Image *img = ass_render_frame(rend, track, tsMs, &changed);
    for (ASS_Image *im = img; im; im = im->next) {
        unsigned int c = im->color;
        int cr = (c >> 24) & 0xFF;
        int cg = (c >> 16) & 0xFF;
        int cb = (c >> 8) & 0xFF;
        int ca = 255 - (c & 0xFF); // straight alpha
        for (int yy = 0; yy < im->h; yy++) {
            for (int xx = 0; xx < im->w; xx++) {
                int cov = im->bitmap[yy * im->stride + xx];
                int px = im->dst_x + xx;
                int py = im->dst_y + yy;
                if (px < 0 || px >= kWidth || py < 0 || py >= kHeight) {
                    continue;
                }
                uint8_t *o =
                    frame.data() + (static_cast<size_t>(py) * kWidth + px) * 4;
                int srcA = cov * ca; // 0..65025 premultiplied source alpha
                for (int k = 0; k < 3; k++) {
                    int sc = k == 0 ? cr : (k == 1 ? cg : cb);
                    o[k] = static_cast<uint8_t>(sc * srcA / (255 * 255) +
                                                o[k] * (255 * 255 - srcA) /
                                                    (255 * 255));
                }
                o[3] = static_cast<uint8_t>(srcA / 255 +
                                            o[3] * (255 - srcA / 255) / 255);
            }
        }
    }

    ass_free_track(track);
    ass_renderer_done(rend);
    ass_library_done(lib);
    return frame;
}

} // namespace

// Karaoke-style: one line split into per-syllable \pos + \clip events.
std::string karaokeAss() {
    std::string s =
        "[Script Info]\nScript Type: v4.00+\nPlayResX: 1280\nPlayResY: 720\n"
        "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
        "SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Noto Sans CJK SC,56,&H00FFFFFF,&H00FFFFFF,"
        "&H000000FF,&H00000000,0,0,0,0,100,100,0,0,1,3,2,2,20,20,20,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n";
    const std::string kLine = "今夜月色真美君の名は心の声";
    int x = 60;
    // Iterate the UTF-8 string in 3-byte chunks (CJK characters).
    for (size_t i = 0; i < kLine.size(); i += 3) {
        int w = 56;
        s += "Dialogue: 0,0:00:00.00,1:00:00.00,Default,,0,0,0,,{\\an7\\pos(" +
             std::to_string(x) + ",300)\\t(0,300,\\clip(" + std::to_string(x) +
             ",280," + std::to_string(x + 20) + ",400))}";
        s += kLine.substr(i, 3);
        s += "\n";
        x += w + 8;
    }
    return s;
}

// Benchmark: per-frame GPU time for N karaoke frames, full-surface vs
// damage-restricted render pass.
int runBenchmark(int frames) {
    VulkanContext vk;
    if (!vk.initializeOffscreen(kWidth, kHeight)) {
        std::fprintf(stderr, "FAIL: offscreen Vulkan init failed\n");
        return 1;
    }
    RenderManager rm;
    auto renderer = std::make_unique<AssRenderer>(karaokeAss());
    if (!renderer->initialize(vk)) {
        std::fprintf(stderr, "FAIL: renderer initialize failed\n");
        return 1;
    }
    rm.addRenderer(std::move(renderer));
    rm.setSize(kWidth, kHeight);

    auto timeFrame = [&]() -> double {
        auto t0 = std::chrono::steady_clock::now();
        vk.beginOffscreenFrame();
        rm.prepare(1000);
        rm.recordUploads(vk.commandBuffer());
        vk.beginRenderPass();
        rm.recordDraws(vk.commandBuffer());
        vk.endOffscreenFrame();
        auto t1 = std::chrono::steady_clock::now();
        return std::chrono::duration<double, std::milli>(t1 - t0).count();
    };

    // Warm-up (first frame allocates the atlas).
    timeFrame();
    double changed = 0, unchanged = 0;
    for (int i = 0; i < frames; i++) {
        changed += timeFrame();
        // Re-render the same frame: prepare() short-circuits (no re-pack,
        // no atlas upload) - isolates the fixed per-frame cost.
        unchanged += timeFrame();
    }
    std::printf("bench(%d frames): changed=%.3fms  unchanged=%.3fms\n", frames,
                changed / frames, unchanged / frames);
    return 0;
}

int main(int argc, char **argv) {
    const char *dumpDir = nullptr;
    int64_t tsMs = 1000;
    int benchFrames = 0;
    for (int i = 1; i < argc; i++) {
        if (std::strcmp(argv[i], "--dump") == 0 && i + 1 < argc) {
            dumpDir = argv[++i];
        } else if (std::strcmp(argv[i], "--ts") == 0 && i + 1 < argc) {
            tsMs = std::atoll(argv[++i]);
        } else if (std::strcmp(argv[i], "--bench") == 0 && i + 1 < argc) {
            benchFrames = std::atoi(argv[++i]);
        }
    }

    if (benchFrames > 0) {
        return runBenchmark(benchFrames);
    }

    VulkanContext vk;
    if (!vk.initializeOffscreen(kWidth, kHeight)) {
        std::fprintf(stderr, "FAIL: offscreen Vulkan init failed\n");
        return 1;
    }

    RenderManager rm;
    auto renderer = std::make_unique<AssRenderer>(std::string(kTestAss));
    if (!renderer->initialize(vk)) {
        std::fprintf(stderr, "FAIL: renderer initialize failed\n");
        return 1;
    }
    rm.addRenderer(std::move(renderer));
    rm.setSize(kWidth, kHeight);

    vk.beginOffscreenFrame();
    rm.prepare(tsMs);
    rm.recordUploads(vk.commandBuffer());
    vk.beginRenderPass();
    rm.recordDraws(vk.commandBuffer());
    vk.endOffscreenFrame();
    std::vector<uint8_t> gpu = vk.readbackOffscreen();

    std::vector<uint8_t> cpu = cpuReference(tsMs);

    if (dumpDir) {
        std::string gp = std::string(dumpDir) + "/gpu.raw";
        std::string cp = std::string(dumpDir) + "/cpu.raw";
        FILE *fg = std::fopen(gp.c_str(), "wb");
        FILE *fc = std::fopen(cp.c_str(), "wb");
        if (fg && fc) {
            std::fwrite(gpu.data(), 1, gpu.size(), fg);
            std::fwrite(cpu.data(), 1, cpu.size(), fc);
            std::printf("dumped %s and %s\n", gp.c_str(), cp.c_str());
        }
        if (fg)
            std::fclose(fg);
        if (fc)
            std::fclose(fc);
    }

    size_t diffCount = 0;
    int maxDiff = 0;
    for (size_t i = 0; i < gpu.size(); i += 4) {
        for (int k = 0; k < 3; k++) {
            int d = std::abs(static_cast<int>(gpu[i + k]) -
                             static_cast<int>(cpu[i + k]));
            if (d > 0) {
                diffCount++;
                if (d > maxDiff)
                    maxDiff = d;
            }
        }
    }

    if (diffCount == 0) {
        std::printf("PASS: GPU pixels identical to CPU reference (%dx%d)\n",
                    kWidth, kHeight);
        return 0;
    }
    std::printf("FAIL: %zu differing channels, max diff %d\n", diffCount,
                maxDiff);
    return 1;
}
