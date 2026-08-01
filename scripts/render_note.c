#include <stdarg.h>
/* Render one ASS frame via libass to a transparent PNG.
 * Usage: render_note <in.ass> <out.png> <width> <height> <time_ms>
 * Requires: libass, cairo (pkg-config). */
#include <ass/ass.h>
#include <cairo.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint8_t *read_file(const char *path, long *len)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    *len = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *buf = malloc(*len + 1);
    if (fread(buf, 1, *len, f) != (size_t)*len) {
        fclose(f);
        free(buf);
        return NULL;
    }
    buf[*len] = '\0';
    fclose(f);
    return buf;
}

static void msg_cb(int level, const char *fmt, va_list va, void *data)
{
    (void)level; (void)fmt; (void)va; (void)data;
}

int main(int argc, char **argv)
{
    if (argc < 6) {
        fprintf(stderr, "usage: %s <in.ass> <out.png> <w> <h> <time_ms>\n", argv[0]);
        return 1;
    }
    int w = atoi(argv[3]), h = atoi(argv[4]), time_ms = atoi(argv[5]);

    ASS_Library *lib = ass_library_init();
    if (!lib)
        return 1;
    ass_set_message_cb(lib, msg_cb, NULL);
    ass_set_extract_fonts(lib, 1);

    ASS_Track *track = ass_new_track(lib);
    long len = 0;
    uint8_t *buf = read_file(argv[1], &len);
    if (!buf) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 1;
    }
    ass_process_data(track, (char *)buf, len);
    free(buf);

    ASS_Renderer *renderer = ass_renderer_init(lib);
    ass_set_fonts(renderer, NULL, NULL, ASS_FONTPROVIDER_FONTCONFIG, NULL, 1);
    ass_set_frame_size(renderer, w, h);
    ass_set_storage_size(renderer, w, h);

    int stride = w * 4;
    uint8_t *img = calloc((size_t)h * stride, 1); /* transparent BGRA */

    ASS_Image *img_list = ass_render_frame(renderer, track, time_ms, NULL);
    for (ASS_Image *im = img_list; im; im = im->next) {
        /* libass stores color as 0xRRGGBBAA where AA is *transparency*
         * (0 = opaque, same convention as ASS &HAABBGGRR). */
        uint8_t cr = (im->color >> 24) & 0xff;
        uint8_t cg = (im->color >> 16) & 0xff;
        uint8_t cb = (im->color >> 8) & 0xff;
        uint8_t tr = im->color & 0xff; /* transparency */
        for (int y = 0; y < im->h; y++) {
            for (int x = 0; x < im->w; x++) {
                uint8_t a = (uint8_t)((im->bitmap[y * im->stride + x] * (255 - tr)) / 255);
                if (!a)
                    continue;
                int px = im->dst_x + x, py = im->dst_y + y;
                if (px < 0 || px >= w || py < 0 || py >= h)
                    continue;
                uint8_t *p = img + py * stride + px * 4;
                p[0] = (uint8_t)((cb * a + p[0] * (255 - a)) / 255);
                p[1] = (uint8_t)((cg * a + p[1] * (255 - a)) / 255);
                p[2] = (uint8_t)((cr * a + p[2] * (255 - a)) / 255);
                p[3] = (uint8_t)(a + p[3] * (255 - a) / 255);
            }
        }
    }

    cairo_surface_t *surf = cairo_image_surface_create_for_data(
        img, CAIRO_FORMAT_ARGB32, w, h, stride);
    cairo_surface_flush(surf);
    cairo_status_t st = cairo_surface_write_to_png(surf, argv[2]);
    cairo_surface_destroy(surf);

    ass_renderer_done(renderer);
    ass_free_track(track);
    ass_library_done(lib);
    free(img);
    return st != CAIRO_STATUS_SUCCESS;
}
