#version 450 core

// Custom fragment shader for the imgui Vulkan backend. The framebuffer must
// stay premultiplied (layrics presents with VK_COMPOSITE_ALPHA_PRE_MULTIPLIED),
// so both the vertex color and the texture sample are premultiplied before the
// ONE / ONE_MINUS_SRC_ALPHA blend. The font atlas is straight alpha (RGB=255
// constant, coverage in alpha), hence the texture.rgb * texture.a term.
layout(location = 0) out vec4 fColor;
layout(set=0, binding=0) uniform texture2D _Texture;
layout(set=1, binding=0) uniform sampler _Sampler;

layout(location = 0) in vec4 InColor;
layout(location = 1) in vec2 InUV;

void main()
{
    vec4 tex = texture(sampler2D(_Texture, _Sampler), InUV);
    fColor = vec4(InColor.rgb * InColor.a, InColor.a)
             * vec4(tex.rgb * tex.a, tex.a);
}
