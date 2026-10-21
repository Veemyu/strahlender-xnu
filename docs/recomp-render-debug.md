# Debugging the Metal renderer on macOS

How rendering errors in the native macOS build are found, with the tools that exist for it, and what was found with them.
Status: 2026-10-21.

## Finding: compute work group size read too late

**Symptom.** Vertex explosions (giant stretched triangles) on skinned objects such as the computer terminal in the Pokémon
Center, a missing or shredded cap on the player, shadow errors in the nurse room. Intermittent: about every second run
showed it, and it changed with how the scene was entered.

**Cause.** `compute_program` read the work group size of a compute shader at its first dispatch from the game's control
block (`control + 0x748`). The game owns that block and may reuse it once `nvnProgramSetShaders` has returned. The log
showed a different size for the same program in nearly every run, mostly garbage (`1x1x1`, `4294967295x1x1`, float bit
patterns) and `64x1x1` only when the block happened to be intact. With a size of 1 the skinning program computes only a
fraction of the vertices, and the draws read the rest unwritten.

**Fix.** `nvnProgramSetShaders` copies the three values into `NvnShaderStage.local_size`; the renderer uses the copy.
After the fix all four compute programs report `64x1x1` in every run, and no run showed the errors (3 runs entering the
Center from outside, 2 runs spawning inside it; no long soak yet).

**Related fixes made on the way.**
- A draw copies its vertex streams from guest memory when it is encoded, but a compute dispatch writes such buffers on the
  GPU. A stream that overlaps a range a still-pending dispatch writes is now preceded by a flush (`hz_ranges`,
  `streams_hit_pending_compute`). Cost: a few extra flushes per frame. Whether this is needed on top of the first fix is not
  established; it removes a real ordering hazard (60 overlaps with identical address and size were measured).
- `TexBackend` remembers the guest descriptor (target, size, format, samples) its Metal texture was created from and is
  recreated when it changes. This removed 29 of 30 "type mismatch" fallbacks (a 256x256 2D texture served as 1D).

**Ruled out by measurement** (so nobody has to repeat it): a 16-byte fallback for vertex streams of size 0, index values
beyond the bound stream, NaN in the first floats of the vertex uniform buffers, the guest rewriting storage buffers after
they were encoded, missed texture updates in the cheap change check, stale shader caches (prebuilt libraries, pipelines.bin).

## Method that worked

1. Reproduce deterministically: one instance, scripted input, a fixed save, no keys pressed in the window.
2. Measure at the draw level instead of comparing screenshots: the geometry check below shows which vertex shader
   produces which broken vertices; per-program logs of the compute dispatches showed the bad work group size.
3. Compare runs: the same value differing between runs (here the work group size) points at a read of memory the
   renderer does not own.

## Tools (`nvn/src/nvn/render_debug.inc`, all off unless the variable is set)

| Variable | Effect |
|---|---|
| `BDSP_GEOM_CHECK=1` `BDSP_GEOM_FROM=<f>` `[BDSP_GEOM_TO=<f>]` `[BDSP_GEOM_EVERY=<n>]` `[BDSP_GEOM_WARM=<n>]` `[BDSP_GEOM_LIMIT=<x>]` | Geometry check: vertex shaders also store their clip positions (translator key `dbg_pos`); every n-th frame in the window is scanned draw by draw and vertices with NaN/Inf, w near 0 or \|x/w\|, \|y/w\| above the limit are logged with shaders, attribute formats and the raw input of the first broken vertex. Flushes per draw: short windows only. Programs compile asynchronously and a draw is skipped until its program is ready, hence the warm-up frames. |
| `BDSP_SKIP_VS=<vs hex>[:<count>][,...]` | Hide the draws of a vertex shader (and index/vertex count) to find out what a draw paints. |
| `BDSP_SAVE_CS_DIR=<absolute dir>` | Write the translated MSL of every compute program. |
| `BDSP_DEBUG_FRAME=<f>` | Existing: detailed draw log of one frame; also accepted as `BDSP_GEOM_FROM`. |

Hang diagnostics (runtime, not rendering). None of these does anything in a normal session:

| Switch | Effect |
|---|---|
| `BDSP_HANG_DUMP=1` | The end-of-run report also prints the host state of every guest thread and briefly suspends busy ones to read their registers. |
| `BDSP_VSYNC_LOG=1` | Counts vsync events and logs the count every 120 ticks (is the clock alive when the guest stalls?). Without it nothing is counted. |
| `-DBDSP_DEBUG_MOVIE` at build time, then `BDSP_MOVIE_LOG=1` or `=ring` | Movie decoder/extractor entry and exit tracing; `ring` keeps the last entries in memory and dumps them shortly before the run's timeout. The code is not compiled into a standard build. |

Apple's tools: `MTL_DEBUG_LAYER=1 MTL_SHADER_VALIDATION=1` run the app with Metal API and shader validation (it found the
1D render target that was bound once at start-up). `gpudebug` and `gpucapture` are documented in the macOS 27 SDK but their
executables are not part of Xcode 27.1 on macOS 26.6.

## Practical notes

- The save has two files with different positions (`SaveData.bin`, `Backup.bin`), so the start location can alternate. Use a
  copy through `BDSP_SAVE=<dir>` for tests instead of the real save.
- The game reads input only after about 5 s; the intro video opens at about 7 s.
- Keys pressed in the app window reach the game while a scripted input runs.
- A rare boot hang or early crash (guest threads spinning, signal 11 within seconds) exists independently of these changes.
