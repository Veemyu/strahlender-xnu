// Metal renderer of the on-screen keyboard (swkbd_ui.c): draws the scene list over the finished frame, in its own render pass on the
// drawable. Called through g_overlay_render (nvn_glue.c menu_render) once per presented frame. Own code.
// Textures: BC4/BC5 are decoded on the CPU (lyt_tex_decode), ASTC goes to Metal as it is, with the channel mapping as a texture swizzle.
// Text: rasterised with CoreText into small textures, cached per string and size.
// BDSP_SWKBD_PREVIEW=<frame> opens the keyboard at that frame without the game asking (look-and-feel tests with BDSP_WINDOW_SHOT).
#import <CoreText/CoreText.h>
#import <CoreGraphics/CoreGraphics.h>
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>

#include <math.h>
#include <pthread.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>

#include "../swkbd_ui.h"


static NSString *const kMsl =
    @"#include <metal_stdlib>\n"
    "using namespace metal;\n"
    "struct V { float2 pos; float2 uv; float4 col; };\n"
    "struct O { float4 p [[position]]; float2 uv; float4 col; };\n"
    "vertex O vs(uint i [[vertex_id]], constant V *v [[buffer(0)]], constant float2 &vp [[buffer(1)]]) {\n"
    "  O o; o.p = float4(v[i].pos.x / vp.x * 2.0 - 1.0, 1.0 - v[i].pos.y / vp.y * 2.0, 0, 1); o.uv = v[i].uv; o.col = v[i].col; return o; }\n"
    "struct FU { float2 hsz; float rad; float px; float4 col; };\n"
    "fragment float4 ffs(O in [[stage_in]], constant FU &u [[buffer(0)]]) {\n"
    "  float2 q = abs(in.uv) - (u.hsz - u.rad);\n"
    "  float depth = -(length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - u.rad);\n"   // distance inside the outer, rounded rectangle
    "  float aa = u.px;\n"
    "  float halo = 0.36 * exp((depth - 1.9) / 2.0);\n"   // soft glow outside the core, fading over about 4 px (measured on the console)\n"
    "  float f = mix(halo, 1.0, smoothstep(1.9 - aa, 1.9 + aa, depth));\n"     // core
    "  f = mix(f, 0.5, smoothstep(6.4 - aa, 6.4 + aa, depth));\n"            // soft inner edge
    "  f = mix(f, 0.0, smoothstep(7.0 - aa, 7.0 + aa, depth));\n"            // the key itself
    "  float t = clamp(in.uv.y / u.hsz.y * 0.5 + 0.5, 0.0, 1.0);\n"   // the console's frame runs from a greener top to a bluer bottom (about 8 / 16 / -1 of 255 in r / g / b)
    "  float3 c = u.col.rgb + (0.5 - t) * float3(8.0, 16.0, -1.0) / 255.0;\n"
    "  return float4(c, u.col.a * f); }\n"
    "fragment float4 fs(O in [[stage_in]], texture2d<float> t [[texture(0)]], sampler s [[sampler(0)]]) {\n"
    "  return t.sample(s, in.uv) * in.col; }\n";

// Background blur: the game image behind the keyboard is blurred ONCE when the keyboard opens (the game stands still then) and kept in a
// texture; every following frame only draws that texture. Two passes (horizontal, vertical) of a 13 tap gaussian at a quarter of the
// window resolution, where one tap is 4 window pixels wide.
static NSString *const kMslBlur =
    @"#include <metal_stdlib>\n"
    "using namespace metal;\n"
    "struct B { float4 p [[position]]; float2 uv; };\n"
    "vertex B bvs(uint i [[vertex_id]]) { float2 uv = float2((i << 1) & 2, i & 2); B o; o.p = float4(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, 0, 1); o.uv = uv; return o; }\n"
    "fragment float4 bfs(B in [[stage_in]], texture2d<float> t [[texture(0)]], sampler s [[sampler(0)]], constant float2 &step [[buffer(0)]]) {\n"
    "  float3 c = 0; float ws = 0;\n"
    "  for (int k = -6; k <= 6; k++) { float w = exp(-float(k * k) / 12.5); c += w * t.sample(s, in.uv + step * float(k)).rgb; ws += w; }\n"
    "  return float4(c / ws, 1); }\n";

