#include <sys/mman.h>
#include "paths.h"
#include "settings.h"
#include "ui/menu.h"
// Metal renderer for the NVN layer: window, textures, command execution, presentation.
#include <sys/stat.h>
#import <AppKit/AppKit.h>
#import <Metal/Metal.h>
#import <MetalFX/MetalFX.h>
#include "output_scale.h"
#import <QuartzCore/CAMetalLayer.h>
#import <CoreText/CoreText.h>
#include <SDL3/SDL.h>
#include <SDL3/SDL_metal.h>
#include <stdatomic.h>

#include "nvn.h"
#include "renderer.h"
#include "texpatch.h"
#include "bctc.h"

static id<MTLDevice> dev;
static id<MTLCommandQueue> queue;
static CAMetalLayer *layer;
#define PRESENT_AT_DEFAULT 3   // phase-locked presentation (measurement see docs/rendering.md); BDSP_PRESENT_AT=off switches it off
extern volatile int g_bdsp_fps;
static inline double g_bdsp_fps_now(void) { return g_bdsp_fps; }
static SDL_Window *window;
static atomic_bool ui_ready;
static id<MTLRenderPipelineState> present_pipe;
static id<MTLSamplerState> present_sampler;
id<MTLBuffer> g_guest_buffer;  // wraps the guest heap so GPU addresses map to buffer offsets
uint64_t g_guest_buffer_base;

// ================================================================== formats
typedef struct { MTLPixelFormat pf; uint8_t expand_rgb; uint8_t force_alpha_one; } MtlFormat;

// GPU without BC textures (iPhone A13) or BDSP_TEST_NO_BC=1: BC formats become what bctc.c converts them to (set in backend_init)
static bool g_no_bc;
bool renderer_no_bc(void) { return g_no_bc; }

static MtlFormat mtl_format(uint32_t f) {
    if (g_no_bc)
        switch (bctc_kind(f)) {
        case BCTC_ASTC: return (MtlFormat){MTLPixelFormatASTC_4x4_LDR};
        case BCTC_ASTC_SRGB: return (MtlFormat){MTLPixelFormatASTC_4x4_sRGB};
        case BCTC_R8: return (MtlFormat){MTLPixelFormatR8Unorm};
        case BCTC_R8S: return (MtlFormat){MTLPixelFormatR8Snorm};
        case BCTC_RG8: return (MtlFormat){MTLPixelFormatRG8Unorm};
        case BCTC_RG8S: return (MtlFormat){MTLPixelFormatRG8Snorm};
        default: break;
        }
    switch (f) {
    case 0x01: return (MtlFormat){MTLPixelFormatR8Unorm};
    case 0x02: return (MtlFormat){MTLPixelFormatR8Snorm};
    case 0x03: return (MtlFormat){MTLPixelFormatR8Uint};
    case 0x04: return (MtlFormat){MTLPixelFormatR8Sint};
    case 0x05: return (MtlFormat){MTLPixelFormatR16Float};
    case 0x06: return (MtlFormat){MTLPixelFormatR16Unorm};
    case 0x07: return (MtlFormat){MTLPixelFormatR16Snorm};
    case 0x08: return (MtlFormat){MTLPixelFormatR16Uint};
    case 0x09: return (MtlFormat){MTLPixelFormatR16Sint};
    case 0x0A: return (MtlFormat){MTLPixelFormatR32Float};
    case 0x0B: return (MtlFormat){MTLPixelFormatR32Uint};
    case 0x0C: return (MtlFormat){MTLPixelFormatR32Sint};
    case 0x0D: return (MtlFormat){MTLPixelFormatRG8Unorm};
    case 0x0E: return (MtlFormat){MTLPixelFormatRG8Snorm};
    case 0x0F: return (MtlFormat){MTLPixelFormatRG8Uint};
    case 0x10: return (MtlFormat){MTLPixelFormatRG8Sint};
    case 0x11: return (MtlFormat){MTLPixelFormatRG16Float};
    case 0x12: return (MtlFormat){MTLPixelFormatRG16Unorm};
    case 0x13: return (MtlFormat){MTLPixelFormatRG16Snorm};
    case 0x14: return (MtlFormat){MTLPixelFormatRG16Uint};
    case 0x15: return (MtlFormat){MTLPixelFormatRG16Sint};
    case 0x16: return (MtlFormat){MTLPixelFormatRG32Float};
    case 0x17: return (MtlFormat){MTLPixelFormatRG32Uint};
    case 0x18: return (MtlFormat){MTLPixelFormatRG32Sint};
    case 0x19: return (MtlFormat){MTLPixelFormatRGBA8Unorm, 1, 1};
    case 0x25: return (MtlFormat){MTLPixelFormatRGBA8Unorm};
    case 0x26: return (MtlFormat){MTLPixelFormatRGBA8Snorm};
    case 0x27: return (MtlFormat){MTLPixelFormatRGBA8Uint};
    case 0x28: return (MtlFormat){MTLPixelFormatRGBA8Sint};
    case 0x29: return (MtlFormat){MTLPixelFormatRGBA16Float};
    case 0x2A: return (MtlFormat){MTLPixelFormatRGBA16Unorm};
    case 0x2B: return (MtlFormat){MTLPixelFormatRGBA16Snorm};
    case 0x2C: return (MtlFormat){MTLPixelFormatRGBA16Uint};
    case 0x2D: return (MtlFormat){MTLPixelFormatRGBA16Sint};
    case 0x2E: return (MtlFormat){MTLPixelFormatRGBA32Float};
    case 0x2F: return (MtlFormat){MTLPixelFormatRGBA32Uint};
    case 0x30: return (MtlFormat){MTLPixelFormatRGBA32Sint};
    case 0x31: return (MtlFormat){MTLPixelFormatStencil8};
    case 0x32: return (MtlFormat){MTLPixelFormatDepth16Unorm};
    case 0x33: return (MtlFormat){MTLPixelFormatDepth32Float};
    case 0x34: return (MtlFormat){MTLPixelFormatDepth32Float};
    case 0x35: return (MtlFormat){MTLPixelFormatDepth32Float_Stencil8};
    case 0x36: return (MtlFormat){MTLPixelFormatDepth32Float_Stencil8};
    case 0x37: return (MtlFormat){MTLPixelFormatRGBA8Unorm_sRGB, 0, 1};
    case 0x38: return (MtlFormat){MTLPixelFormatRGBA8Unorm_sRGB};
    case 0x39: return (MtlFormat){MTLPixelFormatABGR4Unorm};
    case 0x3A: return (MtlFormat){MTLPixelFormatB5G6R5Unorm};
    case 0x3B: return (MtlFormat){MTLPixelFormatA1BGR5Unorm};
    case 0x3C: return (MtlFormat){MTLPixelFormatB5G6R5Unorm};
    case 0x3D: return (MtlFormat){MTLPixelFormatRGB10A2Unorm};
    case 0x3E: return (MtlFormat){MTLPixelFormatRGB10A2Uint};
    case 0x3F: return (MtlFormat){MTLPixelFormatRG11B10Float};
    case 0x40: return (MtlFormat){MTLPixelFormatRGB9E5Float};
    case 0x41: case 0x42: return (MtlFormat){MTLPixelFormatBC1_RGBA};
    case 0x43: return (MtlFormat){MTLPixelFormatBC2_RGBA};
    case 0x44: return (MtlFormat){MTLPixelFormatBC3_RGBA};
    case 0x45: case 0x46: return (MtlFormat){MTLPixelFormatBC1_RGBA_sRGB};
    case 0x47: return (MtlFormat){MTLPixelFormatBC2_RGBA_sRGB};
    case 0x48: return (MtlFormat){MTLPixelFormatBC3_RGBA_sRGB};
    case 0x49: return (MtlFormat){MTLPixelFormatBC4_RUnorm};
    case 0x4A: return (MtlFormat){MTLPixelFormatBC4_RSnorm};
    case 0x4B: return (MtlFormat){MTLPixelFormatBC5_RGUnorm};
    // 0x4C = signed RGTC2 (interior normal maps break if decoded unsigned). BDSP_BC5_UNORM=1 decodes it
    // unsigned: that removes the overworld grass hatch/moire (see notes/PLAN.md) but wrecks interiors.
    case 0x4C: return (MtlFormat){getenv("BDSP_BC5_UNORM") ? MTLPixelFormatBC5_RGUnorm : MTLPixelFormatBC5_RGSnorm};
    case 0x4D: return (MtlFormat){MTLPixelFormatBC7_RGBAUnorm};
    case 0x4E: return (MtlFormat){MTLPixelFormatBC7_RGBAUnorm_sRGB};
    case 0x4F: return (MtlFormat){MTLPixelFormatBC6H_RGBFloat};
    case 0x50: return (MtlFormat){MTLPixelFormatBC6H_RGBUfloat};
    case 0x6D: return (MtlFormat){MTLPixelFormatRGBA8Unorm, 0, 1};
    case 0x71: return (MtlFormat){MTLPixelFormatRGBA16Float, 0, 1};
    case 0x76: return (MtlFormat){MTLPixelFormatRGBA32Float, 0, 1};
    case 0x79: return (MtlFormat){MTLPixelFormatASTC_4x4_LDR};
    case 0x7A: return (MtlFormat){MTLPixelFormatASTC_5x4_LDR};
    case 0x7B: return (MtlFormat){MTLPixelFormatASTC_5x5_LDR};
    case 0x7C: return (MtlFormat){MTLPixelFormatASTC_6x5_LDR};
    case 0x7D: return (MtlFormat){MTLPixelFormatASTC_6x6_LDR};
    case 0x7E: return (MtlFormat){MTLPixelFormatASTC_8x5_LDR};
    case 0x7F: return (MtlFormat){MTLPixelFormatASTC_8x6_LDR};
    case 0x80: return (MtlFormat){MTLPixelFormatASTC_8x8_LDR};
    case 0x81: return (MtlFormat){MTLPixelFormatASTC_10x5_LDR};
    case 0x82: return (MtlFormat){MTLPixelFormatASTC_10x6_LDR};
    case 0x83: return (MtlFormat){MTLPixelFormatASTC_10x8_LDR};
    case 0x84: return (MtlFormat){MTLPixelFormatASTC_10x10_LDR};
    case 0x85: return (MtlFormat){MTLPixelFormatASTC_12x10_LDR};
    case 0x86: return (MtlFormat){MTLPixelFormatASTC_12x12_LDR};
    case 0x87: return (MtlFormat){MTLPixelFormatASTC_4x4_sRGB};
    case 0x88: return (MtlFormat){MTLPixelFormatASTC_5x4_sRGB};
    case 0x89: return (MtlFormat){MTLPixelFormatASTC_5x5_sRGB};
    case 0x8A: return (MtlFormat){MTLPixelFormatASTC_6x5_sRGB};
    case 0x8B: return (MtlFormat){MTLPixelFormatASTC_6x6_sRGB};
    case 0x8C: return (MtlFormat){MTLPixelFormatASTC_8x5_sRGB};
    case 0x8D: return (MtlFormat){MTLPixelFormatASTC_8x6_sRGB};
    case 0x8E: return (MtlFormat){MTLPixelFormatASTC_8x8_sRGB};
    case 0x8F: return (MtlFormat){MTLPixelFormatASTC_10x5_sRGB};
    case 0x90: return (MtlFormat){MTLPixelFormatASTC_10x6_sRGB};
    case 0x91: return (MtlFormat){MTLPixelFormatASTC_10x8_sRGB};
    case 0x92: return (MtlFormat){MTLPixelFormatASTC_10x10_sRGB};
    case 0x93: return (MtlFormat){MTLPixelFormatASTC_12x10_sRGB};
    case 0x94: return (MtlFormat){MTLPixelFormatASTC_12x12_sRGB};
    case 0x95: case 0x97: return (MtlFormat){MTLPixelFormatA1BGR5Unorm};
    case 0x96: return (MtlFormat){MTLPixelFormatA1BGR5Unorm};
    case 0x98: return (MtlFormat){MTLPixelFormatBGRA8Unorm, 0, 1};
    case 0x99: return (MtlFormat){MTLPixelFormatBGRA8Unorm};
    case 0x9A: return (MtlFormat){MTLPixelFormatBGRA8Unorm_sRGB, 0, 1};
    case 0x9B: return (MtlFormat){MTLPixelFormatBGRA8Unorm_sRGB};
    default:
        return (MtlFormat){MTLPixelFormatRGBA8Unorm};
    }
}

bool renderer_format_is_depth(uint32_t f) { return f >= 0x31 && f <= 0x36; }
bool renderer_format_has_stencil(uint32_t f) { return f == 0x31 || f == 0x35 || f == 0x36; }
MTLPixelFormat renderer_pixel_format(uint32_t f) { return mtl_format(f).pf; }
bool renderer_format_alpha_one(uint32_t f) { return mtl_format(f).force_alpha_one; }

