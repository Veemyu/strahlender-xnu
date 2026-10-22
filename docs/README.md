# Documentation index

Documentation is English; German exists only for the root README, this index and the build guide
([README.de.md](README.de.md), [BUILD.de.md](BUILD.de.md)).

## Goal

This repository and your own copy of Pokémon Brilliant Diamond (an XCI, optionally the update NSP, and your `prod.keys`) must be
enough to build the app for macOS, iPadOS and (in progress) Linux. The repository contains only original code, scripts and
documentation: no game data, keys, saves or generated code. Everything derived from the game is produced locally under `work/`, and
a built app is for personal use only. The game's own code runs, so logic, UI and saves behave like the original.

## Start here

| Topic | Document |
|---|---|
| Build and install (guided installers, stages, options, troubleshooting) | [BUILD.md](BUILD.md) |
| How the recompilation works (generator, exceptions, memory model, runtime, graphics) | [architecture.md](architecture.md) |
| Working rules, commands, tests, saves for testing, what lives in `work/` | [development.md](development.md) |

## Platforms and features

| Topic | Document |
|---|---|
| macOS app: controls, saves, diagnostics, measurements | [recomp-macapp.md](recomp-macapp.md) |
| iPadOS: build, deployment, memory model and entitlements, known issues | [recomp-ios.md](recomp-ios.md) |
| Linux: build host and Vulkan backend (work in progress) | [recomp-linux.md](recomp-linux.md) |
| Audio output | [recomp-audio.md](recomp-audio.md) |
| App icons | [recomp-icons.md](recomp-icons.md) |

## Rendering, shaders, saves, testing

| Topic | Document |
|---|---|
| Metal renderer: fidelity, debugging method, performance, frame rate, water | [rendering.md](rendering.md) |
| Shader translator and offscreen harness | [shaders.md](shaders.md) |
| Save format, validator, where saves live | [saves.md](saves.md) |
| QA harness and scenarios | [recomp-qa.md](recomp-qa.md) |
| Bit-exactness test of the generated C against ARM64 | [recomp-diff.md](recomp-diff.md) |
| Changes over time | [changelog.md](changelog.md) |

## Removed material

The Unity rebuild is deprecated and lives on the branch `unity`. Its documents, the early feasibility, spike and gate reports of the
recompilation (condensed into [architecture.md](architecture.md)), and the specifications for reimplementing game logic (battle,
Pokémon parameters, event scripts, master data, localization, input) were removed from `main`; they stay in the git history and on
that branch. Code comments and a few notes may still mention scripts or `work/` folders from that time.
