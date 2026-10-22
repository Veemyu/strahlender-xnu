# Shaders: the Maxwell-to-MSL translator and the offscreen harness

The game's shaders are Nvidia Maxwell machine code. At run time the NVN layer hands each program to the translator in
`shader_translator/`, which produces Metal Shading Language (MSL). This page describes the translator, how its correctness was
measured, and the offscreen harness used for reference renders. For where it sits in the renderer see
[architecture.md](architecture.md); for renderer debugging see [rendering.md](rendering.md).

The translator started as the LASRecomp translator (MIT; provenance and every change in `shader_translator/NOTICE.md`). It builds
as a standalone tool, `maxwell2msl`, and is also linked into the runtime (`prepare.sh` uses it instead of the LAS copy). Shader
binaries and reports are generated locally under the ignored `work/shaders/`.

## 1. Layout and usage

| File (`shader_translator/`) | Contents |
|---|---|
| `translate.c`, `shader.h` | Maxwell code to MSL (changed from LASRecomp; a GLSL path remains, untested) |
| `container.c`, `container.h` | reader for the game's shader programs (container magic `0x0C07513C`, control `0x98761234`, blob starts at `0x12345678`) |
| `main.c`, `survey_report.py`, `Makefile`, `tests/` | the `maxwell2msl` tool, coverage report, build and tests |

```sh
make -C shader_translator            # builds build/maxwell2msl
make -C shader_translator test       # C checks, CLI tests, report tests (synthetic data)
make -C shader_translator asan       # same with AddressSanitizer/UBSan

shader_translator/build/maxwell2msl prog.bin -o prog.metal --info prog.json     # a game program: the stage comes from the container
shader_translator/build/maxwell2msl --stage fs blob.bin                         # a raw blob needs --stage vs|fs|cs
shader_translator/build/maxwell2msl --survey --batch list.txt -o survey.jsonl   # coverage; one JSON line per shader
```

Main options: `--info` (resource map), `--cbuf1 <file>` (compiler constants), `--attr-kind N=f|i|u`, `--rt-kind N=f|i|u`,
`--vs-out-mask`, `--flip-y`, `--depth-minus-one`, `--rscale`, `--fast-math` (omit the exactness pragmas). Exit codes: 0 success, 1
translation failed (survey: issues found), 2 usage, 3 input/output error. Extraction of the shaders from the game data into
`work/shaders/blobs/` is done by `scripts/shader_extract_blobs.py`.

## 2. Differences from upstream

1. **Survey mode:** collects every unknown opcode and unsupported form instead of stopping at the first error.
2. **Code end:** padding after `EXIT` jumps to the preceding scheduling word (offset -16), not -8; otherwise compiler constants were
   read as instructions.
3. **Bindless textures (`TEX.B`)**, `HSETP2` with constant-buffer and immediate operands, a resource map (`--info`), pragmas against
   fast math and FMA contraction, and `--half-compat` (an oracle that imitates Ryujinx's unrounded fp16). Each change is marked `XNU:`.
4. LAS-specific behavior removed (debug hooks, `getenv` switches, the tint epilogue); no resolution scaling by default.
5. Still unchanged: the GLSL path, `flip_x`, global-memory globals, non-thread-safe static buffers, unbounded `sprintf`.

## 3. Coverage

The corpus holds 13,710 programs (6,878 vertex, 6,832 fragment) in 4,276 unique Maxwell blobs (2,859 unique code bodies).
Initially fragment shaders were practically untranslatable (0.3 %), because the game samples textures through handles. After adding
`TEX.B` and `HSETP2` **all 4,276 blobs are recognized**, all 8,552 generated MSL files compile with Metal, and a run under
AddressSanitizer/UBSan reports nothing. Translating everything takes about 0.5 s. "Recognized" only means no unknown instruction;
correctness is the subject of section 5.

**How a bindless handle is built.** The compiler emits `MOV Rh, c[2][s]` followed by `LOP.OR Rh, Rh, c[2][t]`. A handle holds the
texture ID in the low 20 bits and the sampler ID in the high 12 bits. The two words live in two tables of constant buffer 2 that start
at `0x168` and `0x568` (8 bytes per entry). The translator records the word offsets, so the table entry is known at translation
time and MSL needs no runtime handle. At run time the **texture** is taken from the table starting at `0x168` and the **sampler**
from the one starting at `0x568`; the first analysis had this the wrong way round and bound wrong textures (found during the Vulkan
bring-up, see [recomp-linux.md](recomp-linux.md)). Of 13,134 texture slots in the corpus all come from constant buffer 2, 13,130
are 2D and 4 are cube.

## 4. Resource map and exact arithmetic

`--info` writes a machine-readable map (stage, Metal binding conventions, constant buffers with size and the statically read range,
textures with slot, type, word offsets and table index, inputs and outputs). Constant-buffer roles: cbuf 0 driver constants, cbuf 1
compiler constants (they follow the code in the blob, rounded to 0x100; `--cbuf1` writes them out), cbuf 2 handle tables, cbuf 3+
the game's uniform blocks. The driver table index of an entry is `(wordOffset - tableBase) / 8` with the table bases `0x168` and `0x568` (see section 3).

Metal defaults to fast math and contracts `a*b+c` into FMA; the Switch GPU rounds every multiply and add. The translator therefore
writes `#pragma METAL fp math_mode(safe)` and `#pragma METAL fp contract(off)` at the start of every MSL file. Measured on macOS 26:
`mathMode = .safe` alone does *not* stop FMA contraction (only `contract(off)` does), and the options visibly change chaotic test
shaders (differences up to 253 levels). Instruction FTZ and rounding flags are not evaluated; denormals are unmeasured.

## 5. Fidelity test (`scripts/shader_fidelity.py`)

For 500 shader pairs the translator's output was rendered next to the reference (Ryujinx's SPIR-V converted with `spirv-cross`) with
identical synthetic inputs (a 12x12 grid, 42 deterministic constant-buffer profiles, 64x64 textures, 128x128 target, no blending
or depth) and compared with `scripts/shader_compare.py`. *Pass* means a difference of at most 1 level per channel.