static id<MTLRenderPipelineState> g_blur_pipe;
static id<MTLTexture> g_blur_a, g_blur_b;      // b holds the result
static NSUInteger g_blur_w, g_blur_h;           // window size the result belongs to
static BOOL g_blur_ready, g_was_active;
static float g_blur_t;

typedef struct { float pos[2], uv[2], col[4]; } Vtx;

static id<MTLRenderPipelineState> g_pipe, g_pipe_frame;
static MTLPixelFormat g_pipe_fmt;
static id<MTLSamplerState> g_samp;
static id<MTLTexture> g_white;
static NSMapTable *g_tex;       // LytTex* -> id<MTLTexture>
static NSMutableDictionary<NSString *, NSDictionary *> *g_text;   // "px|str" -> {tex, w, h}

// Fonts: the system's own (from the user's firmware: fonts/nintendo_udsg-r_std_003.bfttf for text, fonts/nintendo_ext_003.bfttf for the button
// glyphs in the private use area), found under the firmware folder; without them the Mac's fonts. The .bfttf files are TrueType with every
// 32-bit word XORed with a key taken from the first word (first word ^ 0x18029A7F), after an 8 byte header.
static CGFontRef load_bfttf(const char *root, const char *name, const char *title) {
    char path[1200];
    NSData *raw = nil;
    for (int i = 0; i < 2 && !raw; i++) {
        snprintf(path, sizeof path, i ? "%s/fonts/%s/%s" : "%s/fonts/%s", root, i ? title : name, name);
        if (!i) snprintf(path, sizeof path, "%s/fonts/%s", root, name);
        raw = [NSData dataWithContentsOfFile:@(path)];
    }
    if (!raw || raw.length < 16) return NULL;
    NSMutableData *out = [NSMutableData dataWithLength:raw.length - 8];
    const uint32_t *in = (const uint32_t *)raw.bytes;
    uint32_t key = in[0] ^ 0x18029A7Fu;
    uint32_t *o = (uint32_t *)out.mutableBytes;
    for (NSUInteger i = 2; i < raw.length / 4; i++) o[i - 2] = in[i] ^ key;
    CGDataProviderRef dp = CGDataProviderCreateWithCFData((__bridge CFDataRef)out);
    CGFontRef f = CGFontCreateWithDataProvider(dp);
    CGDataProviderRelease(dp);
    return f;
}

static CGFontRef g_font_std, g_font_ext;
static BOOL g_fonts_tried;

static void fonts_init(void) {
    if (g_fonts_tried) return;
    g_fonts_tried = YES;
    const char *root = swkbd_ui_root();
    if (!root || !*root) return;
    g_font_std = load_bfttf(root, "nintendo_udsg-r_std_003.bfttf", "0100000000000811");
    g_font_ext = load_bfttf(root, "nintendo_ext_003.bfttf", "0100000000000810");
}

static CTFontRef font_at(float px) {
    fonts_init();
    if (g_font_std) return CTFontCreateWithGraphicsFont(g_font_std, px, NULL, NULL);
    return CTFontCreateWithName(CFSTR("HelveticaNeue"), px, NULL);
}

static CTFontRef ext_at(float px) {
    fonts_init();
    return g_font_ext ? CTFontCreateWithGraphicsFont(g_font_ext, px, NULL, NULL) : NULL;
}

// Attributed string: button glyphs (private use area) from the button font, everything else from the text font
static NSAttributedString *make_attr(NSString *str, float px, float kern) {
    CTFontRef f = font_at(px), e = ext_at(px);
    NSMutableAttributedString *as = [[NSMutableAttributedString alloc] initWithString:str attributes:@{(__bridge id)kCTFontAttributeName: (__bridge id)f,
        (__bridge id)kCTForegroundColorFromContextAttributeName: @YES}];
    if (kern != 0) [as addAttribute:(__bridge id)kCTKernAttributeName value:@(kern) range:NSMakeRange(0, str.length)];
    if (e) {
        for (NSUInteger i = 0; i < str.length; i++) {
            unichar c = [str characterAtIndex:i];
            if (c >= 0xE000 && c <= 0xF8FF) [as addAttribute:(__bridge id)kCTFontAttributeName value:(__bridge id)e range:NSMakeRange(i, 1)];
        }
        CFRelease(e);
    }
    CFRelease(f);
    return as;
}

