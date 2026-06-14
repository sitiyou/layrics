#pragma once

#include <cstdio>
#include <cstdlib>

namespace layrics {

inline bool debugEnabled() {
    static bool checked = false;
    static bool enabled = false;
    if (!checked) {
        const char *val = getenv("LAYRICS_DEBUG");
        enabled = val && (val[0] == '1' || val[0] == 'y' || val[0] == 'Y');
        checked = true;
    }
    return enabled;
}

} // namespace layrics

#define LAY_ERR(...)                                \
    do {                                            \
        fprintf(stderr, "[ERR] " __VA_ARGS__);      \
        fputc('\n', stderr);                        \
    } while (0)

#define LAY_WARN(...)                               \
    do {                                            \
        fprintf(stderr, "[WARN] " __VA_ARGS__);     \
        fputc('\n', stderr);                        \
    } while (0)

#define LAY_LOG(...)                                \
    do {                                            \
        fprintf(stderr, "[LOG] " __VA_ARGS__);      \
        fputc('\n', stderr);                        \
    } while (0)

#define LAY_DEBUG(...)                                          \
    do {                                                        \
        if (::layrics::debugEnabled()) {                        \
            fprintf(stderr, "[DEBUG] %s:%d ", __FILE__, __LINE__); \
            fprintf(stderr, __VA_ARGS__);                       \
            fputc('\n', stderr);                                \
        }                                                       \
    } while (0)