// ================================================================== textures
typedef struct {
    __unsafe_unretained id<MTLTexture> tex;  // retained manually (CFBridgingRetain)
    bool gpu_owned;     // written by the GPU (render target / copy dest): never re-uploaded
    bool uploaded;
    bool dynamic;        // contents changed after the first upload: verify fully every frame
    uint64_t data_hash, sample_hash;
    uint64_t checked_frame, full_frame;
    bool scalable;       // screen-shaped render target: allocated at the output resolution
    bool presented;      // has been shown by backend_present (a swapchain image)
    uint64_t touched_frame;  // last frame it was written (cleared at the first write of a frame when reshaped)
    uint32_t level_gen;      // g_level_gen when last used as a render target
    uint64_t frame_cleared;  // BDSP_FRAME_CLEAR: frame it was last cleared at first use
    float sx, sy;        // allocation scale relative to the guest's size
    int reg;             // slot in g_reg (live textures, for the "largest textures" dump) + 1
    int tp;              // runtime/nvn/texpatch.c: 0 not checked yet, -1 none, else known UI texture + 1
    uint32_t tp_gen;     // texpatch_generation() it was last uploaded with
    uint32_t key_target, key_w, key_h, key_fmt, key_samples;  // guest descriptor the Metal texture was created from
} TexBackend;

// Live textures (diagnostics: the overworld slowdown at 32:9 - the same textures used 870 MB and 4x the GPU time
// until a window resize reallocated them; user 2026-10-09). Dumped when the frame rate stays low.
static NvnTexture *g_reg[16384];
static int g_reg_n;
static void reg_add(NvnTexture *t, TexBackend *b) {
    if (b->reg || g_reg_n >= 16384) return;
    g_reg[g_reg_n++] = t;
    b->reg = g_reg_n;
}
static void reg_remove(TexBackend *b) {
    if (!b->reg) return;
    int i = b->reg - 1;
    NvnTexture *last = g_reg[--g_reg_n];
    g_reg[i] = last;
    if (last && last->backend) ((TexBackend *)last->backend)->reg = i + 1;
    b->reg = 0;
}
static void dump_largest_textures(const char *why) {
    int idx[16];
    uint64_t sz[16];
    int n = 0;
    for (int i = 0; i < g_reg_n; i++) {
        TexBackend *b = g_reg[i] ? (TexBackend *)g_reg[i]->backend : NULL;
        if (!b || !b->tex) continue;
        uint64_t a = b->tex.allocatedSize;
        int k = n < 16 ? n++ : 15;
        if (k == 15 && n == 16 && a <= sz[15]) continue;
        while (k > 0 && sz[k - 1] < a) { sz[k] = sz[k - 1]; idx[k] = idx[k - 1]; k--; }
        sz[k] = a; idx[k] = i;
    }
    LOG("[texdump] %s: %d live textures, largest:\n", why, g_reg_n);
    for (int k = 0; k < n; k++) {
        NvnTexture *t = g_reg[idx[k]];
        TexBackend *b = (TexBackend *)t->backend;
        LOG("[texdump]   %6.1f MB  guest %ux%u f%#x tgt %u lv %u | mtl %lux%lu lv %lu | scalable %d scale %.2fx%.2f %s\n",
            sz[k] / 1048576.0, t->width, t->height, t->format, t->target, t->levels, (unsigned long)b->tex.width,
            (unsigned long)b->tex.height, (unsigned long)b->tex.mipmapLevelCount, b->scalable, b->sx, b->sy, t->label);
    }
}

// BDSP_TEX_INVENTORY=1 (diagnostics): every 600 presented frames, live textures per NVN format (count, MiB of the Metal allocations);
// basis for the BC -> ASTC decision on GPUs without BC. Runs where the renderer runs (worker), so the registry is not changed meanwhile.
static void tex_inventory_tick(uint64_t frame) {
    static int on = -1;
    if (on < 0) on = getenv("BDSP_TEX_INVENTORY") != NULL;
    if (!on || frame % 600 != 0) return;
    uint64_t bytes[256] = {0}, total = 0;
    uint32_t count[256] = {0};
    for (int i = 0; i < g_reg_n; i++) {
        TexBackend *b = g_reg[i] ? (TexBackend *)g_reg[i]->backend : NULL;
        if (!b || !b->tex) continue;
        uint32_t f = g_reg[i]->format & 0xFF;
        count[f]++;
        bytes[f] += b->tex.allocatedSize;
        total += b->tex.allocatedSize;
    }
    LOG("[texinv] frame %llu: %d textures, %.1f MiB\n", (unsigned long long)frame, g_reg_n, total / 1048576.0);
    for (int f = 0; f < 256; f++)
        if (count[f]) LOG("[texinv]   f%#04x %5u textures %8.1f MiB\n", f, count[f], bytes[f] / 1048576.0);
}

// Start gate display (renderer.m startup_gate): "Shader compilation n / N" as text. The presentation thread
// calls this at 60 Hz; during the gate it is the only presenter.
static const char GATE_MSL[] =
    "#include <metal_stdlib>\nusing namespace metal;\n"
    "struct GOut { float4 pos [[position]]; float2 uv; };\n"
    "vertex GOut gate_v(uint vid [[vertex_id]], constant float4 &rect [[buffer(0)]]) {\n"
    "  const float2 p[6] = {float2(0,0), float2(1,0), float2(0,1), float2(0,1), float2(1,0), float2(1,1)};\n"
    "  GOut o; o.pos = float4(rect.x + p[vid].x * rect.z, rect.y + p[vid].y * rect.w, 0, 1);\n"
    "  o.uv = float2(p[vid].x, 1.0 - p[vid].y); return o;\n}\n"
    "fragment float4 gate_f(GOut in [[stage_in]], texture2d<float> t [[texture(0)]]) {\n"
    "  constexpr sampler s(filter::linear); return t.sample(s, in.uv);\n}\n";
static id<MTLRenderPipelineState> gate_pipe;
static MTLPixelFormat gate_pipe_format;

static NSString *gate_label(uint64_t done, uint64_t total) {
    static BOOL german;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ german = [[NSLocale preferredLanguages].firstObject hasPrefix:@"de"]; });
    return [NSString stringWithFormat:german ? @"Shader-Kompilierung %llu / %llu" : @"Shader compilation %llu / %llu",
                                      (unsigned long long)done, (unsigned long long)total];
}

// Text as a premultiplied BGRA texture; the font scales with the height of the image.
static id<MTLTexture> gate_text(NSString *s, CGFloat pix_h, CGSize *size_out) {
    CTFontRef font = CTFontCreateWithName(CFSTR("Helvetica"), pix_h / 50.0, NULL);
    NSDictionary *attrs = @{ (id)kCTFontAttributeName: (__bridge id)font,
                             (id)kCTForegroundColorFromContextAttributeName: @YES };
    NSAttributedString *as = [[NSAttributedString alloc] initWithString:s attributes:attrs];
    CTLineRef line = CTLineCreateWithAttributedString((__bridge CFAttributedStringRef)as);
    CGFloat asc = 0, desc = 0, lead = 0;
    double w = CTLineGetTypographicBounds(line, &asc, &desc, &lead);
    int pad = (int)(pix_h / 60.0) + 2;
    size_t W = (size_t)ceil(w) + 2 * pad, H = (size_t)ceil(asc + desc) + 2 * pad;
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
    CGContextRef ctx = CGBitmapContextCreate(NULL, W, H, 8, W * 4, cs,
                                             kCGImageAlphaPremultipliedFirst | kCGBitmapByteOrder32Little);
    CGContextSetRGBFillColor(ctx, 1, 1, 1, 0.7);
    CGContextSetTextPosition(ctx, pad, pad + desc);
    CTLineDraw(line, ctx);
    MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
                                                                                  width:W height:H mipmapped:NO];
    td.usage = MTLTextureUsageShaderRead;
    id<MTLTexture> t = [dev newTextureWithDescriptor:td];
    [t replaceRegion:MTLRegionMake2D(0, 0, W, H) mipmapLevel:0 withBytes:CGBitmapContextGetData(ctx) bytesPerRow:W * 4];
    *size_out = CGSizeMake(W, H);
    CGContextRelease(ctx);
    CGColorSpaceRelease(cs);
    CFRelease(line);
    CFRelease(font);
    return t;
}

void renderer_gate_present(uint64_t done, uint64_t total) {
    if (!layer) return;
    id<CAMetalDrawable> drawable = [layer nextDrawable];
    if (!drawable) return;
    id<MTLTexture> target = drawable.texture;
    if (!gate_pipe || gate_pipe_format != target.pixelFormat) {
        NSError *err = nil;
        id<MTLLibrary> lib = [dev newLibraryWithSource:@(GATE_MSL) options:nil error:&err];
        if (!lib) { LOG("[gate] shader failed: %s\n", err.localizedDescription.UTF8String); return; }
        MTLRenderPipelineDescriptor *d = [MTLRenderPipelineDescriptor new];
        d.vertexFunction = [lib newFunctionWithName:@"gate_v"];
        d.fragmentFunction = [lib newFunctionWithName:@"gate_f"];
        MTLRenderPipelineColorAttachmentDescriptor *ca = d.colorAttachments[0];
        ca.pixelFormat = target.pixelFormat;
        ca.blendingEnabled = YES;
        ca.sourceRGBBlendFactor = MTLBlendFactorOne;
        ca.destinationRGBBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
        ca.sourceAlphaBlendFactor = MTLBlendFactorOne;
        ca.destinationAlphaBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
        gate_pipe = [dev newRenderPipelineStateWithDescriptor:d error:&err];
        if (!gate_pipe) { LOG("[gate] pipeline failed: %s\n", err.localizedDescription.UTF8String); return; }
        gate_pipe_format = target.pixelFormat;
    }
    CGSize tsize;
    id<MTLTexture> t = gate_text(gate_label(done, total), target.height, &tsize);
    float ndc_w = 2.0f * tsize.width / target.width, ndc_h = 2.0f * tsize.height / target.height;
    float margin_x = 2.0f * (target.height / 45.0f) / target.width, margin_y = 2.0f * (target.height / 45.0f) / target.height;
    float rect[4] = {-1.0f + margin_x, 1.0f - margin_y - ndc_h, ndc_w, ndc_h};  // linke obere Ecke
    MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
    rp.colorAttachments[0].texture = target;
    rp.colorAttachments[0].loadAction = MTLLoadActionClear;
    rp.colorAttachments[0].clearColor = MTLClearColorMake(0, 0, 0, 1);
    rp.colorAttachments[0].storeAction = MTLStoreActionStore;
    id<MTLCommandBuffer> cb = [queue commandBuffer];
    id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:rp];
    [enc setRenderPipelineState:gate_pipe];
    [enc setVertexBytes:rect length:sizeof rect atIndex:0];
    [enc setFragmentTexture:t atIndex:0];
    [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];
    [enc endEncoding];
    [cb presentDrawable:drawable];
    [cb commit];
}

static uint64_t frames, total_frames, wk_frames;  // wk_frames: frames from the point of view of the translation worker
bool renderer_on_worker(void);  // renderer.m
uint64_t renderer_present_count(void) { return renderer_on_worker() ? wk_frames : total_frames; }

// Output resolution: render targets the game sizes for the 1920x1080 screen are allocated at
// (sx, sy) times their guest size. Shaders and the renderer keep working in guest ("logical") units.
static float g_rs_x = 1, g_rs_y = 1;
void renderer_get_scale(float *sx, float *sy) { *sx = g_rs_x; *sy = g_rs_y; }
void renderer_set_scale(float sx, float sy) { g_rs_x = sx; g_rs_y = sy; }

static bool tex_scalable(const NvnTexture *t) {
    if (getenv("BDSP_NO_SCALE")) return false;
    if (t->target != 1 || t->samples > 1 || !(t->flags & 8) || t->width < 32 || t->height < 16) return false;
    float a = (float)t->width / (float)t->height;
    return a > 1.74f && a < 1.81f;  // 16:9 (1920x1080 and its fractions, 704x396, 60x33...)
}

// First write this frame to a presented image while the output is reshaped: returns true once per frame.
bool renderer_texture_first_write(NvnTexture *t) {
    TexBackend *b = t ? (TexBackend *)t->backend : NULL;
    extern bool g_debug_frame;
    if (g_debug_frame && b && b->presented)
        LOG("[fw] tex %p %ux%u f%#x sx %.2f sy %.2f touched %llu now %llu\n", (void *)t, t->width, t->height, t->format,
            b->sx, b->sy, (unsigned long long)b->touched_frame, (unsigned long long)total_frames + 1);
    if (!b || !b->presented || (b->sx == b->sy) || b->touched_frame == renderer_present_count() + 1) return false;
    b->touched_frame = renderer_present_count() + 1;
    return true;
}