static float measure(const char *utf8, float px) {
    @autoreleasepool {
        NSAttributedString *s = make_attr(@(utf8), px > 1 ? px : 1, 0);
        CTLineRef l = CTLineCreateWithAttributedString((__bridge CFAttributedStringRef)s);
        float w = (float)CTLineGetTypographicBounds(l, NULL, NULL, NULL);
        CFRelease(l);
        return w;
    }
}

static id<MTLTexture> make_rgba(id<MTLDevice> dev, int w, int h, const void *px) {
    MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:(NSUInteger)w height:(NSUInteger)h mipmapped:NO];
    td.usage = MTLTextureUsageShaderRead;
    id<MTLTexture> t = [dev newTextureWithDescriptor:td];
    [t replaceRegion:MTLRegionMake2D(0, 0, (NSUInteger)w, (NSUInteger)h) mipmapLevel:0 withBytes:px bytesPerRow:(NSUInteger)w * 4];
    return t;
}

static MTLTextureSwizzle swz(uint32_t c) {
    switch (c) {
    case 0: return MTLTextureSwizzleZero;
    case 1: return MTLTextureSwizzleOne;
    case 2: return MTLTextureSwizzleRed;
    case 3: return MTLTextureSwizzleGreen;
    case 4: return MTLTextureSwizzleBlue;
    default: return MTLTextureSwizzleAlpha;
    }
}

// The icon textures are 64 px (the backspace one a single BC4 channel with visible 4x4 blocks) and are drawn at about 75 device pixels. They are
// scaled to twice the size with a Catmull-Rom filter and their alpha edge is sharpened, so the shape stays crisp instead of soft and blocky.
static float cubic(float p0, float p1, float p2, float p3, float t) {
    return p1 + 0.5f * t * (p2 - p0 + t * (2 * p0 - 5 * p1 + 4 * p2 - p3 + t * (3 * (p1 - p2) + p3 - p0)));
}
static uint8_t *upscale2_sharp(const uint8_t *px, int w, int h) {
    int W = w * 2, H = h * 2;
    uint8_t *out = malloc((size_t)W * H * 4);
    if (!out) return NULL;
    for (int y = 0; y < H; y++)
        for (int x = 0; x < W; x++) {
            float sx = (x + 0.5f) / 2 - 0.5f, sy = (y + 0.5f) / 2 - 0.5f;
            int ix = (int)floorf(sx), iy = (int)floorf(sy);
            float fx = sx - ix, fy = sy - iy;
            for (int c = 0; c < 4; c++) {
                float col[4];
                for (int j = 0; j < 4; j++) {
                    int yy = iy - 1 + j; yy = yy < 0 ? 0 : yy >= h ? h - 1 : yy;
                    float v[4];
                    for (int i = 0; i < 4; i++) { int xx = ix - 1 + i; xx = xx < 0 ? 0 : xx >= w ? w - 1 : xx; v[i] = px[((size_t)yy * w + xx) * 4 + c]; }
                    col[j] = cubic(v[0], v[1], v[2], v[3], fx);
                }
                float r = cubic(col[0], col[1], col[2], col[3], fy);
                r = r < 0 ? 0 : r > 255 ? 255 : r;
                if (c == 3) {   // sharpen the edge of the shape
                    float a = r / 255, u = (a - 0.3f) / 0.4f;
                    u = u < 0 ? 0 : u > 1 ? 1 : u;
                    r = 255 * u * u * (3 - 2 * u);
                }
                out[((size_t)y * W + x) * 4 + c] = (uint8_t)(r + 0.5f);
            }
        }
    return out;
}

