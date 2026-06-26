#include "core/wayland/ShmBuffer.hpp"
#include "core/utils/Logger.hpp"

#include <wayland-client-protocol.h>
#include <wayland-client.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <errno.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef WL_SHM_FORMAT_ARGB8888
#define WL_SHM_FORMAT_ARGB8888 0
#endif

ShmBuffer::~ShmBuffer() { destroy(); }

ShmBuffer::ShmBuffer(ShmBuffer &&other) noexcept
    : m_buffer(other.m_buffer), m_data(other.m_data), m_width(other.m_width),
      m_height(other.m_height), m_stride(other.m_stride), m_size(other.m_size) {
    other.m_buffer = nullptr;
    other.m_data = nullptr;
    other.m_width = 0;
    other.m_height = 0;
    other.m_stride = 0;
    other.m_size = 0;
}

ShmBuffer &ShmBuffer::operator=(ShmBuffer &&other) noexcept {
    if (this != &other) {
        destroy();
        m_buffer = other.m_buffer;
        m_data = other.m_data;
        m_width = other.m_width;
        m_height = other.m_height;
        m_stride = other.m_stride;
        m_size = other.m_size;

        other.m_buffer = nullptr;
        other.m_data = nullptr;
        other.m_width = 0;
        other.m_height = 0;
        other.m_stride = 0;
        other.m_size = 0;
    }
    return *this;
}

bool ShmBuffer::allocate(int shmFd, wl_shm *shm, int width, int height,
                         uint32_t format) {
    if (shmFd < 0 || !shm || width <= 0 || height <= 0) {
        return false;
    }

    destroy();

    if (format == 0) {
        format = WL_SHM_FORMAT_ARGB8888;
    }

    m_width = width;
    m_height = height;
    m_stride = width * 4;
    m_size = static_cast<size_t>(m_stride) * height;

    LAY_DEBUG("allocating %dx%d stride=%d size=%zu", width, height, m_stride,
              m_size);

    if (ftruncate(shmFd, static_cast<off_t>(m_size)) != 0) {
        LAY_ERR("ftruncate(%d, %zu) failed: %s", shmFd, m_size,
                strerror(errno));
        return false;
    }

    void *mapData =
        mmap(nullptr, m_size, PROT_READ | PROT_WRITE, MAP_SHARED, shmFd, 0);
    if (mapData == MAP_FAILED) {
        LAY_ERR("mmap failed: %s", strerror(errno));
        m_width = 0;
        m_height = 0;
        m_stride = 0;
        m_size = 0;
        return false;
    }
    m_data = mapData;

    wl_shm_pool *pool =
        wl_shm_create_pool(shm, shmFd, static_cast<int32_t>(m_size));
    if (!pool) {
        LAY_ERR("wl_shm_create_pool failed");
        munmap(m_data, m_size);
        m_data = nullptr;
        m_width = 0;
        m_height = 0;
        m_stride = 0;
        m_size = 0;
        return false;
    }

    m_buffer =
        wl_shm_pool_create_buffer(pool, 0, width, height, m_stride, format);
    wl_shm_pool_destroy(pool);

    if (!m_buffer) {
        LAY_ERR("wl_shm_pool_create_buffer failed");
        munmap(m_data, m_size);
        m_data = nullptr;
        m_width = 0;
        m_height = 0;
        m_stride = 0;
        m_size = 0;
        return false;
    }

    return true;
}

void ShmBuffer::destroy() {
    if (m_buffer) {
        wl_buffer_destroy(m_buffer);
        m_buffer = nullptr;
    }
    if (m_data) {
        munmap(m_data, m_size);
        m_data = nullptr;
    }
    m_width = 0;
    m_height = 0;
    m_stride = 0;
    m_size = 0;
}

void ShmBuffer::clear() {
    if (m_data) {
        memset(m_data, 0, m_size);
    }
}
