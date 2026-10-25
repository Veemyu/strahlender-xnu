# Native BDSP generator

C17 replacement for the Python generator and module-image builder, introduced in
independently checked stages. **This milestone implements images and the initial
analysis checkpoint. It does not implement `gen` or replace the production Python
C emitter yet.** No game bytes or generated game output belong in this directory.

## Build

```sh
python3 scripts/recomp/native-generator/build.py
work/native-generator/bdsp_codegen --version --json
```

A C17 compiler is required (`clang`, or `--cc gcc`). The small Python build helper
only invokes the compiler and verifies/caches the result; the resulting executable
has no Python dependency. It builds without CMake, pip, pkg-config or network access.
Vendored LZ4 1.9.4 is checked against `vendor/lz4/source.json` before compiling.
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

## Migration gates

1. Frozen reference, NSO loader and image parity — implemented.
2. Initial EH/entry discovery — implemented.
3. Full instruction classification/lifting, analysis fixpoint and ordered
   Unicorn jump-table behavior — pending.
4. Exact C emission, inline ARM64 ASM and portable SIMD-C, chunking, EH frame
   insertion and partial-build stubs — pending.
5. Native worker pool, GUI/CLI integration, stage hashes and source-matched
   packaging — pending.
6. Complete platform/mod acceptance; remove replaced Python implementations and
   their unused bindings; regenerate shipped SBOMs — pending.

The existing Rust/Iced UI, native IPS helper, game runtime and saves are unaffected.
See `NOTICE.md` for source attribution and `vendor/lz4/LICENSE` for the LZ4 license.

## Validated checkpoints (2026-10-25)

- macOS ARM64: unit tests, AddressSanitizer/UBSan and Clang static analysis.
- Complete vanilla module images: byte-identical in desktop and compact-A layouts.
- Already-staged Lumi modules including `subsdk1`: byte-identical compact-A images;
  every initial boundary, landing pad and setjmp address matches the frozen oracle.
- Linux x86_64 (Nobara): native Clang and GCC builds; synthetic compressed/plain
  images and EH analysis match the Mac results, including Unicode/spaced paths.
- Linux ARM64: host reachable; direct test awaits the user-installed C compiler.
- CI matrix tests prepared after private-runtime assembly; no CI run dispatched.

These results do not establish full native C generation, a new complete game build,
Windows support, or a native Linux ARM64 run.
