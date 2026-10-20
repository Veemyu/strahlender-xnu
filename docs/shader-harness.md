# Shader harness: offscreen reference renderer for cached shaders (as of 2026-10-18)

A custom command-line program (Swift, Swift Package under `scripts/shader_harness/`) that translates a vertex/fragment pair from the Ryujinx shader cache to MSL, compiles it at runtime with Metal, and renders it offscreen to a PNG. Its goal is a reproducible reference renderer for differential tests. The same inputs will later be passed through a shader ported to Unity, followed by a pixel comparison with `scripts/shader_compare.py`.

It opens no window and plays nothing. All outputs go under `work/shaders/` (gitignored). Test data is synthetic (gradient, checkerboard), with no game textures.

## Components

| File | Purpose |
|---|---|
| `scripts/shader_cache_extract.py` | Reads `vulkan_apple.toc/.data` (read-only) and writes SPIR-V to `work/shaders/spirv/<index>_<stage>.spv` |
| `scripts/shader_harness/` | Swift package `shader-harness` (renderer) and `examples/*.json` (three example specs) |
| `scripts/shader_compare.py` | PNG comparison, standard library only |
| `scripts/tests/test_shader_compare.py` | 20 tests using synthetic images |

## Usage

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer

# 1. Export modules (stages: vert, frag, comp; also writes index.json)
python3 scripts/shader_cache_extract.py --smallest 12 --list           # list smallest pairs
python3 scripts/shader_cache_extract.py --index 68 2741 136            # export selected indices

# 2. Build the harness (build directory deliberately under work/)
swift build -c release --package-path scripts/shader_harness --scratch-path work/shaders/build

# 3. Render
H=work/shaders/build/release/shader-harness
$H info   scripts/shader_harness/examples/pair_0068.json        # show bindings; do not render
$H render scripts/shader_harness/examples/pair_0068.json --out work/shaders/out/pair_0068.png \
          --dump-msl work/shaders/out/msl_0068                  # also save MSL

# 4. Compare
python3 scripts/shader_compare.py a.png b.png --threshold 2 --diff work/shaders/out/diff.png \
          --max-diff 3 --min-psnr 40
