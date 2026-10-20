# Rendering fidelity: the 1:1 goal (2026-10-18)

Historical Unity-rebuild design note. That rebuild is deprecated; its pipeline and audio-safety decisions below are not current native-runtime instructions.

**User requirement:** Shaders and effects must look **exactly like the original**. Approximations are insufficient.

## Measured original settings (read-only inspection of `globalgamemanagers`)

| Setting | Original value |
|---|---|
| Render pipeline | **Built-in** (empty `m_CustomRenderPipeline`, no SRP) |
| Color space | **Gamma** (`m_ActiveColorSpace` = 0) |
| Quality levels | Exactly one (“Ultra”): shadows enabled (level 2), shadow distance 20, **no MSAA**, VSync count 2 (every second frame: 30 FPS on Switch) |
| Light intensity | Not linear; no color temperature |
| GPU skinning | Enabled |
| Default window | 1024 × 768 (default only, not Switch resolution) |

## Pipeline implications

- Fidelity requires the **Built-in pipeline**, not URP. Original shaders and lighting assume Unity Built-in conventions for constant buffers, lighting, fog, and shadows. URP would change lighting and shadows.
- Match the original **Gamma color space**, without MSAA or an HDR display.
- Unverified risk: Unity has announced eventual retirement of the Built-in pipeline in later versions. Pin Unity 6.3 LTS and check its support period.

## What “1:1” means for shaders

- The `Dpr/shaders` (63 shaders) and `Effects/fxparticle` (one shader) bundles contain only Switch binaries (platform 19) and parsed ShaderLab data: properties, passes, render states, and tags. Source text is unavailable (`shader-audio-machbarkeit.md`).
- The **Ryujinx cache** contains the same programs as SPIR-V (5,937 modules, 2,971 entries). It is the most precise available behavioral description because Ryujinx generated it from the Switch binaries. `spirv-cross` translates all 5,932 graphics modules to MSL.
- Goal: a **faithful port** of each shader, taking properties, passes, and render states from parsed data and program logic from SPIR-V; no invented look-alikes.
- **Differential verification:** Run identical inputs (vertex data, constant buffers, textures) through the reference program (SPIR-V → MSL in a small Metal harness) and the ported Unity shader, then compare pixels. Also use Ryujinx reference images if supplied by the user.
- Open question: How should Switch shader constant-buffer layouts map to Unity 6? They follow Unity 2019.4; we must supply per-material and per-frame values ourselves. This is the largest task and has not been investigated.

## Effects

Particles (`fxparticle` bundle, `Effects/*`), Timeline sequences, and post-processing (bloom and depth of field) must match visually and temporally. Use differential checks here too: fixed times, fixed camera, and image comparison.

## User audio requirement at the time

All devices were **silent at 0% volume**. Never change device volume or produce sound. As a safeguard, the app was **muted by default** (`AudioSafety`, Editor mute), enabled only by the `XNU_ALLOW_AUDIO` compile symbol. This historical restriction was superseded for the native audio work; see `recomp-audio.md`.