static id<MTLTexture> gpu_tex(id<MTLDevice> dev, const LytTex *t) {
    NSValue *key = [NSValue valueWithPointer:t];
    id<MTLTexture> r = [g_tex objectForKey:key];
    if (r) return r == (id)[NSNull null] ? nil : r;
    if (lyt_tex_is_astc(t)) {
        if (t->blocks) {
            MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatASTC_4x4_LDR width:t->w height:t->h mipmapped:NO];
            td.usage = MTLTextureUsageShaderRead;
            id<MTLTexture> base = [dev newTextureWithDescriptor:td];
            if (base) {
                [base replaceRegion:MTLRegionMake2D(0, 0, t->w, t->h) mipmapLevel:0 withBytes:t->blocks bytesPerRow:(NSUInteger)t->bw * 16];
                MTLTextureSwizzleChannels sc = MTLTextureSwizzleChannelsMake(swz(t->chan & 0xFF), swz((t->chan >> 8) & 0xFF), swz((t->chan >> 16) & 0xFF), swz((t->chan >> 24) & 0xFF));
                r = [base newTextureViewWithPixelFormat:MTLPixelFormatASTC_4x4_LDR textureType:MTLTextureType2D levels:NSMakeRange(0, 1) slices:NSMakeRange(0, 1) swizzle:sc];
            }
        }
    } else {
        uint8_t *px = malloc((size_t)t->w * t->h * 4);
        if (px && lyt_tex_decode(t, px)) {
            uint8_t *big = !strncmp(t->name, "Ico", 3) ? upscale2_sharp(px, (int)t->w, (int)t->h) : NULL;
            r = big ? make_rgba(dev, (int)t->w * 2, (int)t->h * 2, big) : make_rgba(dev, (int)t->w, (int)t->h, px);
            free(big);
        }
        free(px);
    }
    [g_tex setObject:r ?: (id)[NSNull null] forKey:key];
    return r;
}

// Text as a texture: white glyphs with alpha, so the vertex colour tints it. Size in device pixels.
static NSDictionary *text_tex(id<MTLDevice> dev, const char *utf8, float px, float kern) {
    NSString *key = [NSString stringWithFormat:@"%.1f|%.2f|%s", px, kern, utf8];
    NSDictionary *hit = g_text[key];
    if (hit) return hit;
    NSDictionary *res = nil;
    @autoreleasepool {
        NSAttributedString *s = make_attr(@(utf8), px, kern);
        CTLineRef l = CTLineCreateWithAttributedString((__bridge CFAttributedStringRef)s);
        CGFloat asc, desc, lead;
        double w = CTLineGetTypographicBounds(l, &asc, &desc, &lead);
        CGRect ib = CTLineGetImageBounds(l, NULL);   // accents and cedillas can reach beyond the font's ascent / descent
        (void)ib;
        CGFloat pad = ceil(px * 0.3);   // room for accents above and cedillas / descenders below: a fixed amount, so the baseline stands at the same place for every string
        asc += pad; desc += pad;
        int tw = (int)ceil(w) + 4, th = (int)ceil(asc + desc) + 4;
        if (tw > 0 && th > 0 && tw < 4096 && th < 1024) {
            CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
            CGContextRef cg = CGBitmapContextCreate(NULL, (size_t)tw, (size_t)th, 8, (size_t)tw * 4, cs, (CGBitmapInfo)kCGImageAlphaPremultipliedLast);
            CGContextSetRGBFillColor(cg, 1, 1, 1, 1);
            CGContextSetAllowsFontSmoothing(cg, false);   // no stem darkening: the console's strokes are thinner than macOS draws them
            CGContextSetShouldSmoothFonts(cg, false);
            CGContextSetTextPosition(cg, 2, desc + 2);
            CTLineDraw(l, cg);
            uint8_t *bits = CGBitmapContextGetData(cg);
            for (int i = 0; i < tw * th; i++) bits[i * 4] = bits[i * 4 + 1] = bits[i * 4 + 2] = 255;   // the context holds premultiplied white (rgb = alpha); the shader and the blend multiply by alpha again, which made dark fringes on edges: keep straight alpha
            id<MTLTexture> t = make_rgba(dev, tw, th, bits);   // row 0 of the bitmap is the top
            CGContextRelease(cg); CGColorSpaceRelease(cs);
            res = @{@"tex": t, @"w": @(tw), @"h": @(th), @"asc": @(asc), @"pad": @(pad)};
        }
        CFRelease(l);
    }
    if (!res) res = @{};
    g_text[key] = res;
    return res;
}

