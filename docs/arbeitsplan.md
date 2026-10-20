# Work Plan for strahlender-xnu

Goals: see `goal.md`. All assets come exclusively from personally owned XCI/NSP dumps.

## Directories
- `nsp/`, `Ryujinx/`: dumps, keys, saves (local, not in the repository)
- `work/`: extraction and analysis results (local, not in the repository)
- `tools/`: locally built tools (not in the repository)

## Phases
0. Hygiene: `.gitignore`, free up space
1. Install tools (without sudo)
2. Unpack XCI and update NSP, apply the update
3. Reverse engineering with Ghidra, load NSO, IL2CPP dump
4. Analyze assets and save format
5. Make an architecture decision (Unity LTS, native Metal runtime, opendpr as reference only)
6. MVP: 1080p 16:9, Metal, 60/120 FPS

## Rules
- Never commit keys, dumps, saves, or extracted assets.
- Do not reuse code from opendpr (that project prohibits generative AI).
