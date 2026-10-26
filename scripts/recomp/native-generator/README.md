# Native BDSP generator

C17 replacement for the instruction analysis, code emission and module-image
builder. `gen` implements the complete iterative analysis, ordered native Unicorn
jump-table resolution, EH-aware function emission, deterministic chunking,
registration tables and partial-build stubs. Python only compiles/caches the C
tool and orchestrates the surrounding build. No game bytes or generated game
output belong in this directory.

## Build

```sh
python3 scripts/recomp/native-generator/build.py --require-unicorn
work/native-generator/bdsp_codegen --version --json
```

A C17 compiler is required (`clang`, or `--cc gcc`). The small Python build helper
only invokes the compiler and verifies/caches the result; the resulting executable
has no Python dependency. It builds without CMake, pip, pkg-config or network access.
The complete generator requires the pinned Unicorn 2.1.4 C headers and shared
library from the existing runtime package. Its Python bindings are not called.
The helper finds the package without importing it; `--unicorn-root PATH` or
`BDSP_UNICORN_ROOT` can supply just `include/` and `lib/` on CLI-only systems.
`--require-unicorn` rejects a missing engine before compilation. Without it,
image/lifter checkpoints can still be built without Unicorn.

The cached tool includes hashes of the compiler, C sources/headers, LZ4 provenance
and native Unicorn headers/library. The shared library is copied next to the tool
and located using a relative loader path; moving the tool and its `.deps` directory
together preserves execution. Vendored LZ4 1.9.4 is checked against `vendor/lz4/source.json` before compiling.
Build output, temporary files and comparisons default to ignored `work/`.
`--output PATH` selects another output. `--sanitize` enables AddressSanitizer/UBSan.
No build files are added to the repository root.

`--version --json` reports the source/toolchain fingerprint, native host,
interface version and capabilities. A cached executable is accepted only if both
its build fingerprint and its binary SHA-256 match. Paths are passed as distinct
arguments, including spaces, apostrophes and Unicode. On Windows the executable
uses a Unicode command line and file APIs; Windows builds have not been validated.

## Image command

```sh
work/native-generator/bdsp_codegen image work/exefs/main main \
  --base 0x7000000000 --out work/native-generator/images
```

Options match the image pipeline: `--hle-base`, repeatable `--link`, `--hle-list`,
and `--interpose-from`. Only the existing default `--interpose-regex`
`^(_Zn[wa]|_Zd[la]|_ZT[IS])` is accepted; other patterns fail explicitly.

Outputs are `<module>.img`, `<module>.mod`, `<module>.syms.json` and the shared
`hle.txt`. Relocation order, HLE-slot order, weak-symbol handling, default
interposition, JSON escaping/spacing and newline conventions match the reference.
Existing HLE slots are preserved between module invocations. The orchestrator
still controls the two-pass export/import sequence.

Input/container errors are exit code 4; argument errors 2; filesystem errors 5.
`--events=jsonl` emits structured errors and image completion. Error diagnostics
contain phase/module and cause, not input filenames. Generated files are replaced
through temporary files; identical files retain their timestamps. There is no
implicit fallback to Python.

## Initial analysis checkpoint

```sh
work/native-generator/bdsp_codegen inspect work/exefs/main main \
  --base 0x7000000000 > work/native-generator/main-analysis.json
```

This read-only development command emits sorted function boundaries, initial
entries, landing pads, setjmp returns and the count of retained ADR table bases.
It accepts `--entry-offsets` and repeatable `--setjmp-at`. It implements the
initial analysis before the function-scan fixpoint: NSO symbols/relocations,
CIE/FDE/LSDA metadata, direct calls, ADR/ADRP candidates and setjmp PLT discovery.
Unicorn jump-table scanning and C emission are subsequent milestones, not hidden
behind this command.

## Instruction-lifter checkpoint

`decode` reads one hexadecimal instruction per line on stdin and emits diagnostic
IR as JSONL. `--pc` selects the guest address; `--simd asm|c` selects system-register
semantics and portable CRC emission; `--previous-word` supplies context for
EH-aware return handling.

```sh
printf '91000400\nd65f03c0\n' | work/native-generator/bdsp_codegen decode \
  --pc 0x801001000 --simd c
```

