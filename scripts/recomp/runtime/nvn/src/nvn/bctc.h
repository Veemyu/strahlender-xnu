// BC textures on GPUs without BC support (iPhone A13: supportsBCTextureCompression = 0). The game's BC blocks are converted
// while uploading: BC1/BC2/BC3/BC7 into ASTC 4x4 (same block grid, 16 bytes per block), BC4/BC5 into R8/RG8 texels.
// BC6H is not converted (the game does not use it in the measured scenes).
#pragma once
#include <stdint.h>

enum { BCTC_NONE = 0, BCTC_ASTC, BCTC_ASTC_SRGB, BCTC_R8, BCTC_R8S, BCTC_RG8, BCTC_RG8S };

// What a guest NVN format becomes; BCTC_NONE for formats that are uploaded unchanged.
int bctc_kind(uint32_t nvn_format);
// wb x hb x d blocks (rows of wb blocks, tightly packed) -> malloc'd data for the Metal upload.
// *row: bytes per row, *rows: rows per 2D image (ASTC: block rows, R8/RG8: texel rows).
uint8_t *bctc_convert(uint32_t nvn_format, const uint8_t *src, uint32_t wb, uint32_t hb, uint32_t d, uint32_t *row, uint32_t *rows);

// Building blocks (scripts/recomp/runtime/nvn/test/bctc_test.m)
void bctc_decode_rgba(uint32_t nvn_format, const uint8_t *blk, uint8_t px[16][4]);   // BC1/2/3/7, texel y * 4 + x
void bctc_decode_bc4(const uint8_t blk[8], int is_signed, uint8_t out[16]);
void bctc_astc_encode(const uint8_t px[16][4], uint8_t out[16]);
void bctc_astc_from_bc1(const uint8_t bc1[8], uint8_t out[16]);
// The colours the encoder meant for an ASTC block it wrote (its own decode of the modes it uses; 0 for other blocks)
int bctc_astc_decode(const uint8_t blk[16], uint8_t px[16][4]);