static int setup(id<MTLDevice> dev, MTLPixelFormat fmt) {
    if (g_pipe && g_pipe_fmt == fmt) return 1;
    NSError *err = nil;
    id<MTLLibrary> lib = [dev newLibraryWithSource:kMsl options:nil error:&err];
    if (!lib) { fprintf(stderr, "[swkbd] shader: %s\n", err.localizedDescription.UTF8String); return 0; }
    MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
    pd.vertexFunction = [lib newFunctionWithName:@"vs"];
    pd.fragmentFunction = [lib newFunctionWithName:@"fs"];
    MTLRenderPipelineColorAttachmentDescriptor *c = pd.colorAttachments[0];
    c.pixelFormat = fmt;
    c.blendingEnabled = YES;
    c.sourceRGBBlendFactor = MTLBlendFactorSourceAlpha;
    c.destinationRGBBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    c.sourceAlphaBlendFactor = MTLBlendFactorOne;
    c.destinationAlphaBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    g_pipe = [dev newRenderPipelineStateWithDescriptor:pd error:&err];
    if (!g_pipe) { fprintf(stderr, "[swkbd] pipeline: %s\n", err.localizedDescription.UTF8String); return 0; }
    pd.fragmentFunction = [lib newFunctionWithName:@"ffs"];
    g_pipe_frame = [dev newRenderPipelineStateWithDescriptor:pd error:&err];
    if (!g_pipe_frame) { fprintf(stderr, "[swkbd] frame pipeline: %s\n", err.localizedDescription.UTF8String); return 0; }
    g_pipe_fmt = fmt;
    if (!g_samp) {
        MTLSamplerDescriptor *sd = [MTLSamplerDescriptor new];
        sd.minFilter = sd.magFilter = MTLSamplerMinMagFilterLinear;
        sd.sAddressMode = sd.tAddressMode = MTLSamplerAddressModeClampToEdge;
        g_samp = [dev newSamplerStateWithDescriptor:sd];
        uint8_t white[4] = {255, 255, 255, 255};
        g_white = make_rgba(dev, 1, 1, white);
        g_tex = [NSMapTable strongToStrongObjectsMapTable];
        g_text = [NSMutableDictionary new];
        swkbd_ui_set_measure(measure);
    }
    return 1;
}

static void quad(id<MTLRenderCommandEncoder> enc, const float X[4], const float Y[4], const float uv[4][2], const float col[4][4]) {
    Vtx v[4];
    for (int k = 0; k < 4; k++) { v[k].pos[0] = X[k]; v[k].pos[1] = Y[k]; v[k].uv[0] = uv[k][0]; v[k].uv[1] = uv[k][1]; memcpy(v[k].col, col[k], 16); }
    Vtx t[6] = {v[0], v[1], v[2], v[1], v[3], v[2]};
    [enc setVertexBytes:t length:sizeof t atIndex:0];
    [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];
}

extern void metal_set_sampleable(int on);

static void overlay_release(void);
static void blur_drop(void) { g_blur_ready = NO; g_blur_a = g_blur_b = nil; g_blur_t = 0; }

// Blurs `src` (the drawable with the game image, sampleable) into g_blur_b. Returns 0 when it cannot be done yet.
static int blur_capture(id<MTLDevice> dev, id<MTLCommandBuffer> cb, id<MTLTexture> src) {
    if (!(src.usage & MTLTextureUsageShaderRead)) return 0;
    if (!g_blur_pipe) {
        NSError *err = nil;
        id<MTLLibrary> lib = [dev newLibraryWithSource:kMslBlur options:nil error:&err];
        if (!lib) { fprintf(stderr, "[swkbd] blur shader: %s\n", err.localizedDescription.UTF8String); return 0; }
        MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
        pd.vertexFunction = [lib newFunctionWithName:@"bvs"];
        pd.fragmentFunction = [lib newFunctionWithName:@"bfs"];
        pd.colorAttachments[0].pixelFormat = src.pixelFormat;
        g_blur_pipe = [dev newRenderPipelineStateWithDescriptor:pd error:&err];
        if (!g_blur_pipe) { fprintf(stderr, "[swkbd] blur pipeline: %s\n", err.localizedDescription.UTF8String); return 0; }
    }
    NSUInteger qw = src.width / 4 > 1 ? src.width / 4 : 1, qh = src.height / 4 > 1 ? src.height / 4 : 1;
    MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:src.pixelFormat width:qw height:qh mipmapped:NO];
    td.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
    td.storageMode = MTLStorageModePrivate;
    g_blur_a = [dev newTextureWithDescriptor:td];
    g_blur_b = [dev newTextureWithDescriptor:td];
    if (!g_blur_a || !g_blur_b) { blur_drop(); return 0; }
    id<MTLTexture> in[2] = {src, g_blur_a}, out[2] = {g_blur_a, g_blur_b};
    float step[2][2] = {{4.0f / src.width, 0}, {0, 1.0f / qh}};
    for (int i = 0; i < 2; i++) {
        MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
        rp.colorAttachments[0].texture = out[i];
        rp.colorAttachments[0].loadAction = MTLLoadActionDontCare;
        rp.colorAttachments[0].storeAction = MTLStoreActionStore;
        id<MTLRenderCommandEncoder> e = [cb renderCommandEncoderWithDescriptor:rp];
        [e setRenderPipelineState:g_blur_pipe];
        [e setFragmentTexture:in[i] atIndex:0];
        [e setFragmentSamplerState:g_samp atIndex:0];
        [e setFragmentBytes:step[i] length:sizeof step[i] atIndex:0];
        [e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
        [e endEncoding];
    }
    g_blur_a = nil;
    g_blur_w = src.width; g_blur_h = src.height;
    g_blur_ready = YES;
    return 1;
}