// A new level gets fresh render-target memory on the Switch (black); ours keep the previous level's pixels, which
// show wherever a level never draws (the phone booth's surroundings). Render targets are cleared at their first
// use after a level change (BDSP_KEEP_TARGETS=1 disables).
static uint32_t g_level_gen = 1;
static void level_change_check(void) {
    extern const char *game_level_name(void);
    static char last[64];
    const char *lv = game_level_name();
    if (strncmp(lv, last, sizeof last - 1) != 0) {
        strlcpy(last, lv, sizeof last);
        // only levels that never draw their surroundings: clearing everywhere also wipes targets other rooms
        // carry over (a house lost a band of its walls)
        if (!strncmp(lv, "TelephoneBox", 12) || getenv("BDSP_CLEAR_ALL_LEVELS")) g_level_gen++;
    }
}
// Scene render targets are cleared to transparent black at their first use in each frame (BDSP_NO_FRAME_CLEAR=1
// disables): pixels a frame never draws (inside pits, around generated rooms) otherwise keep older frames' content
// and smear (moving enemies over a pit left trails, the pit rim repeated downwards). Verified 2026-10-08 on
// rando/DevGen3 Tail Cave 07D: clean dark pit, no trails; overworld / dungeon rooms otherwise unchanged.
bool renderer_texture_frame_fresh(NvnTexture *t) {
    static int on = -1;
    if (on < 0) on = getenv("BDSP_NO_FRAME_CLEAR") == NULL;
    TexBackend *b = t ? (TexBackend *)t->backend : NULL;
    if (!on || !b || !b->scalable || b->frame_cleared == renderer_present_count() + 1) return false;
    b->frame_cleared = renderer_present_count() + 1;
    return true;
}

bool renderer_texture_level_fresh(NvnTexture *t) {
    TexBackend *b = t ? (TexBackend *)t->backend : NULL;
    static int keep = -1;
    if (keep < 0) keep = getenv("BDSP_KEEP_TARGETS") != NULL;
    if (!b || keep || b->level_gen == g_level_gen) return false;
    if (!b->scalable) { b->level_gen = g_level_gen; return false; }  // scene buffers only: UI textures the game draws once
                                                                       // and reuses (rupee counter) must keep their contents
    bool fresh = b->level_gen != 0;  // first use ever: nothing stale to hide
    b->level_gen = g_level_gen;
    if (fresh && getenv("BDSP_LOG_LEVELCLEAR"))
        LOG("[levelclear] gen %u frame %llu tex %p %ux%u fmt %#x addr %llx\n", g_level_gen, (unsigned long long)total_frames, (void *)t,
            t->width, t->height, t->format, (unsigned long long)t->addr);
    return fresh;
}

void renderer_texture_mark_presented(NvnTexture *t) {
    TexBackend *b = t ? (TexBackend *)t->backend : NULL;
    if (b) b->presented = true;
}

bool renderer_texture_presented(NvnTexture *t) {
    TexBackend *b = t ? (TexBackend *)t->backend : NULL;
    return b && b->presented;
}

void renderer_texture_scale(NvnTexture *t, float *sx, float *sy) {
    TexBackend *b = t ? (TexBackend *)t->backend : NULL;
    if (b && b->scalable) { *sx = b->sx; *sy = b->sy; }
    else { *sx = 1; *sy = 1; }
}

static MTLTextureType mtl_tex_type(uint32_t target, uint32_t samples) {
    switch (target) {
    case 0: return MTLTextureType1D;
    case 2: return MTLTextureType3D;
    case 3: return MTLTextureType1DArray;
    case 4: return MTLTextureType2DArray;
    case 5: return MTLTextureType2DMultisample;
    case 6: return MTLTextureType2DMultisampleArray;
    case 8: return MTLTextureTypeCube;
    case 9: return MTLTextureTypeCubeArray;
    default: return samples > 1 ? MTLTextureType2DMultisample : MTLTextureType2D;
    }
}

static void create_backend_texture(NvnTexture *t, TexBackend *b);
static void release_backend_texture(NvnTexture *t, TexBackend *b);
int g_tex_live;              // (stats: Metal textures alive and their size)
uint64_t g_tex_live_bytes;
void renderer_texture_gone(void *nvn_tex, void *mtl_tex);  // renderer.m

static TexBackend *tex_backend(NvnTexture *t) {
    if (t->backend) {
        TexBackend *b = (TexBackend *)t->backend;
        // reallocate when the output resolution changed, or when the guest descriptor behind this NvnTexture changed
        // (target, size, format, samples): the Metal texture no longer matches it
        bool resized = b->scalable && (b->sx != g_rs_x || b->sy != g_rs_y);
        bool redefined = b->key_target != t->target || b->key_w != t->width || b->key_h != t->height || b->key_fmt != t->format ||
                         b->key_samples != t->samples;
        if (resized || redefined) {
            release_backend_texture(t, b);
            create_backend_texture(t, b);
        }
        return b;
    }
    TexBackend *b = calloc(1, sizeof *b);
    b->scalable = tex_scalable(t);
    if (t->width == 1920 && t->height == 1080 && getenv("BDSP_LOG_SCALABLE"))
        LOG("[scale] 1920x1080 tex %p f%#x flags %#x target %u samples %u levels %u -> scalable %d (%s)\n", (void *)t, t->format,
            t->flags, t->target, t->samples, t->levels, b->scalable, t->label);
    create_backend_texture(t, b);
    t->backend = b;
    reg_add(t, b);
    return b;
}

// runtime/nvn/texpatch.c id of a texture already in use (-1: none / not identified yet)
int renderer_texpatch_of(NvnTexture *t) {
    const TexBackend *b = (const TexBackend *)t->backend;
    return b && b->tp > 0 ? b->tp - 1 : -1;
}

static void create_backend_texture(NvnTexture *t, TexBackend *b) {
    b->key_target = t->target; b->key_w = t->width; b->key_h = t->height; b->key_fmt = t->format; b->key_samples = t->samples;
    MtlFormat mf = mtl_format(t->format);
    MTLTextureDescriptor *d = [MTLTextureDescriptor new];
    d.textureType = mtl_tex_type(t->target, t->samples);
    d.pixelFormat = mf.pf;
    b->sx = b->scalable ? g_rs_x : 1;
    b->sy = b->scalable ? g_rs_y : 1;
    uint32_t tw = t->width ? t->width : 1, th = t->height ? t->height : 1;
    if (b->scalable) {
        tw = (uint32_t)lroundf(tw * b->sx); th = (uint32_t)lroundf(th * b->sy);
        if (tw < 1) tw = 1;
        if (th < 1) th = 1;
    }
    d.width = tw;
    d.height = (t->target == 0 || t->target == 3) ? 1 : th;
    d.depth = t->target == 2 ? (t->depth ? t->depth : 1) : 1;
    if (t->target == 3) d.arrayLength = t->height ? t->height : 1;
    else if (t->target == 4 || t->target == 6) d.arrayLength = t->depth ? t->depth : 1;
    else if (t->target == 9) d.arrayLength = (t->depth ? t->depth : 6) / 6;
    d.mipmapLevelCount = t->levels ? t->levels : 1;
    if (b->scalable) {
        uint32_t m = 1, sz = tw > th ? tw : th;
        while (sz > 1) { sz >>= 1; m++; }
        if (d.mipmapLevelCount > m) d.mipmapLevelCount = m;
    }
    if (t->samples > 1) { d.sampleCount = t->samples; d.mipmapLevelCount = 1; }
    d.usage = MTLTextureUsageShaderRead | MTLTextureUsagePixelFormatView | MTLTextureUsageRenderTarget |
              MTLTextureUsageShaderWrite;
    d.storageMode = MTLStorageModePrivate;
    // Shaders sample depth through ordinary texture2d bindings (Maxwell has no separate depth type);
    // keep depth uncompressed so those reads see the stored values.
    if (renderer_format_is_depth(t->format)) d.allowGPUOptimizedContents = NO;
    if (mf.force_alpha_one)
        d.swizzle = MTLTextureSwizzleChannelsMake(MTLTextureSwizzleRed, MTLTextureSwizzleGreen,
                                                  MTLTextureSwizzleBlue, MTLTextureSwizzleOne);
    id<MTLTexture> tex = [dev newTextureWithDescriptor:d];
    if (!tex) {
        LOG("[metal] texture creation failed: fmt %#x %ux%ux%u target %u\n", t->format, t->width, t->height, t->depth,
            t->target);
        d.pixelFormat = MTLPixelFormatRGBA8Unorm;
        tex = [dev newTextureWithDescriptor:d];
    }
    tex.label = [NSString stringWithFormat:@"%s fmt%#x", t->label[0] ? t->label : "tex", t->format];
    b->tex = tex;
    CFBridgingRetain(tex);
    g_tex_live++;
    g_tex_live_bytes += tex.allocatedSize;
}

static void release_backend_texture(NvnTexture *t, TexBackend *b) {  // (also drops the renderer's views of it)
    renderer_texture_gone(NULL, (__bridge void *)b->tex);
    g_tex_live--;
    g_tex_live_bytes -= b->tex.allocatedSize;
    CFBridgingRelease((__bridge CFTypeRef)b->tex);
    (void)t;
}

void backend_texture_destroyed(NvnTexture *t) {
    extern void renderer_xw_destroy_wait(void);
    renderer_xw_destroy_wait();   // worker mode: with BDSP_XW_DRAIN_DESTROY (iOS default) first wait for the enqueued work
    TexBackend *b = t->backend;
    renderer_texture_gone(t, NULL);  // its snapshot copy
    if (b) { reg_remove(b); release_backend_texture(t, b); free(b); }
    t->backend = NULL;
}

static uint64_t g_frame_counter;  // presents so far (texture change detection runs once per frame)
static uint64_t full_hash_budget, full_hash_budget_frame;

static uint64_t hash_full(const uint8_t *p, uint64_t n) {
    uint64_t h = 0x9E3779B97F4A7C15ull ^ n;
    uint64_t i = 0;
    for (; i + 8 <= n; i += 8) {
        uint64_t v;
        memcpy(&v, p + i, 8);
        h = (h ^ v) * 0x100000001B3ull;
        h ^= h >> 29;
    }
    for (; i < n; i++) h = (h ^ p[i]) * 0x100000001B3ull;
    return h;
}

static uint64_t fnv_sample(const uint8_t *p, uint64_t n) {
    // cheap change detector: hash a strided sample of the data
    uint64_t h = 1469598103934665603ull;
    uint64_t step = n > 4096 ? n / 4096 : 1;
    for (uint64_t i = 0; i < n; i += step) { h ^= p[i]; h *= 1099511628211ull; }
    return h ^ n;
}

