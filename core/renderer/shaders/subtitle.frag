#version 450

layout(binding = 0) uniform sampler2D tex;

layout(location = 0) in vec2 vUV;
layout(location = 1) in vec4 vColor;  // premultiplied rgb, alpha

layout(location = 0) out vec4 outColor;

void main() {
    float coverage = texture(tex, vUV).r;  // R8 alpha bitmap
    outColor = vec4(vColor.rgb * coverage, vColor.a * coverage);
}