static void preview_check(void) {
    static long at = -1, frame;
    if (at < 0) at = getenv("BDSP_SWKBD_PREVIEW") ? atol(getenv("BDSP_SWKBD_PREVIEW")) : 0;
    if (at && ++frame == at) {
        SwkbdParams p = {0};
        p.minlen = 1; p.maxlen = 12;
        snprintf(p.header, sizeof p.header, "%s", getenv("BDSP_SWKBD_HEADER") ? getenv("BDSP_SWKBD_HEADER") : "Enter your name");   // (BDSP_SWKBD_HEADER: for comparing with a screenshot)
        snprintf(p.sub, sizeof p.sub, "Up to 12 characters");
        snprintf(p.guide, sizeof p.guide, "Name");
        SwkbdCallbacks cb = {0};
        swkbd_ui_open(&p, cb, NULL);
    }
}

// While the keyboard is open the game thread is stopped inside the keyboard call and presents nothing; this thread then shows the last
// game image again (metal.m metal_repeat_present), which draws the keyboard over it through render().
extern uint64_t metal_last_present_ns(void);
extern void metal_repeat_present(void);

extern uint64_t metal_now_ns(void);

// The thread only lives while the keyboard is visible: it is started by the keyboard's wake-up when it opens and ends after it has closed.
static pthread_mutex_t g_ka_lock = PTHREAD_MUTEX_INITIALIZER;
static BOOL g_ka_running;

static void *keepalive(void *arg) {
    pthread_setname_np("swkbd-present");
    for (;;) {
        usleep(16000);
        pthread_mutex_lock(&g_ka_lock);
        if (!swkbd_ui_visible()) { g_ka_running = NO; pthread_mutex_unlock(&g_ka_lock); return NULL; }
        pthread_mutex_unlock(&g_ka_lock);
        if (metal_now_ns() - metal_last_present_ns() < 50000000ull) continue;   // the game is presenting itself
        metal_repeat_present();
    }
    return NULL;
}

static void keepalive_wake(void) {
    pthread_mutex_lock(&g_ka_lock);
    if (!g_ka_running) {
        pthread_t th;
        if (!pthread_create(&th, NULL, keepalive, NULL)) { pthread_detach(th); g_ka_running = YES; }
    }
    pthread_mutex_unlock(&g_ka_lock);
}

// Everything the keyboard made on the GPU or in memory goes when it closes (its screens and sounds are freed by swkbd_ui; the command buffers
// still in flight keep the resources they use alive). The next opening builds them again.
static void overlay_release(void) {
    g_tex = nil; g_text = nil; g_white = nil; g_samp = nil;
    g_pipe = nil; g_pipe_frame = nil; g_pipe_fmt = (MTLPixelFormat)0; g_blur_pipe = nil;
    if (g_font_std) { CGFontRelease(g_font_std); g_font_std = NULL; }
    if (g_font_ext) { CGFontRelease(g_font_ext); g_font_ext = NULL; }
    g_fonts_tried = NO;
}

