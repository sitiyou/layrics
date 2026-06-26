#pragma once

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>

namespace layrics {

inline bool g_debugEnabled = []() -> bool {
    const char *val = getenv("LAYRICS_DEBUG");
    if (val) {
        const char *p = val;
        while (*p) {
            while (*p == ' ')
                p++;
            if (std::strncmp(p, "core", 4) == 0) {
                char c = p[4];
                if (c == '\0' || c == ',' || c == ' ') {
                    return true;
                }
            }
            while (*p && *p != ',')
                p++;
            if (*p == ',')
                p++;
        }
    }
    return false;
}();

inline void logTimestamp(FILE *fp) {
    time_t now = time(nullptr);
    struct tm tm_buf;
    localtime_r(&now, &tm_buf);
    char buf[9];
    strftime(buf, sizeof(buf), "%H:%M:%S", &tm_buf);
    fprintf(fp, "%s ", buf);
}

} // namespace layrics

#define LAY_ERR(...)                                                           \
    do {                                                                       \
        ::layrics::logTimestamp(stderr);                                       \
        fprintf(stderr, "[ERROR] " __VA_ARGS__);                               \
        fputc('\n', stderr);                                                   \
    } while (0)

#define LAY_WARN(...)                                                          \
    do {                                                                       \
        ::layrics::logTimestamp(stderr);                                       \
        fprintf(stderr, "[WARN] " __VA_ARGS__);                                \
        fputc('\n', stderr);                                                   \
    } while (0)

#define LAY_LOG(...)                                                           \
    do {                                                                       \
        ::layrics::logTimestamp(stderr);                                       \
        fprintf(stderr, "[INFO] " __VA_ARGS__);                                \
        fputc('\n', stderr);                                                   \
    } while (0)

#define LAY_DEBUG(...)                                                         \
    do {                                                                       \
        if (::layrics::g_debugEnabled) {                                       \
            ::layrics::logTimestamp(stderr);                                   \
            fprintf(stderr, "[DEBUG] " __VA_ARGS__);                           \
            fputc('\n', stderr);                                               \
        }                                                                      \
    } while (0)
