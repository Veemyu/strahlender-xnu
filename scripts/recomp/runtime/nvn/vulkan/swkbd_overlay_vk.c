// Vulkan renderer of the on-screen keyboard (the Metal one is nvn/swkbd_overlay.m). The keyboard's logic, layouts, text atlas and draw lists are
// shared code (swkbd_ui.c, swkbd_text.c, swkbd_draw.c); this file only owns what is Vulkan: the pipelines, the images, the one-time blur and the
// draw calls. menu_render(cmd, w, h) is called by device.c backend_present with the window image's rendering open.
//
// While the keyboard is open the game thread is stopped inside the applet call and presents nothing; the thread below then asks the backend to
// present the last game image again (backend_represent), which draws the keyboard over it through menu_render. The picture is frozen: it is
// blurred once when the keyboard opens (the window image is copied to a quarter-size image and blurred in two passes), and everything the
// keyboard made (images, atlas, draw lists, the thread) is freed when it closes.
//
// Untested on a GPU so far (written on a Mac without a Linux machine): compiled with VK_SYNTAX=1 only.
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <SDL3/SDL.h>

#include "vulkan/vk.h"
#include "astc.h"
#include "lyt.h"
#include "swkbd_draw.h"
#include "swkbd_keepalive.h"
#include "swkbd_text.h"
#include "swkbd_ui.h"

// device.c
extern VkImage vk_frame_image(void);
extern void vk_frame_suspend(void);
extern void vk_frame_resume(void);
extern VkExtent2D vk_frame_extent(void);
extern uint64_t vk_last_game_present_ns(void);
extern void backend_represent(void);

typedef struct { VkImage img; VmaAllocation mem; VkImageView view; uint32_t w, h; } Tex;

// Push constants of every pipeline: the window size for the vertex shader, two vec4 for the fragment shaders (the focus frame's values; the blur step).
typedef struct { float vp[2], pad[2], a[4], b[4]; } Push;

static const char *kVert =
    "#version 450\n"
    "layout(location = 0) in vec2 pos;\n"
    "layout(location = 1) in vec2 uv;\n"
    "layout(location = 2) in vec4 col;\n"
    "layout(push_constant) uniform P { vec2 vp; vec2 pad; vec4 a; vec4 b; } p;\n"
    "layout(location = 0) out vec2 o_uv;\n"
    "layout(location = 1) out vec4 o_col;\n"
    "void main() { gl_Position = vec4(pos.x / p.vp.x * 2.0 - 1.0, pos.y / p.vp.y * 2.0 - 1.0, 0.0, 1.0); o_uv = uv; o_col = col; }\n";

static const char *kFrag =
    "#version 450\n"
    "layout(set = 0, binding = 0) uniform sampler2D t;\n"
    "layout(location = 0) in vec2 uv;\n"
    "layout(location = 1) in vec4 col;\n"
    "layout(location = 0) out vec4 o;\n"
    "void main() { o = texture(t, uv) * col; }\n";

// The focus frame: a rounded rectangle with a soft glow outside, a core, a soft inner edge and a green-to-blue gradient (same as the Metal shader)
static const char *kFrameFrag =
    "#version 450\n"
    "layout(push_constant) uniform P { vec2 vp; vec2 pad; vec4 a; vec4 b; } p;\n"
    "layout(location = 0) in vec2 uv;\n"
    "layout(location = 1) in vec4 col;\n"
    "layout(location = 0) out vec4 o;\n"
    "void main() {\n"
    "  vec2 hsz = p.a.xy; float rad = p.a.z; float aa = p.a.w;\n"
    "  vec2 q = abs(uv) - (hsz - rad);\n"
    "  float depth = -(length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - rad);\n"
    "  float halo = 0.36 * exp((depth - 1.9) / 2.0);\n"
    "  float f = mix(halo, 1.0, smoothstep(1.9 - aa, 1.9 + aa, depth));\n"
    "  f = mix(f, 0.5, smoothstep(6.4 - aa, 6.4 + aa, depth));\n"
    "  f = mix(f, 0.0, smoothstep(7.0 - aa, 7.0 + aa, depth));\n"
    "  float t = clamp(uv.y / hsz.y * 0.5 + 0.5, 0.0, 1.0);\n"
    "  vec3 c = p.b.rgb + (0.5 - t) * vec3(8.0, 16.0, -1.0) / 255.0;\n"
    "  o = vec4(c, p.b.a * f);\n"
    "}\n";

