# Private Python runtime (development)

## Release profile update

Full macOS and Linux release preparation now uses `--profile shaders`, with
`shader-wheels.lock.json` covering all transitive packages. `tpk_ar` and Linux
ARM64 UnityPy are built from locked sources; their native build records and wheel
hashes accompany the assembled runtime. The full runtime passed native checks on
macOS ARM64 and headless Fedora ARM64. See [release preparation](../docs/releases.md)
for the current pipeline and outstanding acceptance work. Historical probe notes
below describe the earlier base-only stage.

`manifest.json` pins standard CPython 3.13.15 from the [python-build-standalone
20260901 release](https://github.com/astral-sh/python-build-standalone/releases/tag/20260901).
Each of the six host archives has a recorded SHA-256. `wheels.lock.json` pins
the four base packages and the exact wheel bytes for the five hosts where
PyPI currently provides the required wheels: macOS x86_64/aarch64, Linux
x86_64/aarch64, and Windows x86_64. All downloads happen during development or
release preparation. The assembled runtime installs from verified local wheels;
running the installer does not invoke pip or change system Python.

The macOS aarch64 and Linux aarch64 base runtimes have now been executed. The
Linux test ran on headless Fedora Asahi Remix 44, using private CPython and
actual LZ4, Capstone, Unicorn and Pillow operations. macOS also ran the JSONL
preflight with Python's isolated `-I` mode. Other archives still need native
execution and packaging tests. `wheels.lock.json` intentionally has no
Windows aarch64 entry: [Capstone](https://pypi.org/project/capstone/5.0.9/) and
[Unicorn](https://pypi.org/project/unicorn/2.1.4/) lack `win_arm64` wheels at
these versions. A native build or another verified packaging route is needed.

The shader profile is separate. [UnityPy 1.25.4](https://pypi.org/project/UnityPy/1.25.4/)
has no published Linux aarch64 wheel. Its `tpk_ar` dependency is published as
source. On Fedora ARM64 both were built from pinned source; UnityPy was repaired
to a manylinux wheel in a rootless build container, all 15 shader-profile wheels
resolved, and UnityPyBoost loaded under private CPython. Shader functions on
real bundle data, a committed transitive wheel lock, other hosts and licensing
review are still pending. Do not ship this as a completed shader runtime yet.

The four base packages already execute native code: Capstone and Unicorn ship
C engines with Python bindings; LZ4 and Pillow ship compiled extensions.
UnityPy includes the C++ `UnityPyBoost` extension, while `tpk_ar` is pure
Python. Replacing their Python APIs would require a separate generator port;
the packaging work here preserves the existing calls and compiles missing
native wheels on their target hosts. `source-lock.json` pins the four source
archives by SHA-256. `native_smoke.py` executes AArch64 disassembly and
emulation, LZ4 round-trip and Pillow pixel operations, so a mere successful
import is insufficient to pass assembly.

Source wheels can be built with `installer/scripts/build_source_wheel.py` after
downloading the named archives from PyPI. For example:

```sh
python3 -B installer/scripts/build_source_wheel.py tpk_ar \
  --source-archive work/installer-runtime-probe/native-audit/tpk_ar-0.2.4.tar.gz \
  --output work/installer-runtime-probe/source-builds/tpk_ar
python3 -B installer/scripts/probe_runtime.py --target macos-aarch64 \
  --profile shaders --resolve \
  --find-links work/installer-runtime-probe/source-builds/tpk_ar
```

On a native Windows ARM64 Python, the source builder precompiles Capstone and
Unicorn with Visual Studio 2022/CMake for ARM64 before building wheels; this
avoids their older `setup.py` defaults that select x64. This Windows path still
needs a native host test. Linux aarch64 UnityPy and `tpk_ar` builds passed on
Fedora ARM64; the universal `tpk_ar` wheel and source-built UnityPy, Capstone
and Unicorn wheels were also built on macOS aarch64. Record resulting wheel
hashes and run the native smoke checks on each host before adding a wheel to
the release lock.
Linux wheels built directly on a host need a portable manylinux tag and library
audit before distribution; a `linux_aarch64` wheel alone is a local build.
The macOS source-built Unicorn wheel was tagged for this Mac's OS version, so
the release continues to use the older-compatible locked wheel. Before shipping
the native libraries, review the upstream redistribution terms, especially
[Unicorn's GPLv2 terms](https://github.com/unicorn-engine/unicorn/blob/master/bindings/python/README.md)
and UnityPy's FMOD-related dependencies.

To repeat the read-only wheel probes, from the repository root:

```sh
python3 -B installer/scripts/probe_runtime.py --profile base --output work/installer-runtime-probe/base-matrix.json
python3 -B installer/scripts/probe_runtime.py --profile shaders --resolve --output work/installer-runtime-probe/shaders-matrix.json
```

To assemble the native host's base runtime, download its named Python archive
from the pinned release, then run:

```sh
python3 -B installer/scripts/assemble_runtime.py \
  --python-archive work/installer-runtime-probe/cpython-macos-aarch64.tar.gz \
  --fetch-wheels \
  --output work/installer-runtime-probe/private-macos-aarch64
BDSP_INSTALLER_RUNTIME="$PWD/work/installer-runtime-probe/private-macos-aarch64" \
  cargo run --locked --manifest-path installer/Cargo.toml
```

The assembler verifies the archive and every locked wheel before extraction
and installs only from those local wheels. `--wheelhouse DIRECTORY` can replace
`--fetch-wheels` for an offline assembly. It refuses to overwrite an existing
runtime and only assembles for the current host architecture. The GUI also
looks under its per-user data directory at `runtimes/3.13.15/<host-target>`.
Development builds can still use local `python3` when no private runtime is
selected. Release builds require the verified private runtime. Download and
installation into the per-user directory are future work; no release pipeline
is enabled yet.

### Native Linux ARM64 check

This path passed on headless Fedora Asahi Remix 44 via `archimedesseal`. Use a
checkout of this repository and a local work directory (ignored by Git). That
host has no system pip, so the hash-checked CPython archive also bootstraps the
assembler. The assembler checks the same hash again and runs `native_smoke.py`.

```sh
mkdir -p work/installer-runtime-probe
curl -fL --retry 3 \
  'https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.13.15+20260901-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz' \
  -o work/installer-runtime-probe/cpython-linux-aarch64.tar.gz
printf '%s  %s\n' \
  '01ce0ce9189feaead3298abf10d4efe998c55a489b3d5d38ca4f83dda7e7977e' \
  'work/installer-runtime-probe/cpython-linux-aarch64.tar.gz' | sha256sum -c -
mkdir -p work/installer-runtime-probe/bootstrap
tar -xzf work/installer-runtime-probe/cpython-linux-aarch64.tar.gz \
  -C work/installer-runtime-probe/bootstrap
work/installer-runtime-probe/bootstrap/python/bin/python3 -B \
  installer/scripts/assemble_runtime.py \
  --target linux-aarch64 \
  --python-archive work/installer-runtime-probe/cpython-linux-aarch64.tar.gz \
  --fetch-wheels \
  --output work/installer-runtime-probe/private-linux-aarch64
```

The server has no host compiler. A pinned ARM64 manylinux container supplies
GCC and `auditwheel` without changing Fedora's system packages. The builder
verifies both source hashes. Run it with the container's CPython 3.13 so the
wheel ABI and compiler settings are correct. Do not pass `-I` to the builder
script: it must import its adjacent `probe_runtime.py` module.

```sh
work/installer-runtime-probe/private-linux-aarch64/python/bin/python3 -I -B -m pip download \
  --no-binary=:all: --no-deps --dest work/installer-runtime-probe/sources \
  UnityPy==1.25.4 tpk_ar==0.2.4
work/installer-runtime-probe/private-linux-aarch64/python/bin/python3 -B \
  installer/scripts/build_source_wheel.py tpk_ar \
  --source-archive work/installer-runtime-probe/sources/tpk_ar-0.2.4.tar.gz \
  --output work/installer-runtime-probe/source-wheels
podman run --rm --userns keep-id -v "$PWD:/workspace:Z" -w /workspace \
  quay.io/pypa/manylinux_2_28_aarch64@sha256:270a5e59af09f02dfc07fe4bb2cb2c5625c76d085cfa47f87dd93d9026eacc75 \
  /opt/python/cp313-cp313/bin/python -B installer/scripts/build_source_wheel.py UnityPy \
  --source-archive work/installer-runtime-probe/sources/unitypy-1.25.4.tar.gz \
  --output work/installer-runtime-probe/source-wheels
podman run --rm --userns keep-id -v "$PWD:/workspace:Z" -w /workspace \
  quay.io/pypa/manylinux_2_28_aarch64@sha256:270a5e59af09f02dfc07fe4bb2cb2c5625c76d085cfa47f87dd93d9026eacc75 \
  auditwheel repair --plat manylinux_2_28_aarch64 \
  -w work/installer-runtime-probe/repaired-wheels \
  work/installer-runtime-probe/source-wheels/unitypy-1.25.4-cp313-cp313-linux_aarch64.whl
cp work/installer-runtime-probe/source-wheels/tpk_ar-0.2.4-py3-none-any.whl \
  work/installer-runtime-probe/repaired-wheels/
work/installer-runtime-probe/private-linux-aarch64/python/bin/python3 -B \
  installer/scripts/probe_runtime.py --target linux-aarch64 \
  --profile shaders --resolve \
  --find-links work/installer-runtime-probe/repaired-wheels \
  --output work/installer-runtime-probe/linux-aarch64-shaders.json
```

The repaired UnityPy wheel has SHA-256
`a79c264168a3ee4f7538cf9d8178ff9145a3e37b8941fa0fb88c150da3f6e4a5`;
the `tpk_ar` wheel has
`ed079739ae6074fe4647bdc7147d99ff9d39b2d3370b22b5d6370f383d08a937`.
The shader probe found 15 wheels. They were installed into a separate copy of
the private runtime and `UnityPy`, `UnityPyBoost`, `tpk_ar`, `texture2ddecoder`
and `etcpak` imported successfully on Fedora. The probe report and built wheels
are retained under `work/installer-runtime-probe/linux-aarch64-fedora44/` in
the development checkout. Shader parsing of real bundles and a committed lock
for all transitive wheels remain open.

When `BDSP_INSTALLER_PRIVATE_RUNTIME=1`, generator and shader scripts skip
`tools/pydeps`: compiled extensions there may belong to another Python ABI.
The GUI prepends only its child process's private Python directory to `PATH`.
This was verified by loading the generator with CPython 3.13 while the local
`tools/pydeps` contained Python 3.14 extensions. A complete production
generator run is still outstanding. A bounded profile of local function
discovery took 2.30 seconds under cProfile, with 1.88 seconds in its Python
`discover` routine; the larger generator sample reached the Python lifter but
was stopped due to its memory and run time. That evidence does not justify
replacing the generator's semantics with a new native implementation yet.