| Result (500 pairs, 62 shaders, M1 Pro) | Pairs |
|---|---:|
| Pass | 332 (155 bit-identical) |
| Near (at most 3 levels) | 11 |
| Fail | 44 |
| Uninformative (monochrome or empty reference) | 98 |
| Unsupported (memory buffers, cube textures) | 15 |

Among the 387 informative pairs 85.8 % pass; 95.1 % pass when Ryujinx's fp16 behavior is taken out. All 159 pairs that use no
packed-half instructions pass. The differences come from two things:
- **Ryujinx does not round fp16.** Switch shaders use `half`, and the hardware rounds each half result; Ryujinx removes the
  pack/unpack pairs and computes in fp32. Our output rounds, which is *suspected* to be the faithful behavior, but there is no
  hardware reference to prove it. `--half-compat` imitates Ryujinx (36 of the 55 differing pairs then pass).
- **NaNs from fp16 overflow** at extreme synthetic inputs (about 15 `Delphis/Map/Standard` pairs, 0.4 to 0.6 % of pixels), and a few
  chaotic edge pixels.

Not the cause: binding, register allocation, interpolation, clip space (texture keys match in 970 of 970 stages). Limits of the
test: synthetic inputs, one draw, 2D textures only, a Ryujinx reference rather than hardware.

## 6. Open items

1. Check fp16 rounding against hardware or an emulator that rounds.
2. Resolve the remaining NaN pairs at instruction level (HFMA2/HMUL2 overflow microtests).
3. Cube, array and shadow textures and memory buffers in the harness; `noperspective`/`flat`/`centroid` against a reference.
4. Instruction microtests (MUFU variants, F2I rounding, SHF/BFE/PRMT/XMAD, denormals) and a decoder cross-check.
5. Hardening, the GLSL path, and removing the dead handle-word reads from the MSL (they force an extra buffer binding).
6. Subgroup shuffle instructions and a second storage buffer are not supported (a few fragment blobs).

## 7. The offscreen harness (`scripts/shader_harness/`)

A Swift command-line program that translates a vertex/fragment pair (from the Ryujinx cache or MSL), compiles it with Metal and
renders it offscreen to a PNG: a reproducible reference renderer. It opens no window; outputs go under `work/shaders/`; test data
is synthetic.

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
python3 scripts/shader_cache_extract.py --index 68 2741 136                   # export SPIR-V from the Ryujinx cache
swift build -c release --package-path scripts/shader_harness --scratch-path work/shaders/build
H=work/shaders/build/release/shader-harness
$H info   scripts/shader_harness/examples/pair_0068.json                       # show the bindings
$H render scripts/shader_harness/examples/pair_0068.json --out work/shaders/out/pair_0068.png --dump-msl work/shaders/out/msl_0068
python3 scripts/shader_compare.py a.png b.png --threshold 2 --diff work/shaders/out/diff.png --max-diff 3 --min-psnr 40
```

`spirv-cross` is found in `/opt/homebrew/bin`, `/usr/local/bin` or `PATH` (or `SPIRV_CROSS=<path>`). A spec (JSON) describes the
size, vertex and fragment sources, draw call, vertex buffers and attributes, uniform buffers, textures with sampler, and render state;
unknown keys are errors; see `scripts/shader_harness/examples/`. Reproducibility: fixed pipeline, `rgba8Unorm`, no MSAA, no random
values; two renders were bit-identical on the M1 Pro.

Limits: one draw call, one color target (optional depth), 2D textures only, a few vertex and texture formats, no compute or
tessellation, render state from the spec rather than the cache, `storageModeShared` assumed (Apple Silicon), and the clip-space
conventions (`flipVertY`, `fixupClipspace`) must be set per comparison.

## 8. Reproduction

```sh
make -C shader_translator test
swift build -c release --package-path scripts/shader_harness --scratch-path work/shaders/build
python3 -m unittest scripts/tests/test_shader_fidelity.py scripts/tests/test_shader_compare.py scripts/tests/test_shader_extract.py
PYTHONPATH=tools/pydeps python3 scripts/shader_fidelity.py index        # once: work/shaders/prog_blob.json
python3 scripts/shader_cache_extract.py                                  # all SPIR-V modules to work/shaders/spirv
python3 scripts/shader_fidelity.py run --count 500 --jobs 4              # about 10 minutes; report work/shaders/fidelity_report.json
```

Reports, images and per-pair files stay under `work/shaders/` and never go into the repository.