// Background blur: 13 taps of a gaussian along one axis (p.a.xy is the step), a fullscreen triangle
static const char *kBlurVert =
    "#version 450\n"
    "layout(location = 0) out vec2 o_uv;\n"
    "void main() { vec2 uv = vec2((gl_VertexIndex << 1) & 2, gl_VertexIndex & 2); gl_Position = vec4(uv * 2.0 - 1.0, 0.0, 1.0); o_uv = uv; }\n";

static const char *kBlurFrag =
    "#version 450\n"
    "layout(set = 0, binding = 0) uniform sampler2D t;\n"
    "layout(push_constant) uniform P { vec2 vp; vec2 pad; vec4 a; vec4 b; } p;\n"
    "layout(location = 0) in vec2 uv;\n"
    "layout(location = 0) out vec4 o;\n"
    "void main() {\n"
    "  vec3 c = vec3(0.0); float ws = 0.0;\n"
    "  for (int k = -6; k <= 6; k++) { float w = exp(-float(k * k) / 12.5); c += w * texture(t, uv + p.a.xy * float(k)).rgb; ws += w; }\n"
    "  o = vec4(c / ws, 1.0);\n"
    "}\n";

#define TEX_CACHE 96

static struct {
    // kept for the life of the process (a few kilobytes): layouts and pipelines
    VkDescriptorSetLayout dsl;
    VkPipelineLayout pl;
    VkPipeline pipe, pipe_frame, pipe_blur;
    VkFormat fmt;
    // made when the keyboard opens, freed when it closes
    Tex white, atlas, blur_a, blur_b;
    unsigned atlas_ver;
    struct { const LytTex *key; Tex t; } cache[TEX_CACHE];
    int ncache;
    int blur_ready;
    float blur_t;
    uint32_t blur_w, blur_h;
    SwkbdBatch batch;
    int was_active;
    uint64_t last_ns;
} V;

