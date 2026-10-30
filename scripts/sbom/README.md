# SBOM (software bill of materials)

The CI generates the SBOM for every full run and attaches it to the release; nothing generated is checked in.

| File | Format |
|---|---|
| `strahlender-xnu.spdx.json` | SPDX 2.3, JSON (main format) |
| `strahlender-xnu.spdx` | SPDX 2.3, tag-value |
| `strahlender-xnu.cdx.json` | CycloneDX 1.6, JSON |
| `strahlender-xnu.csv` | flat inventory with evidence paths, for review |

- `installer-ci.yml`: job `sbom` on every run (artifact `sbom`); published with the installer releases (nightly and stable).
- `windows-buildenv.yml`: the same files travel with the `windows-buildenv` release.

Locally (standard library only, Python 3.11 or newer; `cargo fetch --locked` in `installer/` first, so licences resolve offline):

```sh
python3 scripts/sbom/generate_sbom.py --out sbom
python3 -m unittest scripts/tests/test_generate_sbom.py
```

## Scope

- **Rust crates** of the installer and of `installer/extract` (`bdsp-extract`), merged by purl: both `Cargo.lock` files, with SHA-256 checksums. Licences and
  dependency edges come from `cargo metadata --locked --offline`.
- **Python**: the pinned wheels of the installer runtime (`installer/runtime/wheels.lock.json`) and the local
  `tools/pydeps` environment (git-ignored).
- **Windows build environment** (CI only, `--windows-inputs`): Qt, LLVM-MinGW, SDL3, Vulkan, FFmpeg, hactool and the VC runtime with the versions and hashes the CI resolved that day (`windows-dependencies.json`, `windows-sources.json`, `qt.json`, published as assets of the `windows-buildenv` release). The installer SBOM job downloads them, so every release carries one document for all platforms.
- **Vendored source and assets**: LASRecomp (MIT), Octicons, Lucide, Fira Sans.
- **Pinned build inputs** named in `scripts/recomp/.../build_deps*.sh`, `fetch_zig.sh` and `installer/runtime/manifest.json`.
- **Local tools** in `tools/` (git-ignored): hactool and its bundled mbed TLS, cJSON and LZ4, Il2CppDumper, nx2elf, vgmstream.
- **System packages** named in `install.command`, `install-linux.sh` and `docs/BUILD.md`. The project does not pin
  their versions, so they are recorded as `unpinned`.

Each component has a `distribution` class (`shipped`, `build-tool`, `dev-test`, `user-installed`, `local-tool`,
`optional`) and a `repository_state` (`tracked`, `uncommitted`, `git-ignored`, `external`). The CSV and the
`bdsp:*` properties in the CycloneDX file carry both.

The catalogue of non-Cargo, non-wheel items lives in `CATALOG` in `scripts/sbom/generate_sbom.py`. Each entry names
the file that proves it, so a reviewer can check it against the repository.

## Validation

- SPDX JSON and tag-value: parsed with `spdx-tools` (`pyspdxtools`). An intentionally broken licence expression is rejected.
- CycloneDX: validated against the 1.6 schema with `cyclonedx-python-lib`.
- Every licence expression is checked with `license-expression` against the SPDX licence list. The two
  `LicenseRef-*` entries are defined in the document.

## Open findings

These are not errors in the SBOM. They are licence and consistency questions the SBOM exposes:

1. **Unicorn 2.1.4** (GPL-2.0-only) ships in the installer's private runtime. Its wheel metadata says "BSD License",
   its upstream metadata says GPLv2. Check this before a release.
2. **FFmpeg** is bundled into the macOS app by `scripts/recomp/app/bundle_dylibs.py`. `THIRD_PARTY_NOTICES.md` says FFmpeg
   is "not distributed here". That is true for the repository, not for the built app. `bundle_dylibs.py` copies whatever
   FFmpeg the binary links. With the documented setup (`brew install ffmpeg`) that is the Homebrew build (`brew-ffmpeg`),
   whose licence depends on its configure options. It is not the pinned LGPL source build.
3. **FMOD** (`fmod_toolkit`) contains a proprietary library. It is only in the shader profile, which is not yet shipped.
4. **Version drift**: SDL3 is pinned to 3.4.16 on Linux and 3.4.18 on macOS. CPython is 3.12.14 in the macOS generator
   script and 3.13.15 in the installer runtime.
5. **nx2elf** has no licence file. Its licence is unknown.
6. **option-ext 0.2.0** (MPL-2.0, file-level copyleft) is in the installer binary. Its notice is needed in the release.
7. **Fira Sans** (OFL-1.1) is embedded in the installer binary. The OFL notice must ship with it (`--licenses` already offers it).
8. `THIRD_PARTY_NOTICES.md` does not yet list the Rust crates, the installer runtime wheels or the Zig compiler shipped in the Windows release.
