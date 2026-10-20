# Documentation index

Documentation defaults to English. German text is allowed only in files ending
in `.de.md`. German source documents are retained under that suffix while their
standard `.md` counterparts are translated in full.

## Active native recompilation

| Topic | Guide |
|---|---|
| Build prerequisites, local configuration, platforms | [BUILD.md](BUILD.md) |
| macOS application, controls, saves, diagnostics | [recomp-macapp.md](recomp-macapp.md) |
| iPadOS build, deployment, memory, known issues | [recomp-ios.md](recomp-ios.md) |
| Audio output, threading, evidence, remaining checks | [recomp-audio.md](recomp-audio.md) |
| Original icon extraction, language variants, deterministic styling | [recomp-icons.md](recomp-icons.md) |

German versions use the corresponding `.de.md` suffix, including
[BUILD.de.md](BUILD.de.md).

## Historical references

Architecture: architektur-entscheidung.md and kernziel.md.
Recompilation progression: recomp-machbarkeit.md → recomp-spike-2.md →
recomp-gate1.md → recomp-gate2.md. Additional evidence: recomp-qa.md,
recomp-vulkan.md, recomp-linux.md, recomp-diff.md, recomp-referenzen.md.

Rendering investigations: shader-translator.md, shader-inventar.md,
shader-harness.md, shader-globals.md, wasser.md, ios-texturen.md,
video-umwandlung.md, render-treue.md.

Data and saves: extraktion.md, daten-inventar.md, save-format.md,
save-validator.md, save-kompatibilitaet.md, spielcode-inventar.md.
Historical filenames remain stable so existing links continue to work.

The Unity rebuild is deprecated and must not be modified for native work.
Older Unity specifications remain research references only.
The former German index is preserved in [README.de.md](README.de.md).
