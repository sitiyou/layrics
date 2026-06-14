#pragma once

#include <cstddef>
#include <cstdint>

struct wl_buffer;
struct wl_shm;

class ShmBuffer {
  public:
    ShmBuffer() = default;
    ~ShmBuffer();

    ShmBuffer(const ShmBuffer &) = delete;
    ShmBuffer &operator=(const ShmBuffer &) = delete;
    ShmBuffer(ShmBuffer &&) noexcept;
    ShmBuffer &operator=(ShmBuffer &&) noexcept;

    bool allocate(int shmFd, wl_shm *shm, int width, int height,
                  uint32_t format = 0 /* WL_SHM_FORMAT_ARGB8888 */);
    void destroy();

    wl_buffer *buffer() const { return m_buffer; }
    void *data() const { return m_data; }
    int stride() const { return m_stride; }
    int width() const { return m_width; }
    int height() const { return m_height; }
    void clear();
    explicit operator bool() const { return m_buffer != nullptr; }

  private:
    wl_buffer *m_buffer = nullptr;
    void *m_data = nullptr;
    int m_width = 0;
    int m_height = 0;
    int m_stride = 0;
    size_t m_size = 0;
};
