// Test of the BC conversion for GPUs without BC (nvn/src/nvn/bctc.c), on a Mac GPU that decodes BC and ASTC itself:
//  1. bctc's BC decoders against Metal's BC decoding (random blocks, every BC format the game uses)
//  2. the ASTC blocks bctc writes against Metal's ASTC decoding of them: must equal bctc's own reading (bit layout)
//  3. the error of the conversion against the original BC texels (PSNR, maximum)
// Synthetic data only (no game files). Usage: run_bctc_test.sh
#import <Metal/Metal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#include "bctc.h"

static id<MTLDevice> dev;
static id<MTLCommandQueue> q;
static id<MTLComputePipelineState> rd_pipe;

// All texels of a 2D texture as floats (RGBA)
static float *read_back(id<MTLTexture> t) {
    NSUInteger n = t.width * t.height;
    id<MTLBuffer> out = [dev newBufferWithLength:n * 16 options:MTLResourceStorageModeShared];
    id<MTLCommandBuffer> cb = [q commandBuffer];
    id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
    [e setComputePipelineState:rd_pipe];
    [e setTexture:t atIndex:0];
    [e setBuffer:out offset:0 atIndex:0];
    uint32_t w = (uint32_t)t.width;
    [e setBytes:&w length:4 atIndex:1];
    [e dispatchThreads:MTLSizeMake(t.width, t.height, 1) threadsPerThreadgroup:MTLSizeMake(8, 8, 1)];
    [e endEncoding];
    [cb commit];
    [cb waitUntilCompleted];
    float *f = malloc(n * 16);
    memcpy(f, out.contents, n * 16);
    return f;
}

static id<MTLTexture> make(MTLPixelFormat pf, uint32_t w, uint32_t h, const void *data, uint32_t row) {
    MTLTextureDescriptor *d = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:pf width:w height:h mipmapped:NO];
    d.usage = MTLTextureUsageShaderRead;
    id<MTLTexture> t = [dev newTextureWithDescriptor:d];
    [t replaceRegion:MTLRegionMake2D(0, 0, w, h) mipmapLevel:0 withBytes:data bytesPerRow:row];
    return t;
}

static uint32_t rng = 12345;
static uint32_t rnd(void) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }

// Random blocks; with smooth = 1 the endpoints of BC1/BC3 colour parts are close together (like real textures)
static void fill(uint8_t *b, size_t n, int bpb, uint32_t fmt, int smooth) {
    for (size_t i = 0; i < n * bpb; i++) b[i] = (uint8_t)rnd();
    if (!smooth) return;
    for (size_t i = 0; i < n; i++) {
        uint8_t *c = b + i * bpb + (bpb == 16 && fmt != 0x4D ? 8 : 0);
        if (fmt == 0x4D) continue;
        uint16_t c0 = (uint16_t)(c[0] | c[1] << 8), c1 = (uint16_t)(c0 ^ (rnd() & 0x0841));
        c[2] = (uint8_t)c1; c[3] = (uint8_t)(c1 >> 8);
    }
}

static int test_rgba(const char *name, uint32_t fmt, MTLPixelFormat bc_pf, int bpb, int smooth) {
    const uint32_t W = 256, H = 256, BW = W / 4, BH = H / 4, NB = BW * BH;
    uint8_t *blk = malloc((size_t)NB * bpb);
    fill(blk, NB, bpb, fmt, smooth);
    float *ref = read_back(make(bc_pf, W, H, blk, BW * bpb));
    // 1. own decoder
    int dec_max = 0;
    for (uint32_t i = 0; i < NB; i++) {
        uint8_t px[16][4];
        bctc_decode_rgba(fmt, blk + (size_t)i * bpb, px);
        for (int t = 0; t < 16; t++) {
            uint32_t x = (i % BW) * 4 + t % 4, y = (i / BW) * 4 + t / 4;
            for (int c = 0; c < 4; c++) {
                int r = (int)lrintf(ref[((size_t)y * W + x) * 4 + c] * 255), d = abs(r - px[t][c]);
                if (d > dec_max) dec_max = d;
            }
        }
    }
    // 2./3. conversion
    uint32_t row, rows;
    uint64_t t0 = clock_gettime_nsec_np(CLOCK_UPTIME_RAW);
    uint8_t *astc = bctc_convert(fmt, blk, BW, BH, 1, &row, &rows);
    double ns_blk = (double)(clock_gettime_nsec_np(CLOCK_UPTIME_RAW) - t0) / NB;
    float *got = read_back(make(MTLPixelFormatASTC_4x4_LDR, W, H, astc, row));
    int layout_max = 0, err_max = 0;
    double se = 0;
    for (uint32_t i = 0; i < NB; i++) {
        uint8_t own[16][4];
        bctc_astc_decode(astc + (size_t)i * 16, own);
        for (int t = 0; t < 16; t++) {
            uint32_t x = (i % BW) * 4 + t % 4, y = (i / BW) * 4 + t / 4;
            for (int c = 0; c < 4; c++) {
                int g = (int)lrintf(got[((size_t)y * W + x) * 4 + c] * 255), r = (int)lrintf(ref[((size_t)y * W + x) * 4 + c] * 255);
                if (abs(g - own[t][c]) > layout_max) layout_max = abs(g - own[t][c]);
                if (abs(g - r) > err_max) err_max = abs(g - r);
                se += (double)(g - r) * (g - r);
            }
        }
    }
    double psnr = se > 0 ? 10 * log10(255.0 * 255.0 / (se / ((double)W * H * 4))) : 99;
    int ok = dec_max <= 2 && layout_max <= 1;
    printf("%-14s decoder vs Metal max %d | ASTC: Metal vs own reading max %d | vs BC: PSNR %.1f dB, max %d | %.0f ns/block  %s\n", name,
           dec_max, layout_max, psnr, err_max, ns_blk, ok ? "ok" : "FAILED");
    free(blk); free(ref); free(got); free(astc);
    return ok;
}