// Upload all levels/layers from block-linear guest memory.
static void upload_texture(NvnTexture *t, TexBackend *b, id<MTLBlitCommandEncoder> blit) {
    if (!t->addr || t->target == 10) return;
    if (b->uploaded && b->checked_frame == g_frame_counter) return;  // (fast exits before any layout math)
    if (b->uploaded && !b->dynamic && ((g_frame_counter + ((uintptr_t)b >> 6)) & 7)) return;
    const FormatInfo *fi = t->layout.fmt;
    MtlFormat mf = mtl_format(t->format);
    uint64_t total = tegra_total_size(&t->layout);
    // CPU-written textures (e.g. font glyph caches) change sparsely, so a strided sample can miss
    // updates. Check at most once per frame; textures seen changing get a full hash every frame,
    // the rest a full hash on a rotating ~16 MB/frame budget plus a cheap sample otherwise.
    if (b->uploaded && b->checked_frame == g_frame_counter) return;
    // Textures that have never changed since upload (almost all: loaded from files) are re-checked every 8th
    // frame, staggered per texture; ones seen changing (glyph caches, video...) every frame.
    if (b->uploaded && !b->dynamic && ((g_frame_counter + ((uintptr_t)b >> 6)) & 7)) return;
    b->checked_frame = g_frame_counter;
    // linear textures are the CPU-written kind (the font glyph cache, 1024x2048 R8, video): checked in full every
    // frame from the start - a strided sample missed newly rasterized glyphs, so characters of new text popped in
    // seconds later (user 2026-10-08: file select "P ease se e t a i e.")
    if (t->flags & 0x10) b->dynamic = true;
    if (full_hash_budget_frame != g_frame_counter) { full_hash_budget_frame = g_frame_counter; full_hash_budget = 4 << 20; }
    const uint8_t *mem = (const uint8_t *)(uintptr_t)t->addr;
    static int always_full = -1;
    if (always_full < 0) always_full = getenv("BDSP_TEX_FULLHASH") ? 1 : 0;
    bool full = b->dynamic || !b->uploaded || always_full;
    if (!full && g_frame_counter - b->full_frame >= 120 && full_hash_budget >= total) { full = true; full_hash_budget -= total; }
    if (!b->tp) b->tp = texpatch_identify(t) + 1;  // (button prompts / Hero Mode icon: re-uploaded when their look changes)
    bool restyle = b->tp > 0 && b->uploaded && b->tp_gen != texpatch_generation();
    if (!full && !restyle) {
        uint64_t sh = fnv_sample(mem, total);
        if (sh == b->sample_hash) return;
    }
    uint64_t h = hash_full(mem, total);
    b->full_frame = g_frame_counter;
    b->sample_hash = fnv_sample(mem, total);
    if (b->uploaded && h == b->data_hash && !restyle) return;
    if (b->uploaded && h != b->data_hash) b->dynamic = true;
    if (b->tp > 0) b->tp_gen = texpatch_generation();
    b->data_hash = h;
    b->uploaded = true;
    // callers without an encoder get a private upload command buffer, created only when needed
    id<MTLCommandBuffer> own_cb = nil;
    if (!blit) { own_cb = [queue commandBuffer]; blit = [own_cb blitCommandEncoder]; }
    uint32_t layers = t->layout.layers ? t->layout.layers : 1;
    uint64_t layer_size = tegra_layer_size(&t->layout);
    bool linear = (t->flags & 0x10) != 0;
    for (uint32_t layer = 0; layer < layers; layer++) {
        for (uint32_t lv = 0; lv < t->layout.levels; lv++) {
            LevelLayout l = tegra_level(&t->layout, lv);
            uint32_t row = l.wb * fi->bpb;
            uint64_t sz = (uint64_t)row * l.hb * l.d;
            uint8_t *lin = malloc(sz);
            const uint8_t *src = (const uint8_t *)(uintptr_t)t->addr + layer * layer_size + l.offset;
            if (linear) {
                for (uint32_t y = 0; y < l.hb; y++) memcpy(lin + (uint64_t)y * row, src + y * t->stride, row);
            } else {
                tegra_deswizzle(src, lin, l.wb, l.hb, l.d, fi->bpb, l.block_height_log2, l.block_depth_log2);
            }
            if (b->tp > 0 && layer == 0) texpatch_apply(b->tp - 1, lv, lin, l.w, l.h, row);
            uint8_t *data = lin;
            uint32_t out_row = row, out_rows = l.hb;
            if (g_no_bc && bctc_kind(t->format)) {   // GPU without BC: convert the deswizzled blocks
                data = bctc_convert(t->format, lin, l.wb, l.hb, l.d, &out_row, &out_rows);
                free(lin);
                lin = data;
            }
            static int bc5log;  // BDSP_LOG_BC5: endpoint bytes of BC5 (0x4B/0x4C) textures (unorm ~128 vs snorm ~0)
            if ((t->format == 0x4B || t->format == 0x4C) && lv == 0 && bc5log < 12 && getenv("BDSP_LOG_BC5")) {
                bc5log++;
                int hist[4] = {0};
                for (uint64_t i = 0; i + 16 <= sz; i += 16) { hist[lin[i] >> 6]++; hist[lin[i + 8] >> 6]++; }
                LOG("[bc5] fmt %#x %ux%u endpoint0 quartiles (0-63,64-127,128-191,192-255): %d %d %d %d\n", t->format, l.w, l.h,
                    hist[0], hist[1], hist[2], hist[3]);
            }
            if (mf.expand_rgb && fi->bpb == 3) {  // RGB8 -> RGBA8
                uint64_t n = (uint64_t)l.wb * l.hb * l.d;
                data = malloc(n * 4);
                for (uint64_t i = 0; i < n; i++) {
                    data[i * 4] = lin[i * 3]; data[i * 4 + 1] = lin[i * 3 + 1]; data[i * 4 + 2] = lin[i * 3 + 2];
                    data[i * 4 + 3] = 255;
                }
                out_row = l.wb * 4;
                free(lin);
                lin = data;
            }
            uint64_t out_sz = (uint64_t)out_row * out_rows * l.d;
            id<MTLBuffer> staging = [dev newBufferWithBytes:data length:out_sz options:MTLResourceStorageModeShared];
            free(lin);
            // the copy stays inside the texture's level: one allocated at the internal resolution (16:9, render
            // target sized - the save slots' screenshots on the title screen) can still be filled from the CPU, and its
            // full-size data overran the scaled texture (a GPU fault on Windows: runtime/nvn/vulkan/textures.c)
            NSUInteger lw = MAX(b->tex.width >> lv, 1), lh = MAX(b->tex.height >> lv, 1), ld = MAX(b->tex.depth >> lv, 1);
            MTLSize size = MTLSizeMake(MIN((NSUInteger)l.w, lw), MIN((NSUInteger)l.h, lh), MIN((NSUInteger)l.d, ld));
            NSUInteger slice = layer;
            [blit copyFromBuffer:staging sourceOffset:0 sourceBytesPerRow:out_row
                 sourceBytesPerImage:(NSUInteger)out_row * out_rows sourceSize:size toTexture:b->tex
                    destinationSlice:slice destinationLevel:lv destinationOrigin:MTLOriginMake(0, 0, 0)];
        }
    }
    if (own_cb) { [blit endEncoding]; [own_cb commit]; }
}

id<MTLTexture> renderer_texture(NvnTexture *t, id<MTLBlitCommandEncoder> blit, bool for_render) {
    TexBackend *b = tex_backend(t);
    if (for_render) b->gpu_owned = true;
    else if (!b->gpu_owned) upload_texture(t, b, blit);
    return b->tex;
}

void renderer_mark_gpu_owned(NvnTexture *t) { tex_backend(t)->gpu_owned = true; }
bool renderer_is_gpu_owned(NvnTexture *t) { return tex_backend(t)->gpu_owned; }

void backend_pool_written(uint64_t addr, uint64_t size) { (void)addr; (void)size; }

// Host-produced texel data (decoded video): upload straight into the Metal texture.
void renderer_upload_rgba(NvnTexture *t, const void *rgba, uint32_t w, uint32_t h, uint32_t stride) {
    TexBackend *b = tex_backend(t);
    b->gpu_owned = true;
    @autoreleasepool {
        id<MTLBuffer> staging = [dev newBufferWithBytes:rgba length:(NSUInteger)stride * h options:MTLResourceStorageModeShared];
        id<MTLCommandBuffer> cb = [queue commandBuffer];
        id<MTLBlitCommandEncoder> blit = [cb blitCommandEncoder];
        [blit copyFromBuffer:staging sourceOffset:0 sourceBytesPerRow:stride sourceBytesPerImage:(NSUInteger)stride * h
                  sourceSize:MTLSizeMake(MIN(w, b->tex.width), MIN(h, b->tex.height), 1) toTexture:b->tex
            destinationSlice:0 destinationLevel:0 destinationOrigin:MTLOriginMake(0, 0, 0)];
        [blit endEncoding];
        [cb commit];
    }
}

// ================================================================== init / window
static const char *present_src =
    "#include <metal_stdlib>\n"
    "using namespace metal;\n"
    "struct V { float4 pos [[position]]; float2 uv; };\n"
    "vertex V vs(uint vid [[vertex_id]], constant float4 *pv [[buffer(0)]]) {\n"
    "  float2 p = float2((vid << 1) & 2, vid & 2);\n"
    "  V o; o.pos = float4(p * 2.0 - 1.0, 0, 1);\n"
    "  float2 uv = float2(p.x, pv[0].x > 0.5 ? p.y : 1.0 - p.y); o.uv = pv[1].xy + uv * pv[1].zw; return o; }\n"
    "fragment float4 fs(V in [[stage_in]], texture2d<float> t [[texture(0)]], sampler s [[sampler(0)]]) {\n"
    "  return float4(t.sample(s, in.uv).rgb, 1.0); }\n";

void backend_init(void) {
    while (!atomic_load(&ui_ready)) usleep(1000);
    g_no_bc = !dev.supportsBCTextureCompression || getenv("BDSP_TEST_NO_BC");
    if (g_no_bc) LOG("[metal] BC textures are converted while uploading (bctc.c)\n");
    queue = [dev newCommandQueue];
    NSError *err = nil;
    id<MTLLibrary> lib = [dev newLibraryWithSource:@(present_src) options:nil error:&err];
    if (!lib) FATAL("present shader: %s\n", err.localizedDescription.UTF8String);
    MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
    pd.vertexFunction = [lib newFunctionWithName:@"vs"];
    pd.fragmentFunction = [lib newFunctionWithName:@"fs"];
    pd.colorAttachments[0].pixelFormat = layer.pixelFormat;
    present_pipe = [dev newRenderPipelineStateWithDescriptor:pd error:&err];
    MTLSamplerDescriptor *sd = [MTLSamplerDescriptor new];
    sd.minFilter = sd.magFilter = MTLSamplerMinMagFilterLinear;
    present_sampler = [dev newSamplerStateWithDescriptor:sd];
    // Wrap the guest heap: memory pools live there, and GPU addresses are guest addresses.
    extern void nvn_glue_mem_range(void);
    nvn_glue_mem_range();
#ifdef BDSP_COMPACT_BASE
    if (HEAP_MAX > dev.maxBufferLength) {
        // A single Metal buffer must cover the guest memory, but the envelope of all mappings (a few small blocks sit far below the
        // main one) exceeds maxBufferLength on the iPhone (2 GiB). The SDK's application chunk starts at the next 2 GiB boundary of
        // the window and holds all memory pools (checked on the A13): wrap only that part.
        extern uint64_t g_nvn_mem_base, g_nvn_mem_size;
        uint64_t lo = BDSP_COMPACT_BASE + 0x80000000ull, room = dev.maxBufferLength & ~0x3FFFull;
        uint64_t hi = g_nvn_mem_base + g_nvn_mem_size;
        g_nvn_mem_base = lo;
        g_nvn_mem_size = hi - lo < room ? hi - lo : room;
        LOG("[nvn] Metal buffer clipped to the application chunk: 0x%llx + %llu MiB (limit %llu MiB)\n", (unsigned long long)lo,
            (unsigned long long)(g_nvn_mem_size >> 20), (unsigned long long)(dev.maxBufferLength >> 20));
    }
#endif
    g_guest_buffer_base = HEAP_BASE;
    g_guest_buffer = [dev newBufferWithBytesNoCopy:(void *)HEAP_BASE length:HEAP_MAX
                                           options:MTLResourceStorageModeShared deallocator:nil];
    if (!g_guest_buffer) FATAL("cannot wrap guest heap in a Metal buffer (max %llu)\n", (uint64_t)dev.maxBufferLength);
    renderer_init(dev);
#if !defined(BDSP_REBASE32) && !defined(BDSP_COMPACT_BASE)   // test with a fixed Mac guest address; not valid under the compact layouts
    if (getenv("BDSP_ASPECT_TEST")) {  // experiment: widen the game's 16:9 aspect constant
        float *k = (float *)(uintptr_t)0x70016afba4ull;
        mprotect((void *)((uintptr_t)k & ~0x3fffull), 0x4000, PROT_READ | PROT_WRITE);
        LOG("[aspect] constant %f -> %f\n", *k, (float)atof(getenv("BDSP_ASPECT_TEST")));
        *k = (float)atof(getenv("BDSP_ASPECT_TEST"));
    }
#endif
    LOG("[metal] %s, heap buffer %llu MB\n", dev.name.UTF8String, (uint64_t)HEAP_MAX >> 20);
}

id<MTLCommandQueue> renderer_queue(void) { return queue; }

// ---- in-place reboot (runtime/main.c teardown; main thread, guest threads stopped)
static NvnTexture *g_last_presented;
// Every game texture goes (the NvnTexture structs themselves are leaked: guest memory pointed at them), the
// renderer drops what is keyed by guest addresses / objects, and the heap wrapper is let go: guest memory is
// about to be replaced (backend_guest_memory_reset wraps the new pages).
void backend_reset(void) {
    if (!queue) return;  // the game never initialised NVN
    extern void renderer_reset(void);
    extern void renderer_flush(void);
    renderer_flush();  // (everything submitted has completed)
    int n = g_reg_n;
    while (g_reg_n > 0) backend_texture_destroyed(g_reg[g_reg_n - 1]);
    renderer_reset();
    g_last_presented = NULL;
    g_guest_buffer = nil;
    LOG("[metal] reboot: %d textures released (%d left alive, %.0f MB)\n", n, g_tex_live, g_tex_live_bytes / 1048576.0);
}

void backend_guest_memory_reset(void) {
    if (!queue) return;
    g_guest_buffer = [dev newBufferWithBytesNoCopy:(void *)HEAP_BASE length:HEAP_MAX
                                           options:MTLResourceStorageModeShared deallocator:nil];
    if (!g_guest_buffer) FATAL("cannot wrap guest heap in a Metal buffer\n");
}

// The window goes black while the game is down (instead of holding its last frame).
void backend_clear_window(void) {
    if (!layer || !dev) return;
    @autoreleasepool {
        id<CAMetalDrawable> drawable = [layer nextDrawable];
        if (!drawable) return;
        id<MTLCommandQueue> q = queue ? queue : [dev newCommandQueue];
        id<MTLCommandBuffer> cb = [q commandBuffer];
        MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
        rp.colorAttachments[0].texture = drawable.texture;
        rp.colorAttachments[0].loadAction = MTLLoadActionClear;
        rp.colorAttachments[0].clearColor = MTLClearColorMake(0, 0, 0, 1);
        rp.colorAttachments[0].storeAction = MTLStoreActionStore;
        [[cb renderCommandEncoderWithDescriptor:rp] endEncoding];
        [cb presentDrawable:drawable];
        [cb commit];
        [cb waitUntilCompleted];
    }
}

