//! Locally bundled fallback SVGs plus native SF Symbols on macOS.
use iced::{Color, Element, widget::svg};

#[derive(Clone, Copy)]
pub enum Icon {
    Sun,
    Moon,
    Desktop,
    Laptop,
    Tablet,
    Phone,
    GenericPhone,
    Github,
    Copy,
    Check,
}

pub fn view<'a>(icon: Icon, size: f32, color: Color) -> Element<'a, crate::app::Message> {
    view_for_host(icon, size, color, crate::platform::Platform::native())
}

pub fn view_for_host<'a>(
    icon: Icon,
    size: f32,
    color: Color,
    host: crate::platform::Platform,
) -> Element<'a, crate::app::Message> {
    #[cfg(not(target_os = "macos"))]
    let _ = host;
    #[cfg(target_os = "macos")]
    if host == crate::platform::Platform::Mac {
        if let Some(image) = macos::view(icon, size, color) {
            return image;
        }
    }

    let bytes: &'static [u8] = match icon {
        Icon::Sun => include_bytes!("../assets/lucide/sun.svg"),
        Icon::Moon => include_bytes!("../assets/lucide/moon.svg"),
        Icon::Desktop => include_bytes!("../assets/lucide/monitor.svg"),
        Icon::Laptop => include_bytes!("../assets/lucide/laptop.svg"),
        Icon::Tablet => include_bytes!("../assets/lucide/tablet.svg"),
        Icon::Phone => include_bytes!("../assets/lucide/smartphone.svg"),
        Icon::GenericPhone => include_bytes!("../assets/lucide/smartphone.svg"),
        Icon::Github => include_bytes!("../assets/github.svg"),
        Icon::Copy => include_bytes!("../assets/ui/copy.svg"),
        Icon::Check => include_bytes!("../assets/ui/check.svg"),
    };
    let rotation = if matches!(icon, Icon::Tablet) {
        std::f32::consts::FRAC_PI_2
    } else {
        0.0
    };
    svg(svg::Handle::from_memory(bytes))
        .width(size)
        .height(size)
        .rotation(iced::Radians(rotation))
        .style(move |_, _| svg::Style { color: Some(color) })
        .into()
}

#[cfg(target_os = "macos")]
mod macos {
    use super::Icon;
    use iced::{Color, Element, widget::image};
    use objc2::MainThreadMarker;
    use objc2_app_kit::{
        NSColor, NSFontWeightRegular, NSImage, NSImageSymbolConfiguration, NSImageSymbolScale,
    };
    use objc2_foundation::{NSOperatingSystemVersion, NSProcessInfo, NSSize, NSString};
    use std::{
        collections::HashMap,
        sync::{Mutex, OnceLock},
    };

    type RenderedSymbol = (u32, u32, Vec<u8>);
    type SymbolCache = Mutex<HashMap<(&'static str, u32, [u32; 4]), RenderedSymbol>>;

    pub fn view<'a>(
        icon: Icon,
        size: f32,
        color: Color,
    ) -> Option<Element<'a, crate::app::Message>> {
        let symbol = match icon {
            Icon::Laptop => "macbook",
            Icon::Tablet => "ipad.landscape",
            Icon::Phone => "iphone",
            _ => return None,
        };
        render(symbol, size, color).map(|(width, height, rgba)| {
            image(image::Handle::from_rgba(width, height, rgba))
                .width(size)
                .height(size)
                .into()
        })
    }

    fn render(symbol: &str, size: f32, color: Color) -> Option<(u32, u32, Vec<u8>)> {
        static CACHE: OnceLock<SymbolCache> = OnceLock::new();
        let name = match symbol {
            "macbook" => "macbook",
            "ipad.landscape" => "ipad.landscape",
            _ => "iphone",
        };
        let key = (
            name,
            size.to_bits(),
            [
                color.r.to_bits(),
                color.g.to_bits(),
                color.b.to_bits(),
                color.a.to_bits(),
            ],
        );
        let cache = CACHE.get_or_init(|| Mutex::new(HashMap::new()));
        if let Some((width, height, rgba)) = cache.lock().ok()?.get(&key) {
            return Some((*width, *height, rgba.clone()));
        }
        let rendered = render_uncached(symbol, size, color)?;
        cache.lock().ok()?.insert(key, rendered.clone());
        Some(rendered)
    }

    fn render_uncached(symbol: &str, size: f32, color: Color) -> Option<(u32, u32, Vec<u8>)> {
        let _main_thread = MainThreadMarker::new()?;
        if !NSProcessInfo::processInfo().isOperatingSystemAtLeastVersion(NSOperatingSystemVersion {
            majorVersion: 11,
            minorVersion: 0,
            patchVersion: 0,
        }) {
            return None;
        }
        let name = NSString::from_str(symbol);
        let image = NSImage::imageWithSystemSymbolName_accessibilityDescription(&name, None)?;
        let color = NSColor::colorWithSRGBRed_green_blue_alpha(
            color.r as f64,
            color.g as f64,
            color.b as f64,
            color.a as f64,
        );
        let color_configuration =
            NSImageSymbolConfiguration::configurationWithHierarchicalColor(&color);
        // Ask AppKit for a 3x point-size rendering before converting it for Iced.
        // SAFETY: NSFontWeightRegular is an AppKit-provided immutable constant.
        let regular_weight = unsafe { NSFontWeightRegular };
        let size_configuration =
            NSImageSymbolConfiguration::configurationWithPointSize_weight_scale(
                size.max(1.0) as f64 * 3.0,
                regular_weight,
                NSImageSymbolScale::Medium,
            );
        let configuration =
            size_configuration.configurationByApplyingConfiguration(&color_configuration);
        let image = image.imageWithSymbolConfiguration(&configuration)?;
        let pixels = (size.max(1.0) * 3.0).ceil() as f64;
        image.setSize(NSSize::new(pixels, pixels));
        let data = image.TIFFRepresentation()?;
        let mut bytes = vec![0; data.length()];
        let destination = std::ptr::NonNull::new(bytes.as_mut_ptr().cast())?;
        unsafe { data.getBytes_length(destination, bytes.len()) };
        let rgba = ::image::load_from_memory(&bytes).ok()?.into_rgba8();
        Some((rgba.width(), rgba.height(), rgba.into_raw()))
    }
}
