//! Shared window dimensions; only the log is allowed to extend the height.
pub const WIDTH: f32 = 440.0;
pub const HEIGHT: f32 = 480.0;
pub const LOG_HEIGHT: f32 = 630.0;

// Keep the compact Mac window inside NSScreen.visibleFrame (menu bar and Dock excluded).
#[cfg(target_os = "macos")]
pub fn fit(window: &dyn iced::window::Window, content: iced::Size) {
    use iced::window::raw_window_handle::RawWindowHandle;
    use objc2::MainThreadMarker;
    use objc2_app_kit::NSView;
    let Some(_) = MainThreadMarker::new() else {
        return;
    };
    let Ok(handle) = window.window_handle() else {
        return;
    };
    let RawWindowHandle::AppKit(handle) = handle.as_raw() else {
        return;
    };
    // SAFETY: window::run executes on the main thread; this live view is only borrowed here.
    let view = unsafe { handle.ns_view.cast::<NSView>().as_ref() };
    let Some(window) = view.window() else { return };
    let Some(screen) = window.screen() else {
        return;
    };
    let visible = screen.visibleFrame();
    let mut frame = window.frame();
    let old_top = frame.origin.y + frame.size.height;
    let decoration = (frame.size.height - view.bounds().size.height).max(0.0);
    let margin = 16.0;
    frame.size.width = (content.width as f64).min((visible.size.width - margin * 2.0).max(1.0));
    frame.size.height =
        (content.height as f64 + decoration).min((visible.size.height * 0.85).max(1.0));
    frame.origin.x = frame.origin.x.clamp(
        visible.origin.x + margin,
        (visible.origin.x + visible.size.width - frame.size.width - margin)
            .max(visible.origin.x + margin),
    );
    frame.origin.y = (old_top - frame.size.height).clamp(
        visible.origin.y + margin,
        (visible.origin.y + visible.size.height - frame.size.height - margin)
            .max(visible.origin.y + margin),
    );
    window.setFrame_display(frame, true);
}