void swkbd_overlay_render(void *dev_, void *cb_, void *target_) {
    static dispatch_once_t once;
    dispatch_once(&once, ^{   // first frame: tell the keyboard logic that something can draw it, and how to wake the thread that keeps the picture alive
        swkbd_ui_set_display(1);
        swkbd_ui_set_wake(keepalive_wake);
    });
    id<MTLDevice> dev = (__bridge id<MTLDevice>)dev_;
    id<MTLCommandBuffer> cb = (__bridge id<MTLCommandBuffer>)cb_;
    id<MTLTexture> target = (__bridge id<MTLTexture>)target_;
    preview_check();
    int active = swkbd_ui_visible();
    if (active != g_was_active) {   // the drawables must be readable while the keyboard is open (the blur is made from one of them)
        g_was_active = active;
        metal_set_sampleable(active);
        if (!active) { blur_drop(); overlay_release(); }
    }
    if (!active) return;
    static int calls;
    if (getenv("BDSP_TRACE_APPLET") && calls++ % 60 == 0) fprintf(stderr, "[swkbd_overlay] render while active, target %lux%lu fmt %lu\n", (unsigned long)((__bridge id<MTLTexture>)target_).width, (unsigned long)((__bridge id<MTLTexture>)target_).height, (unsigned long)((__bridge id<MTLTexture>)target_).pixelFormat);
    @autoreleasepool {
        static CFAbsoluteTime last;
        CFAbsoluteTime now = CFAbsoluteTimeGetCurrent();
        double dt = last ? fmin(now - last, 0.1) : 0.016;
        last = now;
        if (!setup(dev, target.pixelFormat)) return;
        if (g_blur_ready && (g_blur_w != target.width || g_blur_h != target.height)) blur_drop();   // window resized: blur again
        if (!g_blur_ready) blur_capture(dev, cb, target);
        else g_blur_t += (float)dt;
        float scale, off[2];
        int tw = (int)target.width, th = (int)target.height;
        const LytScene *sc = swkbd_ui_scene(dt, tw, th, &scale, off);
        if (!sc) { last = 0; return; }
        MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
        rp.colorAttachments[0].texture = target;
        rp.colorAttachments[0].loadAction = MTLLoadActionLoad;
        rp.colorAttachments[0].storeAction = MTLStoreActionStore;
        id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:rp];
        [enc setRenderPipelineState:g_pipe];
        float vp[2] = {(float)tw, (float)th};
        [enc setVertexBytes:vp length:sizeof vp atIndex:1];
        [enc setFragmentSamplerState:g_samp atIndex:0];
        if (g_blur_ready) {   // the stored blur instead of the sharp game image, fading in like the dimming layer
            float bx[4] = {0, (float)tw, 0, (float)tw}, by[4] = {0, 0, (float)th, (float)th};
            float buv[4][2] = {{0, 0}, {1, 0}, {0, 1}, {1, 1}}, bc[4][4];
            float fa = (g_blur_t >= 0.1f ? 1.0f : g_blur_t / 0.1f) * swkbd_ui_backdrop();
            for (int k = 0; k < 4; k++) { bc[k][0] = bc[k][1] = bc[k][2] = 1; bc[k][3] = fa; }
            [enc setFragmentTexture:g_blur_b atIndex:0];
            quad(enc, bx, by, buv, bc);
        }
        for (int i = 0; i < sc->n; i++) {
            const LytItem *it = &sc->items[i];
            float X[4], Y[4];
            for (int k = 0; k < 4; k++) { X[k] = off[0] + it->x[k] * scale; Y[k] = off[1] + it->y[k] * scale; }
            if (it->type == LYT_ITEM_FRAME) {   // focus frame around the key rectangle (items x[0], y[0] .. x[3], y[3]); the faint outer 1.9 px do not count, so the radius of the outer shape is 2.5 + 1.9
                float kx0 = X[0], ky0 = Y[0], kx1 = X[3], ky1 = Y[3], m = 8 * scale;
                float cx = (kx0 + kx1) / 2, cy = (ky0 + ky1) / 2, hw = (kx1 - kx0) / 2 / scale + 7, hh = (ky1 - ky0) / 2 / scale + 7;
                struct { float half[2]; float rad, px; float col[4]; } fu = {{hw, hh}, 4.4f, 1.0f / scale, {it->col[0][0] / 255.0f, it->col[0][1] / 255.0f, it->col[0][2] / 255.0f, it->alpha}};
                float fx[4] = {cx - hw * scale - m + 7 * scale, cx + hw * scale + m - 7 * scale, cx - hw * scale - m + 7 * scale, cx + hw * scale + m - 7 * scale};
                float fy[4] = {cy - hh * scale - m + 7 * scale, cy - hh * scale - m + 7 * scale, cy + hh * scale + m - 7 * scale, cy + hh * scale + m - 7 * scale};
                float fuv[4][2], fcol[4][4] = {{1,1,1,1},{1,1,1,1},{1,1,1,1},{1,1,1,1}};
                for (int k = 0; k < 4; k++) { fuv[k][0] = (fx[k] - cx) / scale; fuv[k][1] = (fy[k] - cy) / scale; }
                [enc setRenderPipelineState:g_pipe_frame];
                [enc setFragmentBytes:&fu length:sizeof fu atIndex:0];
                quad(enc, fx, fy, fuv, fcol);
                [enc setRenderPipelineState:g_pipe];
                continue;
            }
            if (it->type == LYT_ITEM_QUAD) {
                id<MTLTexture> t = g_white;
                if (it->tex) { t = gpu_tex(dev, it->tex); if (!t) continue; }
                float col[4][4];
                for (int k = 0; k < 4; k++) { for (int c = 0; c < 3; c++) col[k][c] = it->col[k][c] / 255.0f; col[k][3] = it->col[k][3] / 255.0f * it->alpha; }
                [enc setFragmentTexture:t atIndex:0];
                quad(enc, X, Y, (const float (*)[2])it->uv, col);
            } else if (it->str && it->str[0]) {
                float bw = X[3] - X[0], bh = Y[3] - Y[0];
                float px = it->font_size[0] * scale;   // the layouts' glyph width is the em size; the height is 1.5x of it (the font is drawn at its own proportions)
                if (px < 4 || bw <= 0 || bh <= 0) continue;
                NSDictionary *d = text_tex(dev, it->str, px, it->char_space * scale);
                id<MTLTexture> t = d[@"tex"];
                if (!t) continue;
                float w = [d[@"w"] floatValue] - 4, h = [d[@"h"] floatValue];
                BOOL glyph = NO;                                  // button glyphs are never squeezed
                for (const unsigned char *u = (const unsigned char *)it->str; *u; u++) if (*u == 0xEE) glyph = YES;   // utf-8 lead byte of U+E000..EFFF
                float sx = (w > bw && !glyph) ? bw / w : 1;       // squeeze text to fit the box
                float drawW = w * sx, drawH = h * sx;                // too long for its box: smaller, in proportion (a squeezed label looks tall and thin)
                int ox = it->origin & 3, oy = (it->origin >> 2) & 3;
                float left = X[0] + (ox == 1 ? 0 : ox == 2 ? bw - drawW : (bw - drawW) / 2);
                float padd = [d[@"pad"] floatValue] * sx;   // the texture has that much room above and below the font's own ascent and descent
                float top = Y[0] + (oy == 1 ? -padd : oy == 2 ? bh - drawH + padd : (bh - drawH) / 2);
                float gx[4] = {left - 2 * sx, left + drawW + 2 * sx, left - 2 * sx, left + drawW + 2 * sx};
                float gy[4] = {top, top, top + drawH, top + drawH};
                float uv[4][2] = {{0, 0}, {1, 0}, {0, 1}, {1, 1}}, col[4][4];
                for (int k = 0; k < 4; k++) {
                    const uint8_t *c = k < 2 ? it->top_color : it->bottom_color;
                    col[k][0] = c[0] / 255.0f; col[k][1] = c[1] / 255.0f; col[k][2] = c[2] / 255.0f; col[k][3] = c[3] / 255.0f * it->alpha;
                }
                [enc setFragmentTexture:t atIndex:0];
                quad(enc, gx, gy, uv, col);
            }
        }
        swkbd_ui_unlock();
        [enc endEncoding];
    }
}
