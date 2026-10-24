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

extern void (*g_overlay_render)(void *dev, void *cb, void *target);

static NSString *const kMsl =
    @"#include <metal_stdlib>\n"
    "using namespace metal;\n"
    "struct V { float2 pos; float2 uv; float4 col; };\n"
    "struct O { float4 p [[position]]; float2 uv; float4 col; };\n"
    "vertex O vs(uint i [[vertex_id]], constant V *v [[buffer(0)]], constant float2 &vp [[buffer(1)]]) {\n"
    "  O o; o.p = float4(v[i].pos.x / vp.x * 2.0 - 1.0, 1.0 - v[i].pos.y / vp.y * 2.0, 0, 1); o.uv = v[i].uv; o.col = v[i].col; return o; }\n"
    "fragment float4 fs(O in [[stage_in]], texture2d<float> t [[texture(0)]], sampler s [[sampler(0)]]) {\n"
    "  return t.sample(s, in.uv) * in.col; }\n";

typedef struct { float pos[2], uv[2], col[4]; } Vtx;

static id<MTLRenderPipelineState> g_pipe;
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
static NSAttributedString *make_attr(NSString *str, float px) {
    CTFontRef f = font_at(px), e = ext_at(px);
    NSMutableAttributedString *as = [[NSMutableAttributedString alloc] initWithString:str attributes:@{(__bridge id)kCTFontAttributeName: (__bridge id)f,
        (__bridge id)kCTForegroundColorFromContextAttributeName: @YES}];
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
        NSAttributedString *s = make_attr(@(utf8), px > 1 ? px : 1);
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
        if (px && lyt_tex_decode(t, px)) r = make_rgba(dev, (int)t->w, (int)t->h, px);
        free(px);
    }
    [g_tex setObject:r ?: (id)[NSNull null] forKey:key];
    return r;
}

