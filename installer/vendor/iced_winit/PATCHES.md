# Local patch to iced_winit 0.14.1

Upstream: https://github.com/iced-rs/iced/tree/0.14.0/winit
The starting sources are the published crates.io iced_winit 0.14.1 package.
`Cargo.toml.orig` and the nested `Cargo.lock` of that package are not kept: Cargo ignores the lock file of a path
dependency, and the original manifest is in the crates.io package.

`src/lib.rs`, `window::Action::Resize`: handle the physical size returned by
Winit's `request_inner_size`. `Some(size)` is a synchronous resize and Winit
does not guarantee another `Resized` event. Update the viewport and broadcast
the resize exactly as for a native resize event, then request a redraw.

Without this, KDE Wayland fractional scaling stretches the old framebuffer
when expanding the installer log instead of laying out the new content.
Remove this patch when an upstream release handles synchronous resize results.

For explicit macOS background launches, `BDSP_INSTALLER_BACKGROUND=1` disables
Winit's default activation that ignores other apps. This allows a bundled
installer launched through `open -g` to respect the active application. Normal
launches retain the upstream activation behavior.