// ---- images
static int img_make(Tex *t, uint32_t w, uint32_t h, VkFormat fmt, VkImageUsageFlags usage, VkComponentMapping sw) {
    memset(t, 0, sizeof *t);
    VkImageCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D, .format = fmt, .extent = {w, h, 1},
                            .mipLevels = 1, .arrayLayers = 1, .samples = VK_SAMPLE_COUNT_1_BIT, .tiling = VK_IMAGE_TILING_OPTIMAL, .usage = usage,
                            .sharingMode = VK_SHARING_MODE_EXCLUSIVE, .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED};
    VmaAllocationCreateInfo ai = {.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    if (vmaCreateImage(g_vk.vma, &ci, &ai, &t->img, &t->mem, NULL) != VK_SUCCESS) { memset(t, 0, sizeof *t); return 0; }
    VkImageViewCreateInfo vi = {.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = t->img, .viewType = VK_IMAGE_VIEW_TYPE_2D, .format = fmt,
                                .components = sw, .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    if (vkCreateImageView(g_vk.dev, &vi, NULL, &t->view) != VK_SUCCESS) { vmaDestroyImage(g_vk.vma, t->img, t->mem); memset(t, 0, sizeof *t); return 0; }
    t->w = w; t->h = h;
    vk_image_init_layout(vk_upload_cmd(), t->img, VK_IMAGE_ASPECT_COLOR_BIT);   // (every image of the backend lives in the general layout)
    return 1;
}

static void img_free(Tex *t) {
    if (t->view) vk_defer_view(t->view);
    if (t->img) vk_defer_image(t->img, t->mem);
    memset(t, 0, sizeof *t);
}

// Copies pixels into the image with the next submission's upload command buffer (it runs before the frame's own commands).
static void img_upload(const Tex *t, const void *px, uint64_t bytes) {
    VkSpan s = vk_transient_copy(px, bytes, 16);
    VkBufferImageCopy rg = {.bufferOffset = s.off, .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .imageExtent = {t->w, t->h, 1}};
    vkCmdCopyBufferToImage(vk_upload_cmd(), s.buf, t->img, VK_IMAGE_LAYOUT_GENERAL, 1, &rg);
}

static const VkComponentMapping kIdentity = {VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY};

// A layout texture as an RGBA8 image (BC4 / BC5 are decoded by lyt_tex_to_rgba; ASTC here, the desktop GPUs have no hardware for it).
static const Tex *layout_tex(const LytTex *lt) {
    for (int i = 0; i < V.ncache; i++) if (V.cache[i].key == lt) return V.cache[i].t.view ? &V.cache[i].t : NULL;
    if (V.ncache == TEX_CACHE) return NULL;
    int w = 0, h = 0;
    uint8_t *px = NULL;
    if (lyt_tex_is_astc(lt)) {
        if (lt->blocks) {
            uint8_t *raw = malloc((size_t)lt->w * lt->h * 4);
            if (raw) { astc_decode_ldr(lt->blocks, lt->w, lt->h, 4, 4, false, raw); px = lyt_tex_to_rgba(lt, raw, &w, &h); }
            free(raw);
        }
    } else {
        px = lyt_tex_to_rgba(lt, NULL, &w, &h);
    }
    int i = V.ncache++;
    V.cache[i].key = lt;
    if (px && img_make(&V.cache[i].t, (uint32_t)w, (uint32_t)h, VK_FORMAT_R8G8B8A8_UNORM, VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, kIdentity))
        img_upload(&V.cache[i].t, px, (uint64_t)w * h * 4);
    free(px);
    return V.cache[i].t.view ? &V.cache[i].t : NULL;
}

// The glyph atlas as an R8 image that reads as white with the coverage in alpha; uploaded again when glyphs were added.
static const Tex *atlas_tex(void) {
    int w, h;
    unsigned ver;
    const uint8_t *px = swkbd_text_atlas(&w, &h, &ver);
    if (!px) return NULL;
    if (!V.atlas.view) {
        VkComponentMapping sw = {VK_COMPONENT_SWIZZLE_ONE, VK_COMPONENT_SWIZZLE_ONE, VK_COMPONENT_SWIZZLE_ONE, VK_COMPONENT_SWIZZLE_R};
        if (!img_make(&V.atlas, (uint32_t)w, (uint32_t)h, VK_FORMAT_R8_UNORM, VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, sw)) return NULL;
        V.atlas_ver = ver - 1;
    }
    if (ver != V.atlas_ver) { img_upload(&V.atlas, px, (uint64_t)w * h); V.atlas_ver = ver; }
    return &V.atlas;
}

// ---- pipelines
static VkPipeline make_pipe(VkShaderModule vs, VkShaderModule fs, VkFormat fmt, int vertices, int blend) {
    VkPipelineShaderStageCreateInfo st[2] = {
        {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_VERTEX_BIT, .module = vs, .pName = "main"},
        {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_FRAGMENT_BIT, .module = fs, .pName = "main"}};
    VkVertexInputBindingDescription vb = {0, sizeof(SwkbdVtx), VK_VERTEX_INPUT_RATE_VERTEX};
    VkVertexInputAttributeDescription va[3] = {{0, 0, VK_FORMAT_R32G32_SFLOAT, 0}, {1, 0, VK_FORMAT_R32G32_SFLOAT, 8}, {2, 0, VK_FORMAT_R32G32B32A32_SFLOAT, 16}};
    VkPipelineVertexInputStateCreateInfo vi = {.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
    if (vertices) { vi.vertexBindingDescriptionCount = 1; vi.pVertexBindingDescriptions = &vb; vi.vertexAttributeDescriptionCount = 3; vi.pVertexAttributeDescriptions = va; }
    VkPipelineInputAssemblyStateCreateInfo ia = {.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO, .topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST};
    VkPipelineViewportStateCreateInfo vp = {.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO, .viewportCount = 1, .scissorCount = 1};
    VkPipelineRasterizationStateCreateInfo rs = {.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO, .polygonMode = VK_POLYGON_MODE_FILL,
                                                 .cullMode = VK_CULL_MODE_NONE, .lineWidth = 1};
    VkPipelineMultisampleStateCreateInfo ms = {.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO, .rasterizationSamples = VK_SAMPLE_COUNT_1_BIT};
    VkPipelineColorBlendAttachmentState cba = {.colorWriteMask = 0xF};
    if (blend) {
        cba.blendEnable = VK_TRUE;
        cba.srcColorBlendFactor = VK_BLEND_FACTOR_SRC_ALPHA; cba.dstColorBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA; cba.colorBlendOp = VK_BLEND_OP_ADD;
        cba.srcAlphaBlendFactor = VK_BLEND_FACTOR_ONE; cba.dstAlphaBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA; cba.alphaBlendOp = VK_BLEND_OP_ADD;
    }
    VkPipelineColorBlendStateCreateInfo cb = {.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO, .attachmentCount = 1, .pAttachments = &cba};
    VkDynamicState dyn[] = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo dy = {.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO, .dynamicStateCount = 2, .pDynamicStates = dyn};
    VkPipelineRenderingCreateInfo ri = {.sType = VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO, .colorAttachmentCount = 1, .pColorAttachmentFormats = &fmt};
    VkPipelineDepthStencilStateCreateInfo ds = {.sType = VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO};
    VkGraphicsPipelineCreateInfo pi = {.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO, .pNext = &ri, .stageCount = 2, .pStages = st,
                                       .pVertexInputState = &vi, .pInputAssemblyState = &ia, .pViewportState = &vp, .pRasterizationState = &rs,
                                       .pMultisampleState = &ms, .pDepthStencilState = &ds, .pColorBlendState = &cb, .pDynamicState = &dy, .layout = V.pl};
    VkPipeline p = VK_NULL_HANDLE;
    if (vkCreateGraphicsPipelines(g_vk.dev, g_vk.pcache, 1, &pi, NULL, &p) != VK_SUCCESS) return VK_NULL_HANDLE;
    return p;
}

static int pipelines(void) {
    if (V.pipe && V.fmt == g_vk.sc_format) return 1;
    if (!V.pl) {
        VkDescriptorSetLayoutBinding b = {0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_FRAGMENT_BIT, NULL};
        VkDescriptorSetLayoutCreateInfo li = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 1, .pBindings = &b};
        if (vkCreateDescriptorSetLayout(g_vk.dev, &li, NULL, &V.dsl) != VK_SUCCESS) return 0;
        VkPushConstantRange r = {VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof(Push)};
        VkPipelineLayoutCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &V.dsl,
                                         .pushConstantRangeCount = 1, .pPushConstantRanges = &r};
        if (vkCreatePipelineLayout(g_vk.dev, &ci, NULL, &V.pl) != VK_SUCCESS) return 0;
    }
    VkShaderModule vs = vk_compile_glsl(kVert, STAGE_VERTEX, "swkbd.vert"), fs = vk_compile_glsl(kFrag, STAGE_FRAGMENT, "swkbd.frag");
    VkShaderModule ff = vk_compile_glsl(kFrameFrag, STAGE_FRAGMENT, "swkbd_frame.frag");
    VkShaderModule bv = vk_compile_glsl(kBlurVert, STAGE_VERTEX, "swkbd_blur.vert"), bf = vk_compile_glsl(kBlurFrag, STAGE_FRAGMENT, "swkbd_blur.frag");
    if (!vs || !fs || !ff || !bv || !bf) return 0;
    V.fmt = g_vk.sc_format;
    V.pipe = make_pipe(vs, fs, V.fmt, 1, 1);
    V.pipe_frame = make_pipe(vs, ff, V.fmt, 1, 1);
    V.pipe_blur = make_pipe(bv, bf, V.fmt, 0, 0);
    return V.pipe && V.pipe_frame && V.pipe_blur;
}

