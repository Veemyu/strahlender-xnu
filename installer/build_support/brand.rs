//! Build-time SVG rendering; no system fonts or runtime icon downloads.
use resvg::{tiny_skia, usvg};
use std::{error::Error, fs, path::Path};

const SOURCE: &str = include_str!("../assets/brand/icon.svg");
const TILE: &str = "<rect id=\"tile\" width=\"512\" height=\"512\" rx=\"112\" fill=\"#fff\"/>";

fn render(svg: &str, size: u32) -> Result<tiny_skia::Pixmap, Box<dyn Error>> {
    let tree = usvg::Tree::from_str(svg, &usvg::Options::default())?;
    let mut pixels = tiny_skia::Pixmap::new(size, size).ok_or("Invalid icon dimensions")?;
    resvg::render(
        &tree,
        tiny_skia::Transform::from_scale(size as f32 / 512.0, size as f32 / 512.0),
        &mut pixels.as_mut(),
    );
    Ok(pixels)
}

pub fn generate(output: &Path) -> Result<(), Box<dyn Error>> {
    if SOURCE.matches(TILE).count() != 1 {
        return Err("The installer SVG must have exactly one named white tile".into());
    }
    for forbidden in [
        "<image",
        "<text",
        "<script",
        "href=",
        "url(http",
        "@font-face",
    ] {
        if SOURCE.contains(forbidden) {
            return Err(format!(
                "Installer SVG contains an external or non-vector resource: {forbidden}"
            )
            .into());
        }
    }
    fs::create_dir_all(output)?;
    fs::write(output.join("icon.svg"), SOURCE)?;
    for size in [16, 32, 48, 64, 128, 256, 512, 1024] {
        let pixels = render(SOURCE, size)?;
        pixels.save_png(output.join(format!("{size}.png")))?;
        if size == 64 {
            let rgba: Vec<_> = pixels
                .pixels()
                .iter()
                .flat_map(|pixel| {
                    let color = pixel.demultiply();
                    [color.red(), color.green(), color.blue(), color.alpha()]
                })
                .collect();
            fs::write(output.join("64.rgba"), rgba)?;
        }
    }
    // Apple supplies its own outer mask and the native lighting.
    render(&SOURCE.replace(TILE, ""), 1024)?.save_png(output.join("foreground.png"))?;
    render(
        &SOURCE.replace(TILE, &TILE.replace("rx=\"112\"", "rx=\"0\"")),
        1024,
    )?
    .save_png(output.join("full-bleed.png"))?;
    Ok(())
}
