//! Export build-time artwork for packagers. Never shipped as an end-user tool.
use std::{path::Path, process::ExitCode};

macro_rules! assets {
    ($($name:literal),+ $(,)?) => {
        const ASSETS: &[(&str, &[u8])] = &[$(
            ($name, include_bytes!(concat!(env!("OUT_DIR"), "/brand/", $name))),
        )+];
    };
}
assets!(
    "icon.svg",
    "16.png",
    "32.png",
    "48.png",
    "64.png",
    "128.png",
    "256.png",
    "512.png",
    "1024.png",
    "foreground.png",
    "full-bleed.png"
);

fn export(directory: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(directory)?;
    for (name, bytes) in ASSETS {
        std::fs::write(directory.join(name), bytes)?;
    }
    Ok(())
}

fn main() -> ExitCode {
    let arguments: Vec<_> = std::env::args_os().skip(1).collect();
    if arguments.len() != 2 || arguments[0] != "--output" {
        eprintln!("Usage: installer_icons --output DIRECTORY");
        return ExitCode::from(2);
    }
    match export(Path::new(&arguments[1])) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("Could not export installer icons: {error}");
            ExitCode::FAILURE
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn artwork_has_the_expected_dimensions_and_transparency() {
        for (name, bytes) in ASSETS.iter().filter(|(name, _)| name.ends_with(".png")) {
            let mut reader = png::Decoder::new(Cursor::new(bytes)).read_info().unwrap();
            let expected = name.trim_end_matches(".png").parse::<u32>().unwrap_or(1024);
            assert_eq!(
                (reader.info().width, reader.info().height),
                (expected, expected)
            );
            assert_eq!(reader.info().color_type, png::ColorType::Rgba);
            let mut pixels = vec![0; reader.output_buffer_size().unwrap()];
            reader.next_frame(&mut pixels).unwrap();
            let corner_alpha = pixels[3];
            assert_eq!(
                corner_alpha,
                if *name == "full-bleed.png" { 255 } else { 0 },
                "{name}"
            );
            if *name != "foreground.png" {
                let background = ((expected * (expected / 4) + expected / 2) * 4) as usize;
                assert_eq!(
                    &pixels[background..background + 4],
                    &[255, 255, 255, 255],
                    "{name}"
                );
            }
        }
    }
}