// ---- drawing
static void bind_tex(VkCommandBuffer cb, const Tex *t) {
    VkDescriptorSet ds = vk_alloc_set(V.dsl);
    VkDescriptorImageInfo ii = {vk_default_sampler(true), t->view, VK_IMAGE_LAYOUT_GENERAL};
    VkWriteDescriptorSet w = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = ds, .dstBinding = 0, .descriptorCount = 1,
                              .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &ii};
    vkUpdateDescriptorSets(g_vk.dev, 1, &w, 0, NULL);
    vkCmdBindDescriptorSets(cb, VK_PIPELINE_BIND_POINT_GRAPHICS, V.pl, 0, 1, &ds, 0, NULL);
}

static void layout_barrier(VkCommandBuffer cb, VkImage img, VkImageLayout from, VkImageLayout to) {
    VkImageMemoryBarrier2 b = {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2,
                               .srcStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, .srcAccessMask = VK_ACCESS_2_MEMORY_WRITE_BIT,
                               .dstStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, .dstAccessMask = VK_ACCESS_2_MEMORY_READ_BIT | VK_ACCESS_2_MEMORY_WRITE_BIT,
                               .oldLayout = from, .newLayout = to, .image = img, .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
                               .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED};
    VkDependencyInfo di = {.sType = VK_STRUCTURE_TYPE_DEPENDENCY_INFO, .imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &b};
    vkCmdPipelineBarrier2(cb, &di);
}