// ================================================================== screenshots
#import <ImageIO/ImageIO.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>

void renderer_save_texture(id<MTLTexture> tex, const char *path);
bool dbg_thread_enabled(void);                                    // debug_thread.c
void dbg_thread_submit(void (*fn)(void *), void *arg);
void dbg_thread_drain(void);

// Scanout shows the bytes the game wrote: sample sRGB textures through a non-sRGB view so the
// present/screenshot shaders pass them through instead of decoding to linear.
static id<MTLTexture> raw_view(id<MTLTexture> t) {
    MTLPixelFormat pf = t.pixelFormat;
    MTLPixelFormat raw = pf == MTLPixelFormatRGBA8Unorm_sRGB ? MTLPixelFormatRGBA8Unorm
                       : pf == MTLPixelFormatBGRA8Unorm_sRGB ? MTLPixelFormatBGRA8Unorm : pf;
    if (raw == pf) return t;
    id<MTLTexture> v = [t newTextureViewWithPixelFormat:raw];
    return v ? v : t;
}

static void save_png(id<MTLTexture> tex, const char *path) { renderer_save_texture(tex, path); }

// MetalFX spatial upscaling (Video tab "Upscaler" = MetalFX). metalfx_upscale() decides (and sets up the scaler for
// this input / output size); metalfx_encode() runs it and returns the upscaled image.
static id<MTLFXSpatialScaler> g_fx;
static id<MTLTexture> g_fx_out;
static NSUInteger g_fx_iw, g_fx_ih, g_fx_ow, g_fx_oh;
static MTLPixelFormat g_fx_fmt;
static id<MTLTexture> metalfx_upscale(id<MTLCommandBuffer> cb, id<MTLTexture> in, double ow_d, double oh_d) {
    (void)cb;
    if (g_settings.upscaler != UPSCALE_METALFX) return nil;
    static int supported = -1;
    if (supported < 0) {
        supported = [MTLFXSpatialScalerDescriptor supportsDevice:dev] ? 1 : 0;
        LOG("[metalfx] spatial scaler %s\n", supported ? "available" : "not supported on this GPU");
    }
    if (!supported) return nil;
    NSUInteger ow = (NSUInteger)lround(ow_d), oh = (NSUInteger)lround(oh_d);
    if (ow <= in.width + 1 && oh <= in.height + 1) return nil;  // not an upscale: plain sampling is right
    if (ow > 16384) ow = 16384;
    if (oh > 16384) oh = 16384;
    if (!g_fx || g_fx_iw != in.width || g_fx_ih != in.height || g_fx_ow != ow || g_fx_oh != oh || g_fx_fmt != in.pixelFormat) {
        MTLFXSpatialScalerDescriptor *d = [MTLFXSpatialScalerDescriptor new];
        d.inputWidth = in.width; d.inputHeight = in.height;
        d.outputWidth = ow; d.outputHeight = oh;
        d.colorTextureFormat = in.pixelFormat;
        d.outputTextureFormat = in.pixelFormat;
        d.colorProcessingMode = MTLFXSpatialScalerColorProcessingModePerceptual;  // (gamma-encoded 8-bit image)
        g_fx = [d newSpatialScalerWithDevice:dev];
        MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:in.pixelFormat width:ow height:oh mipmapped:NO];
        td.usage = g_fx ? g_fx.outputTextureUsage | MTLTextureUsageShaderRead : MTLTextureUsageShaderRead;
        td.storageMode = MTLStorageModePrivate;
        g_fx_out = [dev newTextureWithDescriptor:td];
        g_fx_iw = in.width; g_fx_ih = in.height; g_fx_ow = ow; g_fx_oh = oh; g_fx_fmt = in.pixelFormat;
        LOG("[metalfx] %lux%lu -> %lux%lu (%s)\n", (unsigned long)in.width, (unsigned long)in.height, (unsigned long)ow,
            (unsigned long)oh, g_fx ? "ok" : "FAILED");
    }
    return g_fx && g_fx_out ? g_fx_out : nil;
}
// SMAA 1x (Video tab "Anti-aliasing"; third_party/smaa, MIT; as runtime/nvn/vulkan/shaders.c / exec.c): luma edges ->
// blending weights -> neighbourhood blending, at the game image's size, before the present / MetalFX. The reference
// SMAA.hlsl has no Metal mode: it is built through its SMAA_CUSTOM_SL porting macros, with a few textual fixes for
// MSL (out / inout parameters and array parameters as references, no swizzles bound to them, no discard in a
// helper). The render-target size is a literal in the source (SMAA's preferred form): the library is compiled for
// each new image size, on first use - a problem there is logged once and turns SMAA off. Metal's texture origin is
// top-left, as SMAA expects.
static NSString *smaa_msl(NSUInteger w, NSUInteger h) {
    extern const char smaa_hlsl_src[];
    NSMutableString *s = [NSMutableString stringWithUTF8String:smaa_hlsl_src];
    struct { const char *from, *to; } fix[] = {
        {"inout float2 variable", "thread float2 &variable"},
        {"inout float4 variable", "thread float4 &variable"},
        {"SMAAMovc(cond.xy, variable.xy, value.xy);", "variable = select(variable, value, cond);"},
        {"SMAAMovc(cond.zw, variable.zw, value.zw);", ""},
        {"out float4 offset[3]", "thread float4 (&offset)[3]"},
        {"float4 offset[3]", "thread float4 (&offset)[3]"},
        {"thread thread float4 (&offset)[3]", "thread float4 (&offset)[3]"},
        {"out float2 pixcoord", "thread float2 &pixcoord"},
        {"out float4 offset)", "thread float4 &offset)"},
        {"out float2 e)", "thread float2 &e)"},
        {"inout float2 weights", "thread float2 &weights"},
        {"SMAADetectHorizontalCornerPattern(SMAATexturePass2D(edgesTex), weights.rg, coords.xyzy, d);",
         "{ float2 w_ = weights.rg; SMAADetectHorizontalCornerPattern(SMAATexturePass2D(edgesTex), w_, coords.xyzy, d); weights.rg = w_; }"},
        {"SMAADetectVerticalCornerPattern(SMAATexturePass2D(edgesTex), weights.ba, coords.xyxz, d);",
         "{ float2 w_ = weights.ba; SMAADetectVerticalCornerPattern(SMAATexturePass2D(edgesTex), w_, coords.xyxz, d); weights.ba = w_; }"},
        {"        discard;", "        return float2(0.0, 0.0);"},
    };
    for (size_t i = 0; i < sizeof fix / sizeof fix[0]; i++)
        [s replaceOccurrencesOfString:@(fix[i].from) withString:@(fix[i].to) options:0 range:NSMakeRange(0, s.length)];
    NSString *head = [NSString stringWithFormat:
        @"#include <metal_stdlib>\n"
        "using namespace metal;\n"
        "#define SMAA_CUSTOM_SL\n"
        "#define SMAA_PRESET_HIGH\n"
        "#define SMAA_RT_METRICS float4(%.9g, %.9g, %.1f, %.1f)\n"
        "constexpr sampler LinearSampler(filter::linear, address::clamp_to_edge);\n"
        "constexpr sampler PointSampler(filter::nearest, address::clamp_to_edge);\n"
        "#define SMAATexture2D(tex) texture2d<float> tex\n"
        "#define SMAATexturePass2D(tex) tex\n"
        "#define SMAASampleLevelZero(tex, coord) tex.sample(LinearSampler, coord, level(0.0))\n"
        "#define SMAASampleLevelZeroPoint(tex, coord) tex.sample(PointSampler, coord, level(0.0))\n"
        "#define SMAASampleLevelZeroOffset(tex, coord, offset) tex.sample(LinearSampler, coord, level(0.0), offset)\n"
        "#define SMAASample(tex, coord) tex.sample(LinearSampler, coord)\n"
        "#define SMAASamplePoint(tex, coord) tex.sample(PointSampler, coord)\n"
        "#define SMAASampleOffset(tex, coord, offset) tex.sample(LinearSampler, coord, offset)\n"
        "#define SMAA_FLATTEN\n"
        "#define SMAA_BRANCH\n"
        "#define lerp(a, b, t) mix(a, b, t)\n"
        "#define mad(a, b, c) fma(a, b, c)\n",
        1.0 / w, 1.0 / h, (double)w, (double)h];
    NSString *tail =
        @"struct V { float4 pos [[position]]; };\n"
        "vertex V smaa_vs(uint vid [[vertex_id]]) {\n"
        "  float2 p = float2((vid << 1) & 2, vid & 2);\n"
        "  V o; o.pos = float4(p * 2.0 - 1.0, 0, 1); return o; }\n"
        "fragment float4 smaa_edge(V in [[stage_in]], texture2d<float> t0 [[texture(0)]]) {\n"
        "  float2 uv = in.pos.xy * SMAA_RT_METRICS.xy;\n"
        "  float4 off[3];\n"
        "  SMAAEdgeDetectionVS(uv, off);\n"
        "  return float4(SMAALumaEdgeDetectionPS(uv, off, t0), 0.0, 0.0); }\n"
        "fragment float4 smaa_weight(V in [[stage_in]], texture2d<float> t0 [[texture(0)]], texture2d<float> t1 [[texture(1)]],\n"
        "                            texture2d<float> t2 [[texture(2)]]) {\n"
        "  float2 uv = in.pos.xy * SMAA_RT_METRICS.xy, pix;\n"
        "  float4 off[3];\n"
        "  SMAABlendingWeightCalculationVS(uv, pix, off);\n"
        "  return SMAABlendingWeightCalculationPS(uv, pix, off, t0, t1, t2, float4(0.0)); }\n"
        "fragment float4 smaa_blend(V in [[stage_in]], texture2d<float> t0 [[texture(0)]], texture2d<float> t1 [[texture(1)]]) {\n"
        "  float2 uv = in.pos.xy * SMAA_RT_METRICS.xy;\n"
        "  float4 off;\n"
        "  SMAANeighborhoodBlendingVS(uv, off);\n"
        "  return float4(SMAANeighborhoodBlendingPS(uv, off, t0, t1).rgb, 1.0); }\n";
    return [NSString stringWithFormat:@"%@%@%@", head, s, tail];
}

static id<MTLTexture> smaa_target(id<MTLTexture> old, NSUInteger w, NSUInteger h, MTLPixelFormat f) {
    if (old && old.width == w && old.height == h && old.pixelFormat == f) return old;
    MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:f width:w height:h mipmapped:NO];
    td.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
    td.storageMode = MTLStorageModePrivate;
    return [dev newTextureWithDescriptor:td];
}

static void smaa_pass(id<MTLCommandBuffer> cb, id<MTLRenderPipelineState> p, id<MTLTexture> dst, bool clear,
                      id<MTLTexture> t0, id<MTLTexture> t1, id<MTLTexture> t2) {
    MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
    rp.colorAttachments[0].texture = dst;
    rp.colorAttachments[0].loadAction = clear ? MTLLoadActionClear : MTLLoadActionDontCare;
    rp.colorAttachments[0].clearColor = MTLClearColorMake(0, 0, 0, 0);
    rp.colorAttachments[0].storeAction = MTLStoreActionStore;
    id<MTLRenderCommandEncoder> e = [cb renderCommandEncoderWithDescriptor:rp];
    [e setRenderPipelineState:p];
    [e setFragmentTexture:t0 atIndex:0];
    if (t1) [e setFragmentTexture:t1 atIndex:1];
    if (t2) [e setFragmentTexture:t2 atIndex:2];
    [e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
    [e endEncoding];
}

static id<MTLTexture> smaa_encode(id<MTLCommandBuffer> cb, id<MTLTexture> in) {
    static bool failed;  // (shader / pipeline error: logged once, SMAA stays off)
    static NSUInteger lw, lh;
    static MTLPixelFormat lf;
    static id<MTLRenderPipelineState> pe, pw, pb;
    static id<MTLTexture> area, search, edges, weights, out;
    if (failed) return in;
    if (!area) {  // the lookup textures (runtime/nvn/smaa_data.c), uploaded once
        extern const unsigned char *smaa_area_tex(void);
        extern const unsigned char *smaa_search_tex(void);
        MTLTextureDescriptor *ad = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRG8Unorm width:160 height:560 mipmapped:NO];
        area = [dev newTextureWithDescriptor:ad];
        [area replaceRegion:MTLRegionMake2D(0, 0, 160, 560) mipmapLevel:0 withBytes:smaa_area_tex() bytesPerRow:160 * 2];
        MTLTextureDescriptor *sd = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatR8Unorm width:64 height:16 mipmapped:NO];
        search = [dev newTextureWithDescriptor:sd];
        [search replaceRegion:MTLRegionMake2D(0, 0, 64, 16) mipmapLevel:0 withBytes:smaa_search_tex() bytesPerRow:64];
    }
    if (!pe || lw != in.width || lh != in.height || lf != in.pixelFormat) {
        NSError *err = nil;
        id<MTLLibrary> lib = [dev newLibraryWithSource:smaa_msl(in.width, in.height) options:nil error:&err];
        if (!lib) { LOG("[smaa] shader: %s\n", err.localizedDescription.UTF8String); failed = true; return in; }
        MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
        pd.vertexFunction = [lib newFunctionWithName:@"smaa_vs"];
        pd.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
        pd.fragmentFunction = [lib newFunctionWithName:@"smaa_edge"];
        pe = [dev newRenderPipelineStateWithDescriptor:pd error:&err];
        pd.fragmentFunction = [lib newFunctionWithName:@"smaa_weight"];
        pw = pe ? [dev newRenderPipelineStateWithDescriptor:pd error:&err] : nil;
        pd.fragmentFunction = [lib newFunctionWithName:@"smaa_blend"];
        pd.colorAttachments[0].pixelFormat = in.pixelFormat;
        pb = pw ? [dev newRenderPipelineStateWithDescriptor:pd error:&err] : nil;
        if (!pb) { LOG("[smaa] pipeline: %s\n", err.localizedDescription.UTF8String); failed = true; return in; }
        lw = in.width; lh = in.height; lf = in.pixelFormat;
        LOG("[smaa] %lux%lu\n", (unsigned long)in.width, (unsigned long)in.height);
    }
    edges = smaa_target(edges, in.width, in.height, MTLPixelFormatRGBA8Unorm);
    weights = smaa_target(weights, in.width, in.height, MTLPixelFormatRGBA8Unorm);
    out = smaa_target(out, in.width, in.height, in.pixelFormat);
    smaa_pass(cb, pe, edges, true, in, nil, nil);
    smaa_pass(cb, pw, weights, true, edges, area, search);
    smaa_pass(cb, pb, out, false, in, weights, nil);
    return out;
}