Immediate arithmetic/logical/bitfield/move instructions, PC-relative operations,
branches, system registers, exception instructions and EH return overrides are
ported. Scalar load/store, exclusive pairs, register arithmetic, multiply/divide,
conditional operations and portable CRC emission are also implemented. Addressing,
writeback order, sign extension and generated expressions match the frozen Python
reference, including its handling of reserved encodings.

Tests exhaust immediate bit-mask encodings and add seeded scalar encodings,
comparing over 69,000 IR records plus CRC cases. A local differential check also
matched 44,012 sampled scalar instructions from existing Vanilla/Lumi modules;
no game data or samples are checked in. GCC builds on Linux x86-64 and AArch64
matched a further 12,007 synthetic instruction records against frozen-reference
outputs. macOS tests also pass with ASan/UBSan and the bundled Python runtime.

AArch64 SIMD/FP and CRC assembly metadata are now implemented as well: ordered
GPR mappings (including SP), touched vector registers, flags and literal constants.
A further 9,860 seeded assembly IR records match the frozen lifter, including
vector register wrapping and negative diagnostic PC-relative constants.
Portable SIMD/FP C lowering is now ported as well: scalar FP, vector arithmetic,
copy/permute/table operations, crypto/CRC, shifts, indexed operands and all SIMD
load/store forms supported by the frozen generator. Over 90,000 additional
portable IR comparisons cover seeded and systematic size/opcode/immediate fields.
A compiled mixed memory/vector/FP probe matches native AArch64 execution on macOS
and Linux ARM64. Existing SIMD runtime helpers are reused unchanged.
Temporary expression strings use thread-local checkpoint arenas. Each worker owns
its error context and formatting state; Darwin workers use private locales to
avoid contention in the system text formatter.

## Function C-emission checkpoint

`emit-function NSO --base N --entry N --end N` emits one function from an
**explicitly supplied analysis result**. It does not discover final partitions or
jump tables. Use `gen` for the complete pipeline.
All addresses are absolute guest addresses; the function range is half-open.

- `--simd asm|c`: native AArch64 assembly or portable C semantics.
- Repeat `--label N` for local targets and `--nle N` for landing pads/setjmp returns.
- Repeat `--table PC=TARGET,TARGET` or `--table PC=all` for resolved/fallback tables.
- `--hle SYMBOL` emits the HLE wrapper instead of an instruction body.
- `--json` returns the generated C and sorted external function references.
- `--out PATH` publishes atomically and preserves timestamps for identical output.

The C emitter handles function entry, direct/indirect calls, local/external tail
jumps, all-label table fallback, EH entry/re-entry/pop and HLE symbol sanitization.
AArch64 inline-assembly batches preserve reference output, including instruction
remapping, constant operands, flags and clobber order. Batches split at labels,
control flow, 24 instructions or scratch-register exhaustion. Reserved SIMD
literal encodings are rejected with a trap instead of the Python decoder's
uncaught KeyError; scratch exhaustion is bounded even for constant-only batches.
Malformed ranges, missing local labels and invalid table descriptions fail before
publishing any partial function. Unallocated instructions retain the frozen
reference's trap output.

Tests compare complete function text and reference sets against the unchanged
frozen `EhModule.emit_function`, including EH and assembly-batch boundaries.
A compiled execution probe checks scalar arithmetic/branches, a real longjmp into
a generated EH landing pad and frame cleanup; on AArch64 it also executes a
vector addition through the emitted inline assembly. A local comparison of 19
selected real Vanilla/Lumi functions (including subsdk1) matched byte for byte;
this is a checkpoint comparison, not full-game validation.

Remaining work includes ordered Unicorn scanning,
whole-module chunk/registration emission, worker contexts and production wiring.

## Frozen-reference comparison

The reference is Git revision `a26bc12e4188fb69d6cd96f3271a07bfc9e475ab`.
It must exist locally; the harness does not fetch or silently change it.
The reference requires the existing Python generator dependencies. A verified
private installer Python can be used with `BDSP_INSTALLER_PRIVATE_RUNTIME=1`.

```sh
python3 scripts/recomp/native-generator/compare.py \
  --exefs work/exefs --out work/native-generator/images-check \
  --native work/native-generator/bdsp_codegen
python3 scripts/recomp/native-generator/compare.py \
  --exefs work/exefs --out work/native-generator/analysis-check \
  --native work/native-generator/bdsp_codegen --stage analysis
```