// One blur pass: samples `in`, writes `out` (both quarter size, general layout), 13 taps along `step`.
static void blur_pass(VkCommandBuffer cb, const Tex *in, const Tex *out, float sx, float sy) {
    VkRenderingAttachmentInfo ca = {.sType = VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO, .imageView = out->view, .imageLayout = VK_IMAGE_LAYOUT_GENERAL,
                                    .loadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE, .storeOp = VK_ATTACHMENT_STORE_OP_STORE};
    VkRenderingInfo ri = {.sType = VK_STRUCTURE_TYPE_RENDERING_INFO, .renderArea = {{0, 0}, {out->w, out->h}}, .layerCount = 1, .colorAttachmentCount = 1, .pColorAttachments = &ca};
    vkCmdBeginRendering(cb, &ri);
    VkViewport vp = {0, 0, (float)out->w, (float)out->h, 0, 1};
    VkRect2D sc = {{0, 0}, {out->w, out->h}};
    vkCmdSetViewport(cb, 0, 1, &vp);
    vkCmdSetScissor(cb, 0, 1, &sc);
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_GRAPHICS, V.pipe_blur);
    bind_tex(cb, in);
    Push pc = {{(float)out->w, (float)out->h}, {0, 0}, {sx, sy, 0, 0}, {0, 0, 0, 0}};
    vkCmdPushConstants(cb, V.pl, VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof pc, &pc);
    vkCmdDraw(cb, 3, 1, 0, 0);
    vkCmdEndRendering(cb);
}

static void blur_drop(void) {
    img_free(&V.blur_a); img_free(&V.blur_b);
    V.blur_ready = 0; V.blur_t = 0;
}