static id<MTLTexture> metalfx_encode(id<MTLCommandBuffer> cb, id<MTLTexture> in) {
    g_fx.colorTexture = in;
    g_fx.inputContentWidth = in.width;
    g_fx.inputContentHeight = in.height;
    g_fx.outputTexture = g_fx_out;
    [g_fx encodeToCommandBuffer:cb];
    return g_fx_out;
}



// Debug: dump an 8-bit-per-channel 2D texture's raw bytes (alpha kept, written as a separate grey PNG).
void renderer_save_texture_alpha(id<MTLTexture> tex, const char *path) {
    if (tex.pixelFormat != MTLPixelFormatRGBA8Unorm && tex.pixelFormat != MTLPixelFormatRGBA8Unorm_sRGB &&
        tex.pixelFormat != MTLPixelFormatBGRA8Unorm)
        return;
    NSUInteger w = tex.width, h = tex.height;
    id<MTLBuffer> buf = [dev newBufferWithLength:w * h * 4 options:MTLResourceStorageModeShared];
    id<MTLCommandBuffer> cb = [queue commandBuffer];
    id<MTLBlitCommandEncoder> b = [cb blitCommandEncoder];
    [b copyFromTexture:tex sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0) sourceSize:MTLSizeMake(w, h, 1)
              toBuffer:buf destinationOffset:0 destinationBytesPerRow:w * 4 destinationBytesPerImage:w * h * 4];
    [b endEncoding];
    [cb commit];
    [cb waitUntilCompleted];
    const uint8_t *px = buf.contents;
    uint8_t *a = malloc(w * h);
    unsigned amax = 0;
    for (NSUInteger i = 0; i < w * h; i++) { a[i] = px[i * 4 + 3]; if (a[i] > amax) amax = a[i]; }
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceGray();
    CGContextRef ctx = CGBitmapContextCreate(a, w, h, 8, w, cs, kCGImageAlphaNone);
    CGImageRef img = CGBitmapContextCreateImage(ctx);
    CFURLRef url = CFURLCreateFromFileSystemRepresentation(NULL, (const UInt8 *)path, strlen(path), false);
    CGImageDestinationRef dest = CGImageDestinationCreateWithURL(url, (__bridge CFStringRef)UTTypePNG.identifier, 1, NULL);
    if (dest) {  // (NULL: the folder isn't there)
        CGImageDestinationAddImage(dest, img, NULL);
        CGImageDestinationFinalize(dest);
        CFRelease(dest);
    }
    CFRelease(url); CGImageRelease(img); CGContextRelease(ctx); CGColorSpaceRelease(cs);
    free(a);
    LOG("[metal] saved alpha %s (%lux%lu, max %u)\n", path, (unsigned long)w, (unsigned long)h, amax);
}
static float g_shot_crop[4] = {0, 0, 1, 1};  // presented crop of the current frame (screenshots match it)
static bool g_save_upright;  // (set around saves of the window image: test shots under any name)
static void save_texture_now(id<MTLTexture> tex, const char *path, const float *crop_in, bool upright) {
    NSUInteger w = tex.width, h = tex.height;
    float shot_crop[4] = {0, 0, 1, 1};
    if (strstr(path, "frame_")) {
        memcpy(shot_crop, crop_in, sizeof shot_crop);
        w = (NSUInteger)(w * shot_crop[2]); h = (NSUInteger)(h * shot_crop[3]);
    }
    MTLTextureDescriptor *d = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
                                                                                 width:w height:h mipmapped:NO];
    d.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
    d.storageMode = MTLStorageModeShared;
    id<MTLTexture> dst = [dev newTextureWithDescriptor:d];
    id<MTLCommandBuffer> cb = [queue commandBuffer];
    MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
    rp.colorAttachments[0].texture = dst;
    rp.colorAttachments[0].loadAction = MTLLoadActionClear;
    rp.colorAttachments[0].storeAction = MTLStoreActionStore;
    static id<MTLRenderPipelineState> pipe;
    if (!pipe) {
        MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
        id<MTLLibrary> lib = [dev newLibraryWithSource:@(present_src) options:nil error:nil];
        pd.vertexFunction = [lib newFunctionWithName:@"vs"];
        pd.fragmentFunction = [lib newFunctionWithName:@"fs"];
        pd.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
        pipe = [dev newRenderPipelineStateWithDescriptor:pd error:nil];
    }
    id<MTLRenderCommandEncoder> e = [cb renderCommandEncoderWithDescriptor:rp];
    float flip = renderer_origin_lower_left() ? 1.0f : 0.0f;
    [e setRenderPipelineState:pipe];
    if (upright || strstr(path, "window")) flip = 0;  // the window image is already upright
    float pv[8] = {flip, 0, 0, 0, shot_crop[0], shot_crop[1], shot_crop[2], shot_crop[3]};
    [e setVertexBytes:pv length:sizeof pv atIndex:0];
    [e setFragmentTexture:raw_view(tex) atIndex:0];
    [e setFragmentSamplerState:present_sampler atIndex:0];
    [e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
    [e endEncoding];
    [cb commit];
    [cb waitUntilCompleted];
    uint8_t *px = malloc(w * h * 4);
    [dst getBytes:px bytesPerRow:w * 4 fromRegion:MTLRegionMake2D(0, 0, w, h) mipmapLevel:0];
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
    CGContextRef ctx = CGBitmapContextCreate(px, w, h, 8, w * 4, cs, kCGImageAlphaPremultipliedLast);
    CGImageRef img = CGBitmapContextCreateImage(ctx);
    CFURLRef url = CFURLCreateFromFileSystemRepresentation(NULL, (const UInt8 *)path, strlen(path), false);
    CGImageDestinationRef dest = CGImageDestinationCreateWithURL(url, (__bridge CFStringRef)UTTypePNG.identifier, 1, NULL);
    if (dest) {  // (NULL: the folder isn't there)
        CGImageDestinationAddImage(dest, img, NULL);
        CGImageDestinationFinalize(dest);
        CFRelease(dest);
    }
    CFRelease(url); CGImageRelease(img); CGContextRelease(ctx); CGColorSpaceRelease(cs);
    free(px);
    LOG("[metal] saved %s (%lux%lu)\n", path, (unsigned long)w, (unsigned long)h);
}

// BDSP_DEBUG_THREAD=1 (debug_thread.c): the render thread only copies the image on the GPU queue (no wait); reading it back,
// encoding the PNG and writing the file run on the debug thread.
typedef struct { void *tex;  /* retained id<MTLTexture> (ARC forbids object pointers in C structs) */ char path[256]; float crop[4]; bool upright; } ShotJob;
static void shot_job_run(void *p) {
    ShotJob *j = p;
    @autoreleasepool {
        id<MTLTexture> t = CFBridgingRelease(j->tex);
        save_texture_now(t, j->path, j->crop, j->upright);
    }
    free(j);
}
void renderer_save_texture(id<MTLTexture> tex, const char *path) {
    if (dbg_thread_enabled() && tex.textureType == MTLTextureType2D && tex.sampleCount == 1 && strlen(path) < 256) {
        MTLTextureDescriptor *d = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:tex.pixelFormat
                                                                                     width:tex.width height:tex.height mipmapped:NO];
        d.usage = MTLTextureUsageShaderRead | MTLTextureUsagePixelFormatView;
        d.storageMode = MTLStorageModePrivate;
        id<MTLTexture> copy = [dev newTextureWithDescriptor:d];
        if (copy) {
            id<MTLCommandBuffer> cb = [queue commandBuffer];
            id<MTLBlitCommandEncoder> bl = [cb blitCommandEncoder];
            [bl copyFromTexture:tex toTexture:copy];
            [bl endEncoding];
            [cb commit];
            ShotJob *j = calloc(1, sizeof *j);
            j->tex = (void *)CFBridgingRetain(copy);
            snprintf(j->path, sizeof j->path, "%s", path);
            memcpy(j->crop, g_shot_crop, sizeof j->crop);
            j->upright = g_save_upright;
            dbg_thread_submit(shot_job_run, j);
            return;
        }
    }
    save_texture_now(tex, path, g_shot_crop, g_save_upright);
}

// ================================================================== present

static double last_fps_time;

void backend_present(NvnTexture *t);
// Present the last frame again (the game thread waits in a host dialog, e.g. the software keyboard): the overlay
// keeps drawing and taking input.
void backend_represent(void) {
    if (g_last_presented) backend_present(g_last_presented);
    else SDL_Delay(16);
}

// BDSP_FLICKER=1 (diagnosis): per frame brightness and pixel changes against the predecessor (whole game image, before menu and
// scaling) plus the interval of the presentedTime. Separates pacing (pattern in dt) from shader flicker (dpix in a calm scene).
static NSMutableDictionary *flicker_capture(id<MTLCommandBuffer> cb, id<MTLTexture> tex, uint64_t frame, uint64_t draws, uint64_t skipped) {
    if (!tex || tex.sampleCount != 1 || tex.textureType != MTLTextureType2D) return nil;
    MTLPixelFormat pf = tex.pixelFormat;
    if (pf != MTLPixelFormatRGBA8Unorm && pf != MTLPixelFormatRGBA8Unorm_sRGB && pf != MTLPixelFormatBGRA8Unorm &&
        pf != MTLPixelFormatBGRA8Unorm_sRGB) return nil;
    MTLTextureDescriptor *d = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:pf width:tex.width height:tex.height mipmapped:NO];
    d.storageMode = MTLStorageModeShared;
    d.usage = MTLTextureUsageShaderRead;
    id<MTLTexture> copy = [dev newTextureWithDescriptor:d];
    if (!copy) return nil;
    id<MTLBlitCommandEncoder> bl = [cb blitCommandEncoder];
    [bl copyFromTexture:tex toTexture:copy];
    [bl endEncoding];
    NSMutableDictionary *rec = [NSMutableDictionary dictionary];
    bool bgra = pf == MTLPixelFormatBGRA8Unorm || pf == MTLPixelFormatBGRA8Unorm_sRGB;
    [cb addCompletedHandler:^(id<MTLCommandBuffer> done) {
        (void)done;
        static NSMutableData *prev;
        static NSLock *lk;
        static dispatch_once_t once;
        dispatch_once(&once, ^{ lk = [NSLock new]; });
        size_t w = copy.width, h = copy.height, n = w * h;
        NSMutableData *cur = [NSMutableData dataWithLength:n * 4];
        [copy getBytes:cur.mutableBytes bytesPerRow:w * 4 fromRegion:MTLRegionMake2D(0, 0, w, h) mipmapLevel:0];
        const uint8_t *c = cur.bytes;
        [lk lock];
        const uint8_t *p = prev.length == cur.length ? prev.bytes : NULL;
        double sum = 0, dsum = 0;
        unsigned dpix = 0, dark = 0, ddark = 0, dmax = 0;
        for (size_t i = 0; i < n; i++) {
            const uint8_t *q = c + i * 4;
            int r = bgra ? q[2] : q[0], g = q[1], b = bgra ? q[0] : q[2];
            int y = (r * 54 + g * 183 + b * 19) >> 8;
            sum += y;
            if (y < 64) dark++;
            if (p) {
                const uint8_t *o = p + i * 4;
                int m = abs(q[0] - o[0]);
                int m1 = abs(q[1] - o[1]), m2 = abs(q[2] - o[2]);
                if (m1 > m) m = m1;
                if (m2 > m) m = m2;
                if (m) { dpix++; dsum += m; if ((unsigned)m > dmax) dmax = (unsigned)m; if (y < 64) ddark++; }
            }
        }
        prev = cur;
        [lk unlock];
        @synchronized(rec) {
            rec[@"line"] = [NSString stringWithFormat:@"f%llu draws %llu skip %llu mean %.3f dpix %u (dunkel %u von %u) dmax %u dmean %.2f",
                            (unsigned long long)frame, (unsigned long long)draws, (unsigned long long)skipped, sum / n, dpix, ddark, dark, dmax, dpix ? dsum / dpix : 0.0];
            if (rec[@"pt"]) LOG("[flicker] %s dt %.2fms\n", [rec[@"line"] UTF8String], [rec[@"pt"] doubleValue]);
        }
    }];
    return rec;
}
static void flicker_presented(NSMutableDictionary *rec, double pt) {
    static double prev;
    double dt = prev > 0 ? (pt - prev) * 1000 : 0;
    if (pt > 0) prev = pt;
    @synchronized(rec) {
        rec[@"pt"] = @(dt);
        if (rec[@"line"]) LOG("[flicker] %s dt %.2fms\n", [rec[@"line"] UTF8String], dt);
    }
}