static int test_bc45(const char *name, uint32_t fmt, MTLPixelFormat bc_pf, MTLPixelFormat out_pf, int ch, int sgn) {
    const uint32_t W = 128, H = 128, BW = W / 4, BH = H / 4, NB = BW * BH;
    uint8_t *blk = malloc((size_t)NB * 8 * ch);
    fill(blk, NB, 8 * ch, fmt, 0);
    float *ref = read_back(make(bc_pf, W, H, blk, BW * 8 * ch));
    uint32_t row, rows;
    uint8_t *texels = bctc_convert(fmt, blk, BW, BH, 1, &row, &rows);
    float *got = read_back(make(out_pf, W, H, texels, row));
    int mx = 0;
    for (uint32_t i = 0; i < W * H; i++)
        for (int c = 0; c < ch; c++) {
            float s = sgn ? 127.0f : 255.0f;
            int d = abs((int)lrintf(ref[i * 4 + c] * s) - (int)lrintf(got[i * 4 + c] * s));
            if (d > mx) mx = d;
        }
    int ok = mx <= 2 && rows == H && row == W * (uint32_t)ch;   // (Metal interpolates in float: up to 2 steps apart, as the RGBA decoders)
    printf("%-14s converted texels vs Metal's BC decoding: max %d  %s\n", name, mx, ok ? "ok" : "FAILED");
    free(blk); free(ref); free(got); free(texels);
    return ok;
}

int main(void) {
    @autoreleasepool {
        dev = MTLCreateSystemDefaultDevice();
        if (!dev.supportsBCTextureCompression || ![dev supportsFamily:MTLGPUFamilyApple2]) { printf("needs a GPU with BC and ASTC (Apple silicon Mac)\n"); return 2; }
        q = [dev newCommandQueue];
        NSError *err = nil;
        id<MTLLibrary> lib = [dev newLibraryWithSource:@"#include <metal_stdlib>\nusing namespace metal;\n"
                                "kernel void rd(texture2d<float, access::read> t [[texture(0)]], device float4 *o [[buffer(0)]],"
                                " constant uint &w [[buffer(1)]], uint2 g [[thread_position_in_grid]]) { o[g.y * w + g.x] = t.read(g); }"
                                               options:nil error:&err];
        rd_pipe = [dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"rd"] error:&err];
        int ok = 1;
        ok &= test_rgba("BC1 random", 0x42, MTLPixelFormatBC1_RGBA, 8, 0);
        ok &= test_rgba("BC1 smooth", 0x42, MTLPixelFormatBC1_RGBA, 8, 1);
        ok &= test_rgba("BC2 random", 0x43, MTLPixelFormatBC2_RGBA, 16, 0);
        ok &= test_rgba("BC3 random", 0x44, MTLPixelFormatBC3_RGBA, 16, 0);
        ok &= test_rgba("BC3 smooth", 0x44, MTLPixelFormatBC3_RGBA, 16, 1);
        ok &= test_rgba("BC7 random", 0x4D, MTLPixelFormatBC7_RGBAUnorm, 16, 0);
        ok &= test_bc45("BC4 unorm", 0x49, MTLPixelFormatBC4_RUnorm, MTLPixelFormatR8Unorm, 1, 0);
        ok &= test_bc45("BC4 snorm", 0x4A, MTLPixelFormatBC4_RSnorm, MTLPixelFormatR8Snorm, 1, 1);
        ok &= test_bc45("BC5 unorm", 0x4B, MTLPixelFormatBC5_RGUnorm, MTLPixelFormatRG8Unorm, 2, 0);
        ok &= test_bc45("BC5 snorm", 0x4C, MTLPixelFormatBC5_RGSnorm, MTLPixelFormatRG8Snorm, 2, 1);
        printf("%s\n", ok ? "ALL OK" : "FAILURES");
        return ok ? 0 : 1;
    }
}
