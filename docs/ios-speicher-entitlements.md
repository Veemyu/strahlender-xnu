# iPadOS: Memory Entitlements and Address Space (Research, 2026-10-18)

Purpose: decision support for `ap-ipad-perf` and `ap-recomp-feasibility`. Sources are linked, and confidence is stated for each finding. This is not legal advice or a measurement on our device.

## Findings
| Question | Finding | Confidence |
|---|---|---|
| **Extended Virtual Addressing** (`com.apple.developer.kernel.extended-virtual-addressing`) | Boolean entitlement for an expanded address space. Apple's example is games that stream assets to the GPU using memory mapping. Available starting with iOS, iPadOS, and tvOS 14.0; macOS is not listed. Xcode capability: “Extended Virtual Addressing.” | documented |
| EVA with a **free team** | Apple's “Supported capabilities (iOS)” table lists it only for the paid program (ADP) and Enterprise; the free-account column is empty. | documented (table reviewed) |
| Address-space size with/without EVA | Apple does not specify a number. | unverified |
| **Increased Memory Limit** (`com.apple.developer.kernel.increased-memory-limit`) | Allows exceeding the standard limit on supported devices, starting with iOS/iPadOS 15.0. The actual value comes from `os_proc_available_memory()`. | documented |
| Increased Memory Limit with a free team | Not listed in Apple's table. **Observed (user, 2026-10-18):** The capability can be added in Xcode with the free Personal Team; the app builds, is signed, and runs on the iPad Pro (M2, iPadOS 26.4.2). The reached memory value was measured: 8192 MiB instead of 5120 MiB without the entitlement (`docs/ipad-messung-1.md`). | observed and measured (contradicts the earlier assumption “rather unlikely”) |
| **Increased Debugging Memory Limit** | Development only, for ad hoc and internal TestFlight builds; remove before distribution. Listed only for ADP/Enterprise. | documented |
| Jetsam limit without entitlement | A user report cites about 5 GB on M1 iPads. **Measured on the iPad Pro M2 (8 GB): 5120 MiB** (`docs/ipad-messung-1.md`). | measured |
| Fixed multi-GB region (e.g. 12.5 GB at `0x70_0000_0000`) without EVA | No evidence that this works. A test on an iPhone 17 Pro reports that `mmap` fails without an entitlement with “Cannot allocate memory,” but works with EVA or Increased Memory Limit (single report). Older iOS versions allowed only a narrow region. | suspected; single report |
| macOS | A separate, more generous path seems plausible, but no Apple source was found. | unverified |

## Sources
- EVA: https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.kernel.extended-virtual-addressing
- Capability table: https://developer.apple.com/help/account/reference/supported-capabilities-ios/
- Increased Memory Limit: https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.kernel.increased-memory-limit
- Debugging limit: https://developer.apple.com/help/glossary/increased-debugging-memory-limit/
- `os_proc_available_memory`: https://developer.apple.com/documentation/os/os_proc_available_memory
- Practical mmap report: https://zenn.dev/mtfum/articles/ios_memory_entitlements?locale=en
- Historical address space (PPSSPP, 2017): http://blog.henrikrydgard.com/ios-address-space/
- Go issue about iOS address space: https://github.com/golang/go/issues/46860

## Implications for Us
1. According to Apple's table, EVA and the debugging limit are unavailable with a free team. **The user reports that Increased Memory Limit nevertheless works** (add it, sign, launch). The requirement in `goal.md` (“no high virtual memory requirements for iOS”) remains because of EVA.
2. A fixed 12.5 GB guest window such as LASRecomp's (`runtime/rt.h`) is not reliably possible on iPad. A recompilation would need pointer rebasing, smaller windows, or 32-bit offsets, plus a runtime memory budget.
3. The Unity path is less affected because Unity manages memory normally. The total budget (bundles, textures) still counts against the Jetsam limit.
4. Manage the runtime budget with `os_proc_available_memory()` and measure on the actual iPad Pro (M2). This is the only reliable figure.
5. **Measured (2026-10-19, `docs/ipad-messung-1.md`):** limit without entitlement 5120 MiB, with Increased Memory Limit 8192 MiB (`os_proc_available_memory() + phys_footprint`); the entitlement also works with the free team. The post-build step `unity/Assets/Scripts/Build/Editor/IosPostBuild.cs` adds it automatically to every Unity iOS build (on by default; can be disabled with symbol `XNU_NO_INCREASED_MEMORY`).