// Experiment (BDSP_XW_GPU_LAG=<n>, off by default): the worker waits until the GPU has finished the frame presented n frames earlier,
// so the guest cannot run more than n + BDSP_EXEC_FRAMES frames ahead of the GPU (the Switch GPU is at most 2 to 3 frames behind).
static id<MTLCommandBuffer> g_present_cb;
static void xw_gpu_lag(void) {
    static int lag = -1;
    static id<MTLCommandBuffer> hist[8];
    static uint64_t n;
    if (lag < 0) lag = getenv("BDSP_XW_GPU_LAG") ? atoi(getenv("BDSP_XW_GPU_LAG")) : 0;
    if (lag <= 0 || lag > 7) return;
    hist[n++ % 8] = g_present_cb;
    if (n > (uint64_t)lag) [hist[(n - 1 - lag) % 8] waitUntilCompleted];
}

// GPU part of the presentation (commits the frame work, gets the drawable, encodes the present pass). Runs in the guest thread
// or (BDSP_EXEC_WORKER=1) in the translation worker; therefore only with values that were captured when enqueueing.
// false: no drawable, the frame is dropped.
static bool present_gpu_locked(uint64_t frame, id<MTLTexture> tex, bool has_wc, const float wc[4], bool repeat);
// Last presented game image, kept so that the on-screen keyboard can keep the window alive while the game itself is stopped in the
// keyboard call (the guest thread does not present then). metal_repeat_present draws that image again, with the overlay on top.
static pthread_mutex_t g_present_lock = PTHREAD_MUTEX_INITIALIZER;
static id<MTLTexture> g_rep_tex;
static bool g_rep_has_wc;
static float g_rep_wc[4];
static uint64_t g_rep_frame;
static _Atomic uint64_t g_last_present_ns;
// The on-screen keyboard blurs the game image once; the drawables must be readable for that while it is open.
void metal_set_sampleable(int on) { layer.framebufferOnly = (on || getenv("BDSP_WINDOW_SHOT")) ? NO : YES; }
uint64_t metal_now_ns(void) { return SDL_GetTicksNS(); }   // the clock of metal_last_present_ns (SDL is not linked on iOS)
uint64_t metal_last_present_ns(void) { return atomic_load(&g_last_present_ns); }
static bool present_gpu(uint64_t frame, id<MTLTexture> tex, bool has_wc, const float wc[4]) {
    pthread_mutex_lock(&g_present_lock);
    bool ok = present_gpu_locked(frame, tex, has_wc, wc, false);
    if (ok) {
        g_rep_tex = tex; g_rep_has_wc = has_wc; g_rep_frame = frame;
        if (has_wc) memcpy(g_rep_wc, wc, sizeof g_rep_wc);
        atomic_store(&g_last_present_ns, SDL_GetTicksNS());
    }
    pthread_mutex_unlock(&g_present_lock);
    return ok;
}
void metal_repeat_present(void) {
    pthread_mutex_lock(&g_present_lock);
    if (g_rep_tex) present_gpu_locked(g_rep_frame, g_rep_tex, g_rep_has_wc, g_rep_wc, true);
    pthread_mutex_unlock(&g_present_lock);
}
static bool present_gpu_locked(uint64_t frame, id<MTLTexture> tex, bool has_wc, const float wc[4], bool repeat) {
    extern void renderer_submit(void);
    if (!repeat) renderer_submit();  // same queue: the present pass runs after the frame's work
    @autoreleasepool {
        uint64_t nd0 = SDL_GetTicksNS();
        id<CAMetalDrawable> drawable = [layer nextDrawable];
        uint64_t nd = SDL_GetTicksNS() - nd0;
        if (nd > 30000000) {
            static int warned;
            if (warned++ < 20) LOG("[metal] nextDrawable blocked %llums\n", (unsigned long long)(nd / 1000000));
        }
        if (!drawable) return false;
        id<MTLCommandBuffer> cb = [queue commandBuffer];
        MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
        rp.colorAttachments[0].texture = drawable.texture;
        rp.colorAttachments[0].loadAction = MTLLoadActionClear;
        rp.colorAttachments[0].clearColor = MTLClearColorMake(0, 0, 0, 1);
        rp.colorAttachments[0].storeAction = MTLStoreActionStore;
        id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:rp];
        // Next frame's render resolution follows the window: the 1920x1080 image scaled to fit.
        double dw = drawable.texture.width, dh = drawable.texture.height;
        extern void widescreen_frame_end(uint64_t frame);
        widescreen_frame_end(frame);
        extern void widescreen_set_factor(float f);
        extern bool widescreen_allowed(void);
        // render scale + placement in the window: runtime/nvn/output_scale.c (Video tab "Internal resolution")
        extern uint64_t g_gpu_total_ns;
        static uint64_t gpu_prev;
        uint64_t gpu_now = __atomic_load_n(&g_gpu_total_ns, __ATOMIC_RELAXED);
        double gpu_ms = gpu_prev ? (gpu_now - gpu_prev) / 1e6 : -1;
        gpu_prev = gpu_now;
        OutScale os;
        output_scale(dw, dh, widescreen_allowed(), SDL_GetTicksNS() / 1e9, gpu_ms, &os);
        double sx = os.sx, sy = os.sy, vx = os.vx, vy = os.vy, vw = os.vw, vh = os.vh, shape = os.shape;
        bool reshape = shape != 1.0;
        // interiors / dungeons: their 16:9 centre, or the part inside a room wider than one screen
        extern void widescreen_present_crop(uint64_t, double, float *, double *, double *, double *, double *);
        float crop[4];  // uv origin and size
        widescreen_present_crop(frame, shape, crop, &vx, &vy, &vw, &vh);
        if (has_wc) memcpy(crop, wc, sizeof crop);  // the crop set by the game (nvnWindowSetCrop), captured when enqueueing
        widescreen_set_factor((float)shape);
        {   // (diagnostics) log output scale / drawable changes
            static double psx, psy, pdw, pdh;
            static int nlog;
            if ((sx != psx || sy != psy || dw != pdw || dh != pdh) && nlog++ < 200)
                LOG("[scale] frame %llu drawable %.0fx%.0f -> render scale %.3fx%.3f (reshape %d)\n",
                    (unsigned long long)frame, dw, dh, sx, sy, reshape);
            psx = sx, psy = sy, pdw = dw, pdh = dh;
        }
        renderer_set_scale((float)sx, (float)sy);
        if (tex) {
            id<MTLTexture> src = raw_view(tex);
            // SMAA (Video tab "Anti-aliasing"): first, at the game image's size (MetalFX then upscales its result)
            if (g_settings.antialias == AA_SMAA) {
                [enc endEncoding];
                src = smaa_encode(cb, src);
                MTLRenderPassDescriptor *rp2 = [MTLRenderPassDescriptor renderPassDescriptor];
                rp2.colorAttachments[0].texture = drawable.texture;
                rp2.colorAttachments[0].loadAction = MTLLoadActionLoad;
                rp2.colorAttachments[0].storeAction = MTLStoreActionStore;
                enc = [cb renderCommandEncoderWithDescriptor:rp2];
            }
            // MetalFX (Video tab "Upscaler"): when the game image is smaller than its place in the window, Apple's
            // spatial upscaler brings it to the window's size first (the whole image, so the interior crop below
            // still applies); the present pass then samples it about 1:1. Its own pass: the drawable's pass is
            // ended and resumed (load) around it.
            id<MTLTexture> up = metalfx_upscale(cb, src, vw / crop[2], vh / crop[3]);
            if (up) {
                [enc endEncoding];
                up = metalfx_encode(cb, src);
                MTLRenderPassDescriptor *rp2 = [MTLRenderPassDescriptor renderPassDescriptor];
                rp2.colorAttachments[0].texture = drawable.texture;
                rp2.colorAttachments[0].loadAction = MTLLoadActionLoad;
                rp2.colorAttachments[0].storeAction = MTLStoreActionStore;
                enc = [cb renderCommandEncoderWithDescriptor:rp2];
                src = up;
            }
            float flip = renderer_origin_lower_left() ? 1.0f : 0.0f;
            [enc setViewport:(MTLViewport){vx, vy, vw, vh, 0, 1}];
            [enc setRenderPipelineState:present_pipe];
            float pv[8] = {flip, 0, 0, 0, crop[0], crop[1], crop[2], crop[3]};
            memcpy(g_shot_crop, crop, sizeof crop);
            [enc setVertexBytes:pv length:sizeof pv atIndex:0];
            [enc setFragmentTexture:src atIndex:0];
            [enc setFragmentSamplerState:present_sampler atIndex:0];
            [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
        }
        [enc endEncoding];
        static long menu_at = -1;  // test hook: open the menu at this frame (BDSP_MENU_AT)
        if (menu_at < 0) menu_at = getenv("BDSP_MENU_AT") ? atol(getenv("BDSP_MENU_AT")) : 0;
        if (menu_at && (long)frame + 1 == menu_at) { extern void menu_test_open(void); menu_test_open(); }
        menu_render(dev, cb, drawable.texture);
        static int flick = -1;
        if (flick < 0) flick = getenv("BDSP_FLICKER") != NULL;
        NSMutableDictionary *frec = nil;
        if (flick) {
            extern void renderer_draw_counts(uint64_t *draws, uint64_t *skipped);
            static uint64_t pd, ps;
            uint64_t d, s;
            renderer_draw_counts(&d, &s);
            frec = flicker_capture(cb, tex, frame, d >= pd ? d - pd : d, s >= ps ? s - ps : s);
            pd = d; ps = s;
        }
        if (frec) [drawable addPresentedHandler:^(id<MTLDrawable> d) { flicker_presented(frec, d.presentedTime); }];
        static long win_shot = -1;  // BDSP_WINDOW_SHOT=<frame>: save the final window image (game + menu)
        if (win_shot < 0) win_shot = getenv("BDSP_WINDOW_SHOT") ? atol(getenv("BDSP_WINDOW_SHOT")) : 0;
        id<MTLTexture> shot_tex = nil;
        extern char g_window_shot_request[256];  // test hooks (runtime/hle/hookshot.c): save the next frame here
        if ((win_shot && (long)frame + 1 == win_shot) || g_window_shot_request[0]) {
            MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:drawable.texture.pixelFormat
                                         width:drawable.texture.width height:drawable.texture.height mipmapped:NO];
            td.usage = MTLTextureUsageShaderRead;
            shot_tex = [dev newTextureWithDescriptor:td];
            id<MTLBlitCommandEncoder> bl = [cb blitCommandEncoder];
            [bl copyFromTexture:drawable.texture toTexture:shot_tex];
            [bl endEncoding];
        }
        static int pstats = -1;  // BDSP_PRESENT_STATS=1: drawables actually shown (interval of the presentedTime) every 2 s
        static int pat = -1;     // BDSP_PRESENT_AT=min|grid|lock: presentation time (default: immediately at the next vsync)
        if (pstats < 0) pstats = getenv("BDSP_PRESENT_STATS") != NULL;
        if (pat < 0) { const char *e = getenv("BDSP_PRESENT_AT"); pat = !e ? PRESENT_AT_DEFAULT : !strcmp(e, "min") ? 1 : !strcmp(e, "grid") ? 2 : !strcmp(e, "lock") ? 3 : 0; }   // "off": old behavior
        static _Atomic double vsync_anchor;  // last shown presentedTime: fixes the grid of the display
        static double vper;   // display interval (ProMotion 1/120 s)
        if (vper == 0) {
            long hz = 0;
#if TARGET_OS_OSX
            hz = (long)NSScreen.mainScreen.maximumFramesPerSecond;
#else
            hz = (long)UIScreen.mainScreen.maximumFramesPerSecond;
#endif
            vper = 1.0 / (hz >= 30 && hz <= 240 ? hz : 120);
        }
        double tgt = 0;
        if (pat == 1) [cb presentDrawable:drawable afterMinimumDuration:vper];
        else if (pat == 2) {
            // align to the vsync grid: target shortly before the next grid tick, so exactly that tick is hit
            double a = atomic_load(&vsync_anchor), now = CACurrentMediaTime();
            if (a > 0 && now > a) [cb presentDrawable:drawable atTime:a + (floor((now - a) / vper) + 1) * vper - vper * 0.5];
            else [cb presentDrawable:drawable];
        } else if (pat == 3) {
            // Phase-locked chain: every frame exactly step display intervals after the previous one. If a frame is late,
            // it restarts at a grid point with lead (grid from the last real presentedTime).
            static double chain;
            static double lead = -1;
            if (lead < 0) lead = getenv("BDSP_PRESENT_LEAD") ? atof(getenv("BDSP_PRESENT_LEAD")) : 1.0;
            double a = atomic_load(&vsync_anchor), now = CACurrentMediaTime();
            double step = fmax(1.0, round(1.0 / (g_bdsp_fps_now() * vper))) * vper;
            if (a > 0) {
                double t = chain + step;
                bool resync = chain <= 0 || t - now < 0.75 * step || t - now > lead * step + 1.5 * step;
                if (resync) t = a + ceil((now + lead * step - a) / vper) * vper;
                chain = t;
                tgt = t;
                [cb presentDrawable:drawable atTime:t - vper * 0.5];
            } else [cb presentDrawable:drawable];
        } else [cb presentDrawable:drawable];
        if (pstats || pat >= 2) {
            double commit_t = CACurrentMediaTime();
        [drawable addPresentedHandler:^(id<MTLDrawable> d) {
                static double prev, t0, sum, sum2;
                static unsigned n, hist[6], ncnt, inband;
                double pt = d.presentedTime;
                if (pt <= 0) { hist[5]++; return; }   // verworfen, nie angezeigt
                atomic_store(&vsync_anchor, pt);
                if (!pstats) return;
                if (prev > 0) {
                    double ms = (pt - prev) * 1000;
                    int k = (int)(ms / (vper * 1000) + 0.5);   // number of display intervals between two frames
                    hist[k < 1 ? 0 : k > 4 ? 4 : k - 1]++;
                    if (fabs(ms - 1000.0 / g_bdsp_fps_now()) <= 0.3) inband++;
                    else if (getenv("BDSP_PRESENT_OUT"))
                        LOG("[out] frame %llu t=%.3f interval %.2f ms, commit %.2f ms before display, GPU end %.2f ms before display, GPU duration %.2f ms, target lead %.2f ms\n", (unsigned long long)frame, pt, ms, (pt - commit_t) * 1000, (pt - cb.GPUEndTime) * 1000, (cb.GPUEndTime - cb.GPUStartTime) * 1000, (tgt - commit_t) * 1000);
                    sum += ms; sum2 += ms * ms; ncnt++;
                }
                prev = pt;
                n++;
                if (!t0) t0 = pt;
                if (pt - t0 >= 2) {
                    double mean = ncnt ? sum / ncnt : 0, sd = ncnt ? sqrt(fmax(0, sum2 / ncnt - mean * mean)) : 0;
                    LOG("[present] %.1f angezeigt/s, Intervalle zu 1/2/3/4+ Vsync: %u/%u/%u/%u, verworfen %u, Abstand Mittel %.2f ms sd %.2f ms, im Zielband (±0,3 ms) %.1f %%\n",
                        n / (pt - t0), hist[0], hist[1], hist[2], hist[3] + hist[4], hist[5], mean, sd, ncnt ? 100.0 * inband / ncnt : 0.0);
                    n = 0; t0 = pt; sum = sum2 = 0; ncnt = 0; inband = 0; memset(hist, 0, sizeof hist);
                }
            }];
        }
        [cb commit];
        g_present_cb = cb;
        if (shot_tex) {
            if (!dbg_thread_enabled()) [cb waitUntilCompleted];  // (debug thread: renderer_save_texture queues its copy behind this buffer)
            // BDSP_SHOT_PATH: where (parallel test runs each write their own; default build/window.png)
            g_save_upright = true;
            if (g_window_shot_request[0]) {
                renderer_save_texture(shot_tex, g_window_shot_request);
                g_window_shot_request[0] = 0;
            } else {
                renderer_save_texture(shot_tex, getenv("BDSP_SHOT_PATH") ? getenv("BDSP_SHOT_PATH") : "build/window.png");
                if (getenv("BDSP_EXIT_AFTER_SHOT")) { dbg_thread_drain(); fflush(stderr); _exit(0); }
            }
            g_save_upright = false;
        }
    }
    return true;
}

