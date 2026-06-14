#pragma once

#include <string>

#include "core/renderer/IRenderer.hpp"

struct ass_library;
struct ass_renderer;
struct ass_track;
typedef struct ass_library ASS_Library;
typedef struct ass_renderer ASS_Renderer;
typedef struct ass_track ASS_Track;

class AssRenderer : public IRenderer {
  public:
    explicit AssRenderer(std::string assContent);
    ~AssRenderer() override;

    AssRenderer(const AssRenderer &) = delete;
    AssRenderer &operator=(const AssRenderer &) = delete;

    bool initialize() override;
    void shutdown() override;

    cairo_surface_t *render(int64_t timestampMs) override;
    void setSize(int width, int height) override;

    void loadContent(const std::string &content);
    ASS_Track *track() const { return m_track; }

  private:
    ASS_Library *m_library = nullptr;
    ASS_Renderer *m_renderer = nullptr;
    ASS_Track *m_track = nullptr;
    cairo_surface_t *m_surface = nullptr;
    std::string m_assContent;
    int m_width = 0;
    int m_height = 0;

    void invalidateSurface();
    static void messageCallback(int level, const char *fmt, va_list va,
                                void *data);
};
