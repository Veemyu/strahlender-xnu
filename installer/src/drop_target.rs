//! Hit-test actual widget bounds rather than hard-coded window coordinates.
//! macOS winit 0.30 sends file events without updating the Iced cursor during
//! external drags. Query the existing content view; no native UI is constructed.
use crate::sources::Slot;
#[cfg(any(target_os = "macos", test))]
use iced::advanced::widget::{
    Id, Operation,
    operation::{Outcome, Scrollable},
};
#[cfg(any(target_os = "macos", test))]
use iced::{Point, Rectangle, Vector};

pub fn id(slot: Slot) -> &'static str {
    match slot {
        Slot::Base => "drop-base",
        Slot::Update => "drop-update",
        Slot::Keys => "drop-keys",
    }
}

#[cfg(any(target_os = "macos", test))]
pub struct HitTest {
    point: Point,
    translation: Vector,
    slot: Option<Slot>,
}

#[cfg(any(target_os = "macos", test))]
impl HitTest {
    pub fn new(point: Point) -> Self {
        Self {
            point,
            translation: Vector::ZERO,
            slot: None,
        }
    }
}

#[cfg(any(target_os = "macos", test))]
impl Operation<Option<Slot>> for HitTest {
    fn traverse(&mut self, operate: &mut dyn FnMut(&mut dyn Operation<Option<Slot>>)) {
        operate(self);
    }
    fn scrollable(
        &mut self,
        _: Option<&Id>,
        _: Rectangle,
        _: Rectangle,
        translation: Vector,
        _: &mut dyn Scrollable,
    ) {
        // The app has one outer scrollable. Its content coordinates include
        // the scroll translation; convert the pointer into that same space.
        self.translation = translation;
    }
    fn container(&mut self, widget_id: Option<&Id>, bounds: Rectangle) {
        if bounds.contains(self.point + self.translation) {
            for slot in [Slot::Base, Slot::Update, Slot::Keys] {
                if widget_id == Some(&Id::new(id(slot))) {
                    self.slot = Some(slot);
                }
            }
        }
    }
    fn finish(&self) -> Outcome<Option<Slot>> {
        Outcome::Some(self.slot)
    }
}

#[cfg(target_os = "macos")]
pub fn pointer(window: &dyn iced::window::Window) -> Option<Point> {
    use iced::window::raw_window_handle::RawWindowHandle;
    use objc2::MainThreadMarker;
    use objc2_app_kit::NSView;
    let _main_thread = MainThreadMarker::new()?;
    let handle = window.window_handle().ok()?;
    let RawWindowHandle::AppKit(handle) = handle.as_raw() else {
        return None;
    };
    // SAFETY: Iced invokes window::run on the main event-loop thread. The
    // borrowed view belongs to its live window and is used only in this call.
    let view = unsafe { handle.ns_view.cast::<NSView>().as_ref() };
    let window = view.window()?;
    let point = view.convertPoint_fromView(window.mouseLocationOutsideOfEventStream(), None);
    let bounds = view.bounds();
    Some(Point::new(
        (point.x - bounds.origin.x) as f32,
        if view.isFlipped() {
            (point.y - bounds.origin.y) as f32
        } else {
            (bounds.size.height - (point.y - bounds.origin.y)) as f32
        },
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn routes_drops_by_bounds_including_scroll_offset() {
        let mut hit = HitTest::new(Point::new(400.0, 240.0));
        hit.translation = Vector::new(0.0, 80.0);
        hit.container(
            Some(&Id::new(id(Slot::Base))),
            Rectangle::new(Point::new(20.0, 300.0), iced::Size::new(300.0, 200.0)),
        );
        assert_eq!(hit.slot, None);
        hit.container(
            Some(&Id::new(id(Slot::Update))),
            Rectangle::new(Point::new(350.0, 300.0), iced::Size::new(300.0, 200.0)),
        );
        assert_eq!(hit.slot, Some(Slot::Update));
    }
}