`--layout macos|compact|compact-a` selects the existing desktop/compact/iPad
address layouts. `subsdk1` and per-module `.entries` are included when present.
Comparison directories must be new and outside the input tree. Images are
compared byte-for-byte by file inventory and SHA-256; analysis compares every
address and counter. Logs and reference snapshots remain under the chosen output.
`reference_analysis.py` cuts the frozen generator AST immediately before its
iterative scan, so the oracle executes the original initial-analysis algorithm.

Synthetic unit tests need no keys, game data, devices or running game:

```sh
python3 -m unittest scripts.tests.test_native_codegen
```

They use the existing development Python packages for reference comparisons.
For the sanitizer executable, set `BDSP_CODEGEN_TEST_BINARY` to its absolute path.

## CLI entry point

`bash scripts/recomp/codegen.sh gen ...` builds/caches the tool and forwards
arguments and exit status. `image ...` runs the native image builder. The former
owned `eh_gen.py`, `eh_parallel.py` and `mkimg.py` implementations are removed;
comparison tests obtain them only from the frozen Git revision. Vendored upstream
Python remains for development analysis/probes, outside the productive build path.

## Complete generation

```sh
work/native-generator/bdsp_codegen gen main work/exefs/main 0x7000000000 \
  work/native-generator/generated/main --simd asm --jobs auto
```

`--simd c` emits the portable SIMD/FP helpers used on x86_64. Other options match
the former generator: `--entry-offsets`, repeatable `--setjmp-at`, `--hle`,
`--only`, `--limit`, `--chunk`, `--chunk-bytes`, `--big-fn` and `--window`.
`--jobs N` or `BDSP_GEN_JOBS=N` overrides automatic CPU/affinity/quota and memory
selection. Classification, independent large scans and C emission use a bounded
ordered pthread/Win32 pool. Unicorn runs on the coordinator in the original order:
its register/memory state affects later table probes and cannot be reordered.
Workers propagate errors to the coordinator, which joins all workers before
reporting the failing phase and module. Output ordering is independent of jobs.
Identical files retain their timestamps. Only this module's obsolete generated
chunk filenames are pruned; symlinks are unlinked without following their target.

For full local output parity, use a new ignored comparison directory:

```sh
python3 scripts/recomp/native-generator/compare.py --stage generate \
  --exefs work/exefs --out work/native-generator/full-generation-check \
  --native work/native-generator/bdsp_codegen --simd c --jobs auto
```

`--layout compact-a` also verifies already-staged Lumi modules and `.entries`
without modifying inputs. Every C filename and SHA-256 is recorded alongside
separate native/reference timings. This check needs development oracle packages;
the native executable does not execute Python. The frozen reference is extracted
from Git commit `a26bc12e4188fb69d6cd96f3271a07bfc9e475ab`.

The Rust/Iced UI, IPS helper, runtime and saves are unaffected by the generator.
See `NOTICE.md` for source attribution and `vendor/lz4/LICENSE` for LZ4.

## Validated checkpoints (2026-10-25)

- macOS ARM64: unit tests, AddressSanitizer/UBSan and Clang static analysis.
- Complete vanilla module images: byte-identical in desktop and compact-A layouts.
- Already-staged Lumi modules including `subsdk1`: byte-identical compact-A images;
  every initial boundary, landing pad and setjmp address matches the frozen oracle.
- Linux x86_64 (Nobara): native Clang and GCC builds; synthetic compressed/plain
  images and EH analysis match the Mac results, including Unicode/spaced paths.
- Linux ARM64 (archimedesseal): native GCC and Clang 22.1.8 builds, synthetic
  image/EH parity, function C-output and assembly-IR goldens pass. The Clang-built
  execution probe also passes scalar branches, EH/longjmp/frame cleanup and native
  AArch64 vector addition. No game data was transferred.
- Linux x86_64 additionally passes the Clang-built scalar/EH execution probe;
  macOS ARM64 also executes the generated SIMD addition successfully.
- CI matrix tests prepared after private-runtime assembly; no CI run dispatched.

- Complete vanilla generation in native ARM64 and portable SIMD modes: every
  chunk and registration table matches the frozen reference.
- Complete staged Lumi generation in compact-A layout, including `subsdk1` and
  `.entries`: every generated C file matches the frozen reference.
- Linux ARM64 additionally passes native Unicorn scan/whole-module output parity
  at 1, 3 and automatic workers, plus worker ordering/error-cleanup probes.

These generator results do not establish Windows support or a complete Linux
ARM64 game run. Full application build acceptance is recorded separately.
