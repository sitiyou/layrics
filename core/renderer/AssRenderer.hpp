#pragma once

#include <string>
#include <vector>

#include "core/renderer/IRenderer.hpp"
#include "core/renderer/VulkanContext.hpp"

struct ass_library;
struct ass_renderer;
struct ass_track;
struct ass_image;
typedef struct ass_library ASS_Library;
typedef struct ass_renderer ASS_Renderer;
typedef struct ass_track ASS_Track;
typedef struct ass_image ASS_Image;

// Renders ASS via libass (CPU) into an R8 atlas (mpv-style, 1px padding),
// drawn as textured quads sharing one descriptor set.
class AssRenderer : public IRenderer {
  public:
    explicit AssRenderer(std::string assContent);
    ~AssRenderer() override;

    AssRenderer(const AssRenderer &) = delete;
    AssRenderer &operator=(const AssRenderer &) = delete;

    bool initialize(VulkanContext &vk) override;
    void shutdown() override;
    void setSize(int width, int height) override;

    void prepare(int64_t timestampMs) override;
    void recordUploads(VkCommandBuffer cmd) override;
    void recordDraws(VkCommandBuffer cmd, float offsetX, float offsetY,
                     int screenW, int screenH) override;

    void loadContent(const std::string &content);
    ASS_Track *track() const { return m_track; }

  private:
    struct Quad {
        float x, y, w, h; // destination rect (pixels)
        float u0, v0, u1, v1;
        float r, g, b, a; // premultiplied rgb + alpha
    };

    // Atlas starts at 2048x2048 and doubles (mpv-style) on overflow.
    static constexpr int kAtlasMin = 2048;
    static constexpr int kAtlasMax = 8192;

    ASS_Library *m_library = nullptr;
    ASS_Renderer *m_renderer = nullptr;
    ASS_Track *m_track = nullptr;
    VulkanContext *m_vk = nullptr;
    std::string m_assContent;
    int m_width = 0;
    int m_height = 0;

    VulkanContext::Texture m_atlas;
    std::vector<uint8_t> m_atlasData; // CPU staging: m_atlasW * m_atlasH
    int m_atlasW = 0;                 // actual texture dimensions (power of 2)
    int m_atlasH = 0;
    bool m_atlasReady = false;
    bool m_uploadPending = false; // atlas repacked; upload in recordUploads
    int m_packedH = 0;            // used height of the atlas (upload region)

    std::vector<Quad> m_quads;
    VulkanContext::DynamicBuffer m_vertexBuf;

    void destroyAtlas();
    bool packImages(const ASS_Image *img); // false when the atlas overflows
    void fillVertexBuffer();
    static void messageCallback(int level, const char *fmt, va_list va,
                                void *data);
};