// Text as a texture: white glyphs with alpha, so the vertex colour tints it. Size in device pixels.
static NSDictionary *text_tex(id<MTLDevice> dev, const char *utf8, float px) {
    NSString *key = [NSString stringWithFormat:@"%.1f|%s", px, utf8];
    NSDictionary *hit = g_text[key];
    if (hit) return hit;
    NSDictionary *res = nil;
    @autoreleasepool {
        NSAttributedString *s = make_attr(@(utf8), px);
        CTLineRef l = CTLineCreateWithAttributedString((__bridge CFAttributedStringRef)s);
        CGFloat asc, desc, lead;
        double w = CTLineGetTypographicBounds(l, &asc, &desc, &lead);
        int tw = (int)ceil(w) + 4, th = (int)ceil(asc + desc) + 4;
        if (tw > 0 && th > 0 && tw < 4096 && th < 1024) {
            CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
            CGContextRef cg = CGBitmapContextCreate(NULL, (size_t)tw, (size_t)th, 8, (size_t)tw * 4, cs, (CGBitmapInfo)kCGImageAlphaPremultipliedLast);
            CGContextSetRGBFillColor(cg, 1, 1, 1, 1);
            CGContextSetTextPosition(cg, 2, desc + 2);
            CTLineDraw(l, cg);
            id<MTLTexture> t = make_rgba(dev, tw, th, CGBitmapContextGetData(cg));   // row 0 of the bitmap is the top
            CGContextRelease(cg); CGColorSpaceRelease(cs);
            res = @{@"tex": t, @"w": @(tw), @"h": @(th), @"asc": @(asc)};
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

static void preview_check(void) {
    static long at = -1, frame;
    if (at < 0) at = getenv("BDSP_SWKBD_PREVIEW") ? atol(getenv("BDSP_SWKBD_PREVIEW")) : 0;
    if (at && ++frame == at) {
        SwkbdParams p = {0};
        p.minlen = 1; p.maxlen = 12;
        snprintf(p.header, sizeof p.header, "Enter your name");
        snprintf(p.sub, sizeof p.sub, "Up to 12 characters");
        snprintf(p.guide, sizeof p.guide, "Name");
        SwkbdCallbacks cb = {0};
        swkbd_ui_open(&p, cb, NULL);
    }
}

static void render(void *dev_, void *cb_, void *target_) {
    id<MTLDevice> dev = (__bridge id<MTLDevice>)dev_;
    id<MTLCommandBuffer> cb = (__bridge id<MTLCommandBuffer>)cb_;
    id<MTLTexture> target = (__bridge id<MTLTexture>)target_;
    preview_check();
    if (!swkbd_ui_active()) return;
    static int calls;
    if (getenv("BDSP_TRACE_APPLET") && calls++ % 60 == 0) fprintf(stderr, "[swkbd_overlay] render while active, target %lux%lu fmt %lu\n", (unsigned long)((__bridge id<MTLTexture>)target_).width, (unsigned long)((__bridge id<MTLTexture>)target_).height, (unsigned long)((__bridge id<MTLTexture>)target_).pixelFormat);
    @autoreleasepool {
        static CFAbsoluteTime last;
        CFAbsoluteTime now = CFAbsoluteTimeGetCurrent();
        double dt = last ? fmin(now - last, 0.1) : 0.016;
        last = now;
        if (!setup(dev, target.pixelFormat)) return;
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
        for (int i = 0; i < sc->n; i++) {
            const LytItem *it = &sc->items[i];
            float X[4], Y[4];
            for (int k = 0; k < 4; k++) { X[k] = off[0] + it->x[k] * scale; Y[k] = off[1] + it->y[k] * scale; }
            if (it->type == LYT_ITEM_QUAD) {
                id<MTLTexture> t = g_white;
                if (it->tex) { t = gpu_tex(dev, it->tex); if (!t) continue; }
                float col[4][4];
                for (int k = 0; k < 4; k++) { for (int c = 0; c < 3; c++) col[k][c] = it->col[k][c] / 255.0f; col[k][3] = it->col[k][3] / 255.0f * it->alpha; }
                [enc setFragmentTexture:t atIndex:0];
                quad(enc, X, Y, (const float (*)[2])it->uv, col);
            } else if (it->str && it->str[0]) {
                float bw = X[3] - X[0], bh = Y[3] - Y[0];
                float px = it->font_size[1] * scale;
                if (px < 4 || bw <= 0 || bh <= 0) continue;
                NSDictionary *d = text_tex(dev, it->str, px);
                id<MTLTexture> t = d[@"tex"];
                if (!t) continue;
                float w = [d[@"w"] floatValue] - 4, h = [d[@"h"] floatValue];
                float sx = w > bw ? bw / w : 1;                   // squeeze to fit the box
                float drawW = w * sx, drawH = h;
                int ox = it->origin & 3, oy = (it->origin >> 2) & 3;
                float left = X[0] + (ox == 1 ? 0 : ox == 2 ? bw - drawW : (bw - drawW) / 2);
                float top = Y[0] + (oy == 1 ? 0 : oy == 2 ? bh - drawH : (bh - drawH) / 2);
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

// While the keyboard is open the game thread is stopped inside the keyboard call and presents nothing; this thread then shows the last
// game image again (metal.m metal_repeat_present), which draws the keyboard over it through render().
extern uint64_t metal_last_present_ns(void);
extern void metal_repeat_present(void);

extern uint64_t SDL_GetTicksNS(void);

static void *keepalive(void *arg) {
    pthread_setname_np("swkbd-present");
    for (;;) {
        usleep(16000);
        if (!swkbd_ui_active()) continue;
        if (SDL_GetTicksNS() - metal_last_present_ns() < 50000000ull) continue;   // the game is presenting itself
        metal_repeat_present();
    }
    return NULL;
}

__attribute__((constructor)) static void swkbd_overlay_register(void) {
    g_overlay_render = render;
    swkbd_ui_set_display(1);
    pthread_t th;
    if (!pthread_create(&th, NULL, keepalive, NULL)) pthread_detach(th);
}