python3 -m unittest scripts/tests/test_shader_compare.py
```

`spirv-cross` is searched for in `/opt/homebrew/bin`, `/usr/local/bin`, and `PATH` (or supplied through `SPIRV_CROSS=<path>`). Translation uses `--msl --msl-version 20300`; compilation uses Metal language version 2.3.

`--xcrun-check` (with `--dump-msl`) also tries `xcrun metal -c`. This fails on this machine because the Metal toolchain is not installed; compilation is therefore checked through `MTLDevice.makeLibrary`.

The program exits 0 on success, 1 on errors (spec, translation, compiler, GPU), and 2 for incorrect usage. On `render`, the final line reports the path, dimensions, number of pixels differing from the clear color, and SHA-256 of the RGBA bytes. The hash is a quick reproducibility check.

## Input format (JSON)

Relative paths are resolved from the JSON file's directory. Unknown keys are errors (to catch typos). Complete examples are under `scripts/shader_harness/examples/`.

| Key | Meaning |
|---|---|
| `size` | `[width, height]`, default `[256, 256]`, format `rgba8Unorm` |
| `clearColor`, `clearDepth` | Background RGBA (0–1), depth (default 1) |
| `vertex`, `fragment` | Each accepts `spirv` **or** `msl` (file), optional `entry` (default `main0`), `flipVertY`, `fixupClipspace`, `spirvCrossArgs` |
| `topology` | `triangle`, `triangleStrip`, `line`, `lineStrip`, `point` |
| `vertexCount`, `instanceCount`, `indices` (plus `indexType` `uint16`/`uint32`) | Draw call; if `vertexCount` is omitted, it is derived from buffer size and stride |
| `vertexBuffers[]` | `slot`, optional `stride`, `step` (`vertex`/`instance`), and exactly one data source (see below) |
| `attributes[]` | `location`, `buffer` (slot), `offset`, `format` (`float`…`float4`, `int*`, `uint*`, `uchar4`, `uchar4Normalized`, `ushort2/4`, `half2/4`) |
| `buffers[]` | Uniform buffers: `stage` (`vertex`/`fragment`), `slot`, optional `size` (minimum size), either a direct data source or `writes[]` with `offset` (bytes) or `offsetFloats` and a data source |
| `textures[]` | `stage`, `slot`, optional `samplerSlot`, `format` (`rgba8Unorm`, `rgba8Unorm_srgb`, `r8Unorm`), `mipmaps`, `sampler`; source is `file` (PNG/JPEG) or `generate` (`solid`, `checker`, `gradient`) |
| `sampler` | `min`, `mag` (`nearest`/`linear`), `mip` (`none`/`nearest`/`linear`), `address` or `s`/`t`/`r` (`clamp`, `repeat`, `mirror`, `border`) |
| `state` | `cull` (`none`/`front`/`back`), `frontFace` (`ccw`/`cw`), `wireframe`, `colorMask` (e.g. `"rgb"`), `blend` (preset: `alpha`/`additive`/`premultiplied`, or `srcRGB`, `dstRGB`, `opRGB`, `srcA`, `dstA`, `opA`), `depth` (`test`, `write`) |
| `viewport` | `[x, y, width, height]`, default: full image |

**Data sources** (exactly one per entry): `floats`, `ints`, `uints`, `bytes` (0–255), or `file` (raw bytes). All values are little-endian. Uniform-buffer data uses the same forms, including “float list or byte array.”

**Cache conventions:** MSL output places each stage's constant buffer at `buffer(0)` (`float4[4096]`, 64 KB). Vertex data therefore belongs in another slot; examples use 30. Buffer size is taken from Metal reflection and padded with zeros. `info` shows the bindings required by a pair (buffers, textures, samplers, attributes). Unspecified values in buffers remain 0; a warning appears if an entire buffer is missing.

## Reproducibility

- Target format `rgba8Unorm` (no sRGB conversion), fixed pipeline, no random values, no MSAA, no anisotropy.
- PNG output uses ImageIO, with non-premultiplied alpha. Raw pixel bytes from the PNG match the reported hash (cross-checked with the decoder in `shader_compare.py`).
- Two renders produced bit-identical PNGs (`cmp`) and identical comparison values (maximum difference 0, PSNR inf). This holds on this machine (Apple M1 Pro); other GPUs may differ in floating-point operations, interpolation, and mip generation.

## Comparison script

`shader_compare.py a.png b.png` reports `max_abs_diff`, `mean_abs_diff` (over all channel values), `pixels_over` (pixels with at least one channel above `--threshold`), `mse`, and `psnr` (inf for identical images). `--ignore-alpha` compares RGB only; `--diff` writes a difference image (`--diff-gain` amplifies it); `--json` emits machine-readable output. `--max-diff`, `--max-pixels`, and `--min-psnr` make the exit code 1 when a limit is exceeded (2 for read or size errors). The custom PNG decoder supports all color types, bit depths 1–16, Adam7, and `tRNS`; it checks CRCs and ignores color profiles.

## Test results (Apple M1 Pro, macOS 26, Metal language 2.3)

Three pairs from the local cache, smallest first. Sizes are in bytes (vertex + fragment); all inputs are synthetic.

| Index | SPIR-V | Test | Result |
|---|---|---|---|
| 68 | 3120 + 2388 | Quad from 2 triangles, rotated/scaled by uniform, texture (gradient, linear), fragment outputs `min(texture.x, uniform)` | Red, gradient clamped at 0.75; 10,404 pixels covered |
| 2741 | 5684 + 952 | Triangles with index buffer, two 4×4 matrices from uniform, back-face culling, depth test, `colorMask` `rgb`; fragment writes constant 0 | One black triangle; the clockwise triangle is culled; alpha remains 1; 8,194 pixels |
| 136 | 6044 + 2588 | Triangle strip, UV attribute, checkerboard with alpha, `discard_fragment` at alpha threshold, color from uniform | Orange checkerboard, transparent cells discarded; 26,450 pixels |

- All three pairs translate, compile, and render without errors. A second run was bit-identical (difference 0).
- Also checked: PNG texture input (`r8Unorm`, mipmaps, `repeat`), and error messages for missing texture, missing attribute, and unknown JSON key.
- `scripts/tests/test_shader_compare.py`: 20 tests pass (all decoder filters, color types, bit depths, Adam7, palette/`tRNS`, malformed files; metrics; CLI; cross-check against `sips`).

## Limitations

- **One draw call**, one color target (`rgba8Unorm`), optional `depth32Float`. No MSAA, stencil, compute shaders, geometry, or tessellation (none occur in the cache).
- **Bindings:** uniform buffers, 2D textures, and samplers, each for vertex and fragment stages. No cube/array/3D textures, storage buffers, argument buffers, or specialization constants. Samplers are described through textures (`samplerSlot`); comparison samplers and anisotropy are unsupported.
- **Texture formats:** `rgba8Unorm`, `rgba8Unorm_srgb`, `r8Unorm`. No compressed formats (BCn/ASTC) or float textures. PNGs load through Core Graphics as premultiplied sRGB RGBA; this changes color values for transparent pixels. `r8Unorm` uses the red channel.
- **Vertex formats** are limited to those listed above; packed formats (`10_10_10_2`) are unsupported.
- **Clip space:** unchanged by default. Whether a cached shader needs `--flip-vert-y` and/or `--fixup-clipspace` (Ryujinx uses Vulkan conventions and viewport tricks) is unresolved and must be set for each comparison. The option is set per stage in the spec.
- **Render state** comes from the JSON file, not the cache (`shared.data` contains specialization state that is not interpreted here).
- Input mapping (which attribute is position, which uniform float has which meaning) was read manually from MSL; the harness does not infer it.
- The reflection API (`MTLArgument`) is marked deprecated from macOS 13; the build emits warnings but works.
- The renderer assumes `storageModeShared` (Apple Silicon GPU); on Intel/discrete GPUs, synchronization is missing before readback.
- Still open: a real Unity comparison. Metrics are ready, but thresholds (e.g. 1–3 channel levels for rounding, interpolation, and color space) have not been calibrated against a ported shader.
