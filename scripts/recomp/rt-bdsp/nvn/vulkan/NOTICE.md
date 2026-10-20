# NOTICE: Vulkan NVN layer

Like the Metal backend (see ../../NOTICE.md), this backend uses LASRecomp source
with the user's explicit approval, under its MIT license:
Copyright (c) 2026 Peiikai. The license text is in ../../../upstream/LICENSE.

Upstream: https://github.com/peiikai/LASRecomp
Reference commit: 09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5.

The adapted backend sources are device.c, exec.c, shaders.c/.h, textures.c,
vk.h, and vma.cpp under src/. prepare_vk.sh copies shared NVN and Vulkan sources
into ignored work/recomp/nvn-src-vk. Shared objects/command buffers/formats,
Tegra/ASTC handling, and translation originate from the same runtime.
Our integration provides separate programs, bindless texture/sampler handling,
headless output, work/ paths, and removal of unrelated game hooks.

No new copies of third-party library headers or binaries are vendored here.
The Linux build uses distribution development packages via pkg-config:
Vulkan headers/loader (Apache-2.0 or MIT, as applicable), VMA (MIT), SDL3 (zlib),
shaderc (Apache-2.0), Qt6 (its applicable Qt license), and FFmpeg (its applicable
build license). These components retain their own licenses. The user's original
game content is not included. Existing approved runtime source and its notices
remain intact.

See docs/BUILD.md section 6 and scripts/recomp/linux/deps.sh for the dependency
checks. The previous automatic VMA download and Homebrew-header copying scripts
have been removed; package installation is the user's responsibility.
