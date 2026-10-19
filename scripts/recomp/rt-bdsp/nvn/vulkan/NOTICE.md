# NOTICE: Vulkan-Fassung der NVN-Schicht (`nvn/vulkan/`)

Wie die Metal-Fassung (siehe `../../NOTICE.md`, Abschnitt „NVN-Schicht“) **übernimmt** die Vulkan-Fassung Quelltext des Klons LASRecomp mit ausdrücklicher Freigabe des Nutzers, unter dessen MIT-Lizenz (Copyright (c) 2026 Peiikai, Lizenztext in [`../upstream/LICENSE`](../upstream/LICENSE)).

| | |
|---|---|
| Projekt | LASRecomp, https://github.com/peiikai/LASRecomp |
| Stand | Commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5` |
| Übernommen (unverändert in `../upstream/nvn/vulkan/`) | `device.c`, `exec.c`, `shaders.c`, `shaders.h`, `textures.c`, `vk.h`, `vma.cpp`; `prepare_vk.sh` kopiert sie nach `work/recomp/nvn-src-vk` und wendet `las-vk.patch` an. Der gemeinsame Teil (`objects.c`, `cmdbuf.c`, `formats.c`, `tegra.c`, `astc.c`, Übersetzer) kommt wie beim Metal-Weg aus `../prepare.sh`. |
| Nicht übernommen | `imgui_glue.cpp`, `texpatch.c`, `output_scale.c`, `smaa_data.c`, alle `runtime/hle/*` (Spiel-Hooks), `ui/`, Randomizer, `third_party/` |
| Eigen | `prepare_vk.sh`, `build_vk.sh`, `vk_glue.c`, `shim/*`, `las-vk.patch` (Änderungen: trennbare Programme, bindlose Texturen und getrennte Sampler, Offscreen-Betrieb `--headless`, Pfade unter `work/recomp/`, Entfernung der Zelda-Hooks) |

**Drittkomponenten, die nur zur Bauzeit gebraucht werden und nicht im Repo liegen** (`scripts/recomp/ryzen/vk_sync_deps.sh` überträgt nur Header auf den Linux-Rechner; kein Quelltext davon im Repo):

| Komponente | Lizenz | Verwendung |
|---|---|---|
| Vulkan-Headers (Khronos) | Apache-2.0 / MIT | `vulkan/*.h` |
| VulkanMemoryAllocator (AMD, `vk_mem_alloc.h`) | MIT | Speicherverwaltung der Vulkan-Fassung (`vma.cpp`) |
| SDL3 | zlib | Fenster, PNG-Ausgabe (Laufzeitbibliothek `libSDL3.so.0`) |
| shaderc (Google) | Apache-2.0 | GLSL → SPIR-V zur Laufzeit (`libshaderc_shared.so.1`, nur die C-Schnittstelle `shaderc.h` als Header) |
| Vulkan-Loader | Apache-2.0 | `libvulkan.so.1` (Systembibliothek) |

Die Lizenz des Originals nimmt Nintendo-Eigentum und die Drittkomponenten aus; davon ist nichts enthalten.