void backend_present(NvnTexture *t) {
    extern bool renderer_worker_present(void (^job)(void));
    g_last_presented = t;
    TexBackend *b = t->backend;
    if (b) b->presented = true;
    id<MTLTexture> tex = b ? b->tex : nil;  // the job holds the texture, even if the guest releases it afterwards
    float wc[4];
    extern bool nvn_window_crop(float *uv, uint32_t tw, uint32_t th);
    bool has_wc = nvn_window_crop(wc, t->width, t->height);
    uint64_t frame = total_frames;
    struct { float v[4]; } wcs;
    memcpy(wcs.v, wc, sizeof wcs.v);
    bool worker = renderer_worker_present(^{
        // runs in the worker; the counters that exec_list sees continue here with the frame
        present_gpu(frame, tex, has_wc, wcs.v);
        xw_gpu_lag();
        wk_frames++;
        tex_inventory_tick(wk_frames);
        g_frame_counter++;
    });
    if (!worker && !present_gpu(frame, tex, has_wc, wc)) return;
    frames++;
    total_frames++;
    if (!worker) g_frame_counter++;
    extern void input_frame(uint64_t frame);
    input_frame(total_frames);
    static long slow_ms = -1;  // BDSP_SLOW_FRAME_MS=<ms>: sleep per presented frame (simulate a slow machine)
    if (slow_ms < 0) slow_ms = getenv("BDSP_SLOW_FRAME_MS") ? atol(getenv("BDSP_SLOW_FRAME_MS")) : 0;
    if (slow_ms > 0 && total_frames > 2600) usleep((useconds_t)slow_ms * 1000);
    extern void fnprof_frame(uint64_t frame);
    fnprof_frame(total_frames);
    extern void warp_frame(uint64_t frame);
    warp_frame(total_frames);
    extern void reboot_test_frame(uint64_t frame);  // runtime/main.c (BDSP_REBOOT_AT)
    reboot_test_frame(total_frames);
    extern void save_editor_frame(uint64_t frame);
    save_editor_frame(total_frames);
    static long shot_every = -1;
    if (shot_every < 0) { const char *e = getenv("BDSP_SCREENSHOT_EVERY"); shot_every = e ? atol(e) : 0; }
    extern bool g_debug_frame;
    static long debug_at = -1;
    if (debug_at < 0) { const char *e = getenv("BDSP_DEBUG_FRAME"); debug_at = e ? atol(e) : 0; }
    level_change_check();
    extern volatile int g_debug_frame_request;
    if (g_debug_frame_request) { g_debug_frame_request = 0; debug_at = (long)total_frames + 1; }
    g_debug_frame = debug_at && total_frames == (uint64_t)debug_at;
    if (g_debug_frame) LOG("===== debug frame %llu =====\n", total_frames);
    static long shot_from = -1;  // BDSP_SCREENSHOT_FROM=<frame>: periodic shots start there (into build/frames/)
    if (shot_from < 0) { const char *e = getenv("BDSP_SCREENSHOT_FROM"); shot_from = e ? atol(e) : 0; }
    if (shot_every && b && b->tex && total_frames % shot_every == 0 && (long)total_frames >= shot_from) {
        char path[256];
        const char *dir = getenv("BDSP_SHOT_DIR") ? getenv("BDSP_SHOT_DIR") : "work/recomp/shots";
        mkdir(dir, 0755);
        if (worker) { extern void renderer_submit(void); renderer_submit(); }  // waits until the worker has finished the frame
        snprintf(path, sizeof path, "%s/frame_%05llu.png", dir, total_frames);
        save_png(b->tex, path);
        if (getenv("BDSP_EXIT_AFTER_SHOT")) { dbg_thread_drain(); fflush(stderr); _exit(0); }
    }
    double now = SDL_GetTicks() / 1000.0;
    static double fps_iv = -1, prev_present, max_gap;  // BDSP_FPS_INTERVAL=<s>: fps line period (default 2)
    if (fps_iv < 0) fps_iv = getenv("BDSP_FPS_INTERVAL") ? atof(getenv("BDSP_FPS_INTERVAL")) : 2.0;
    if (prev_present > 0 && now - prev_present > max_gap) max_gap = now - prev_present;
    prev_present = now;
    if (now - last_fps_time >= fps_iv) {
        extern const char *game_level_name(void);
        if (last_fps_time > 0) LOG("[metal] t=%.1f frame %llu %.1f fps max %.0fms level %s (%s)\n", now, (unsigned long long)total_frames,
                                   frames / (now - last_fps_time), max_gap * 1000.0, game_level_name(), renderer_stats());
        {   // (diagnostics) frame rate low for two periods in a row: what's allocated (at most once a minute)
            static int slow;
            static double last_dump = -100;
            double fps = last_fps_time > 0 ? frames / (now - last_fps_time) : 60;
            slow = fps < 40 ? slow + 1 : 0;
            if (slow >= 2 && now - last_dump > 60) { last_dump = now; dump_largest_textures("low frame rate"); }
            if (now - last_dump > 300 && now > 30) { last_dump = now; dump_largest_textures("periodic"); }
        }
        max_gap = 0;
        frames = 0;
        last_fps_time = now;
    }
}

// ================================================================== UI thread
// The window + Metal layer, created once: by the launcher (runtime/ui/launcher.mm, start screen before the game
// boots) or by ui_run; the game reuses the launcher's window.
void ui_window_init(void) {
    if (window) return;
    // (no SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS here: on macOS reading controllers in the background opens them
    // as HID devices, for which the system asks for Input Monitoring - "receive keystrokes from any application")
    settings_load();
    if (!SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD)) FATAL("SDL_Init: %s\n", SDL_GetError());
    int win_w = 1280, win_h = 720;
    if (getenv("BDSP_WINDOW")) sscanf(getenv("BDSP_WINDOW"), "%dx%d", &win_w, &win_h);
    // BDSP_HIDDEN=1: never shown (automated test runs render off screen without taking the user's focus)
    SDL_WindowFlags wflags = SDL_WINDOW_METAL | SDL_WINDOW_RESIZABLE | SDL_WINDOW_HIGH_PIXEL_DENSITY;
    if (getenv("BDSP_HIDDEN")) wflags |= SDL_WINDOW_HIDDEN;
    window = SDL_CreateWindow("BDSP Recomp", win_w, win_h, wflags);
    if (!window) FATAL("SDL_CreateWindow: %s\n", SDL_GetError());
    rt_window_icon(window);
    // the Fullscreen setting applies from the start screen on (not only once the game runs); test windows stay windows
    if (g_settings.fullscreen && !getenv("BDSP_WINDOW") && !getenv("BDSP_HIDDEN")) SDL_SetWindowFullscreen(window, true);
    SDL_MetalView view = SDL_Metal_CreateView(window);
    layer = (__bridge CAMetalLayer *)SDL_Metal_GetLayer(view);
    dev = MTLCreateSystemDefaultDevice();
    layer.device = dev;
    layer.pixelFormat = MTLPixelFormatBGRA8Unorm;
    layer.framebufferOnly = getenv("BDSP_WINDOW_SHOT") ? NO : YES;
}

SDL_Window *ui_window(void) { return window; }
void *ui_metal_layer(void) { return (__bridge void *)layer; }
void *ui_metal_device(void) { return (__bridge void *)dev; }

int ui_run(void) {
    // The emulated vsync/timer threads need precise sleeps; App Nap timer coalescing
    // otherwise stretches 16ms sleeps to ~100ms whenever the window isn't frontmost.
    static id activity;
    if (!activity)
        activity = [[NSProcessInfo processInfo]
            beginActivityWithOptions:NSActivityUserInitiated | NSActivityLatencyCritical
                              reason:@"Game emulation"];
    ui_window_init();
    atomic_store(&ui_ready, true);
    for (;;) {
        if (rt_reboot_requested()) return rt_reboot_requested();  // (runtime/main.c tears the game down)
        SDL_Event e;
        while (SDL_WaitEventTimeout(&e, 16)) {
            if (e.type == SDL_EVENT_QUIT) { LOG("window closed\n"); exit(0); }
            if (input_user_blocked(&e)) continue;  // scripted test runs: the real keyboard / mouse / pads do nothing
            if (menu_handle_event(&e)) continue;
            input_handle_event(&e);
        }
        menu_apply_window_requests(window);
        int w, h;
        SDL_GetWindowSizeInPixels(window, &w, &h);
        layer.drawableSize = CGSizeMake(w, h);
    }
}
