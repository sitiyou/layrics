#version 450

layout(push_constant) uniform Push {
    vec2 offset;    // drag offset in pixels
    vec2 screen;    // surface size in pixels
    float progress; // 0 = hidden, 1 = fully shown
    float effect;   // TransitionEffect id, 0 = identity
    float amp;      // effect amplitude in pixels
    float param;    // effect-specific parameter (blur radius in UV units)
} push;

layout(location = 0) in vec2 inPos;    // pixels, unoffset
layout(location = 1) in vec2 inUV;
layout(location = 2) in vec4 inColor;  // premultiplied rgb, alpha
layout(location = 3) in vec2 inCenter; // quad center, pixels
layout(location = 4) in float inSeed;  // quad center x normalized over the text

layout(location = 0) out vec2 vUV;
layout(location = 1) out vec4 vColor;
layout(location = 2) out float vBlur;
layout(location = 3) out float vFlash;

const float kPi = 3.14159265;

float easeOutCubic(float t) {
    float u = 1.0 - t;
    return 1.0 - u * u * u;
}

// Overshoots past 1.0 before settling: the "snap into place" feel.
float easeOutBack(float t) {
    float c1 = 1.70158;
    float c3 = c1 + 1.0;
    float u = t - 1.0;
    return 1.0 + c3 * u * u * u + c1 * u * u;
}

float hash11(float p) {
    p = fract(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return fract(p);
}

vec2 rotateAround(vec2 p, vec2 c, float angle) {
    float s = sin(angle);
    float co = cos(angle);
    vec2 r = p - c;
    return c + vec2(r.x * co - r.y * s, r.x * s + r.y * co);
}

void main() {
    float t = clamp(push.progress, 0.0, 1.0);
    float id = push.effect;
    vec2 p = inPos;
    float alpha = 1.0;
    float blur = 0.0;
    float flash = 0.0;

    // t == 1 is the resting state: keep it bit-identical to the untransformed
    // path so an idle overlay rasterizes exactly as before.
    if (id > 0.5 && t < 1.0) {
        if (id < 1.5) { // fade
            alpha = t;
        } else if (id < 2.5) { // rise
            float e = easeOutCubic(t);
            p.y += (1.0 - e) * push.amp;
            alpha = t;
        } else if (id < 3.5) { // zoom
            float e = easeOutBack(t);
            p = inCenter + (p - inCenter) * mix(0.55, 1.0, e);
            alpha = t;
        } else if (id < 4.5) { // cascade
            float lt = clamp((t - 0.35 * inSeed) / 0.65, 0.0, 1.0);
            float e = easeOutBack(lt);
            p.y += (1.0 - e) * push.amp * 1.4;
            p = inCenter + (p - inCenter) * mix(0.85, 1.0, min(e, 1.0));
            alpha = lt;
        } else if (id < 5.5) { // wave
            float env = 1.0 - easeOutCubic(t);
            p.y += sin(inCenter.x * 0.02 - t * kPi * 2.0) * push.amp * env;
            alpha = clamp(t * 1.8, 0.0, 1.0);
        } else if (id < 6.5) { // scatter
            float h1 = hash11(inSeed * 37.0 + 1.0);
            float h2 = hash11(inSeed * 91.0 + 7.0);
            float h3 = hash11(inSeed * 53.0 + 3.0);
            float e = easeOutCubic(t);
            p += vec2(h1 - 0.5, h2 - 0.5) * push.amp * 4.0 * (1.0 - e);
            p = rotateAround(p, inCenter, (h3 - 0.5) * kPi * 2.0 * (1.0 - e));
            alpha = t;
        } else if (id < 7.5) { // flip
            float lt = clamp((t - 0.3 * inSeed) / 0.7, 0.0, 1.0);
            float e = easeOutCubic(lt);
            vec2 r = p - inCenter;
            p = inCenter + vec2(r.x * max(sin(kPi * 0.5 * e), 0.02), r.y);
            alpha = lt;
        } else if (id < 8.5) { // wipe
            float a = smoothstep(inSeed, inSeed + 0.3, t * 1.3);
            p.y += (1.0 - a) * push.amp * 0.6;
            alpha = a;
        } else if (id < 9.5) { // blurIn
            float e = easeOutCubic(t);
            alpha = e;
            blur = (1.0 - e) * push.param;
        } else { // flash
            float e = easeOutCubic(t);
            p = inCenter + (p - inCenter) * mix(0.7, 1.0, e);
            alpha = clamp(t * 2.0, 0.0, 1.0);
            flash = pow(1.0 - t, 3.0);
        }
    }

    vec2 q = p + push.offset;
    // Vulkan: NDC y = -1 is the TOP of the framebuffer (y axis points down).
    vec2 ndc = vec2(q.x / push.screen.x * 2.0 - 1.0,
                    q.y / push.screen.y * 2.0 - 1.0);
    gl_Position = vec4(ndc, 0.0, 1.0);
    vUV = inUV;
    vColor = inColor * alpha;
    vBlur = blur;
    vFlash = flash;
}
