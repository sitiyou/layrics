#version 450

layout(binding = 0) uniform sampler2D tex;

layout(location = 0) in vec2 vUV;
layout(location = 1) in vec4 vColor;  // premultiplied rgb, alpha
layout(location = 2) in float vBlur;  // vertical tap offset in UV units
layout(location = 3) in float vFlash; // whiten amount (0..1)

layout(location = 0) out vec4 outColor;

void main() {
    float coverage;
    if (vBlur > 0.0) {
        // Focus-pull: 3 vertical taps. The radius stays inside the 1px
        // duplicated edge ring of each atlas slot, so taps never reach a
        // neighbouring glyph.
        coverage = (texture(tex, vUV).r +
                    0.5 * texture(tex, vUV - vec2(0.0, vBlur)).r +
                    0.5 * texture(tex, vUV + vec2(0.0, vBlur)).r) * 0.5;
    } else {
        coverage = texture(tex, vUV).r; // R8 alpha bitmap
    }

    float a = vColor.a * coverage;
    // vColor is premultiplied, so mixing toward vColor.a yields white.
    vec3 rgb = mix(vColor.rgb, vec3(vColor.a), vFlash) * coverage;
    outColor = vec4(rgb, a);
}