// Blurs the window image (the frozen game picture under the keyboard) once: a quarter-size copy, then a horizontal and a vertical pass. The result is blur_a.
static int blur_capture(void) {
    VkExtent2D ext = vk_frame_extent();
    uint32_t qw = ext.width / 4 > 1 ? ext.width / 4 : 1, qh = ext.height / 4 > 1 ? ext.height / 4 : 1;
    VkImageUsageFlags use = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    if (!img_make(&V.blur_a, qw, qh, V.fmt, use, kIdentity) || !img_make(&V.blur_b, qw, qh, V.fmt, use, kIdentity)) { blur_drop(); return 0; }
    vk_frame_suspend();   // ends the window image's rendering: the copy and the passes are outside of it
    VkCommandBuffer cb = vk_cmd();
    VkImage win = vk_frame_image();
    layout_barrier(cb, win, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
    VkImageBlit bl = {.srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .srcOffsets = {{0, 0, 0}, {(int32_t)ext.width, (int32_t)ext.height, 1}},
                      .dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .dstOffsets = {{0, 0, 0}, {(int32_t)qw, (int32_t)qh, 1}}};
    vkCmdBlitImage(cb, win, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, V.blur_a.img, VK_IMAGE_LAYOUT_GENERAL, 1, &bl, VK_FILTER_LINEAR);
    layout_barrier(cb, win, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);
    vk_full_barrier(cb);
    blur_pass(cb, &V.blur_a, &V.blur_b, 1.0f / (float)qw, 0);
    vk_full_barrier(cb);
    blur_pass(cb, &V.blur_b, &V.blur_a, 0, 1.0f / (float)qh);
    vk_full_barrier(cb);
    vk_frame_resume();
    V.blur_w = ext.width; V.blur_h = ext.height;
    V.blur_ready = 1;
    return 1;
}

static void release(void) {
    blur_drop();
    for (int i = 0; i < V.ncache; i++) img_free(&V.cache[i].t);
    V.ncache = 0;
    img_free(&V.white); img_free(&V.atlas);
    swkbd_text_close();
    swkbd_draw_free(&V.batch);
}

static void quad_verts(SwkbdVtx *v, float w, float h, float a) {
    static const float X[6] = {0, 1, 0, 1, 1, 0}, Y[6] = {0, 0, 1, 0, 1, 1};
    for (int k = 0; k < 6; k++) {
        v[k].pos[0] = X[k] * w; v[k].pos[1] = Y[k] * h; v[k].uv[0] = X[k]; v[k].uv[1] = Y[k];
        v[k].col[0] = v[k].col[1] = v[k].col[2] = 1; v[k].col[3] = a;
    }
}

static uint64_t clock_ns(void) { return SDL_GetTicksNS(); }
static const SwkbdKeepalive k_keepalive = {clock_ns, vk_last_game_present_ns, backend_represent};
static void keepalive_wake(void) { swkbd_keepalive_wake(&k_keepalive); }

void menu_render(void *cmd, uint32_t w, uint32_t h) {
    static int once;
    if (!once) {   // first frame: the keyboard can be drawn when the firmware's text font is there
        once = 1;
        const char *root = getenv("BDSP_FIRMWARE_DATA");
        if (root && *root && swkbd_text_available(root)) { swkbd_ui_set_display(1); swkbd_ui_set_wake(keepalive_wake); }
    }
    int active = swkbd_ui_visible();
    if (active != V.was_active) {
        V.was_active = active;
        if (!active) { release(); return; }
        swkbd_text_open(swkbd_ui_root());
        swkbd_ui_set_measure(swkbd_text_measure_px);
    }
    if (!active || !w || !h) return;
    VkCommandBuffer cb = (VkCommandBuffer)cmd;
    if (!pipelines()) return;
    uint64_t now = SDL_GetTicksNS();
    double dt = V.last_ns ? (double)(now - V.last_ns) / 1e9 : 0.016;
    if (dt > 0.1) dt = 0.1;
    V.last_ns = now;
    if (V.blur_ready && (V.blur_w != w || V.blur_h != h)) blur_drop();   // window resized: blur again
    if (!V.blur_ready) blur_capture();
    else V.blur_t += (float)dt;
    cb = vk_cmd();   // (the blur ended and resumed the window image's rendering on the same command buffer)
    if (!V.white.view) {
        uint8_t white[4] = {255, 255, 255, 255};
        if (img_make(&V.white, 1, 1, VK_FORMAT_R8G8B8A8_UNORM, VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, kIdentity)) img_upload(&V.white, white, 4);
    }
    float scale, off[2];
    const LytScene *sc = swkbd_ui_scene(dt, (int)w, (int)h, &scale, off);
    if (!sc) { V.last_ns = 0; return; }
    swkbd_text_frame_begin();
    swkbd_draw_build(&V.batch, sc, scale, off);
    // vertices: the blurred backdrop first, then the keyboard
    int nv = V.batch.nv + 6;
    VkSpan vb = vk_transient((uint64_t)nv * sizeof(SwkbdVtx), 16);
    SwkbdVtx *v = vb.ptr;
    float fa = (V.blur_t >= 0.1f ? 1.0f : V.blur_t / 0.1f) * swkbd_ui_backdrop();
    quad_verts(v, (float)w, (float)h, fa);
    if (V.batch.nv) memcpy(v + 6, V.batch.v, (size_t)V.batch.nv * sizeof(SwkbdVtx));
    vkCmdBindVertexBuffers(cb, 0, 1, &vb.buf, (VkDeviceSize[]){vb.off});
    Push pc = {{(float)w, (float)h}, {0, 0}, {0, 0, 0, 0}, {0, 0, 0, 0}};
    const VkShaderStageFlags all = VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT;
    vkCmdPushConstants(cb, V.pl, all, 0, sizeof pc, &pc);
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_GRAPHICS, V.pipe);
    if (V.blur_ready && V.blur_a.view && fa > 0) { bind_tex(cb, &V.blur_a); vkCmdDraw(cb, 6, 1, 0, 0); }
    for (int i = 0; i < V.batch.nd; i++) {
        const SwkbdDraw *d = &V.batch.d[i];
        if (d->kind == SWKBD_DRAW_FRAME) {
            Push fp = pc;
            fp.a[0] = d->half[0]; fp.a[1] = d->half[1]; fp.a[2] = d->rad; fp.a[3] = d->px;
            memcpy(fp.b, d->col, sizeof fp.b);
            vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_GRAPHICS, V.pipe_frame);
            bind_tex(cb, V.white.view ? &V.white : &V.blur_a);   // (the shader samples nothing; the layout still wants a set)
            vkCmdPushConstants(cb, V.pl, all, 0, sizeof fp, &fp);
            vkCmdDraw(cb, (uint32_t)d->count, 1, (uint32_t)d->first + 6, 0);
            vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_GRAPHICS, V.pipe);
            vkCmdPushConstants(cb, V.pl, all, 0, sizeof pc, &pc);
            continue;
        }
        const Tex *t = d->tex == SWKBD_TEX_WHITE ? &V.white : d->tex == SWKBD_TEX_ATLAS ? atlas_tex() : layout_tex(d->tex);
        if (!t || !t->view) continue;
        bind_tex(cb, t);
        vkCmdDraw(cb, (uint32_t)d->count, 1, (uint32_t)d->first + 6, 0);
    }
    swkbd_ui_unlock();
}
