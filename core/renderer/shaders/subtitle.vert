#version 450

layout(push_constant) uniform Push {
    vec2 offset;   // drag offset in pixels
    vec2 screen;   // surface size in pixels
} push;

layout(location = 0) in vec2 inPos;    // pixels, unoffset
layout(location = 1) in vec2 inUV;
layout(location = 2) in vec4 inColor;  // premultiplied rgb, alpha

layout(location = 0) out vec2 vUV;
layout(location = 1) out vec4 vColor;

void main() {
    vec2 p = inPos + push.offset;
    // Vulkan: NDC y = -1 is the TOP of the framebuffer (y axis points down).
    vec2 ndc = vec2(p.x / push.screen.x * 2.0 - 1.0,
                    p.y / push.screen.y * 2.0 - 1.0);
    gl_Position = vec4(ndc, 0.0, 1.0);
    vUV = inUV;
    vColor = inColor;
}
