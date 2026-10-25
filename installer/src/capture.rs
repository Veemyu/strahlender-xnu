//! Deterministic screenshots of the actual application renderer, not HTML mocks.
use std::{fs, io::BufWriter, path::PathBuf};

pub const SCENARIOS: [&str; 40] = [
    "error-prerequisite",
    "update-confirmation",
    "setup-dependencies",
    "update-available",
    "target",
    "target-ios",
    "target-mac",
    "demo-target-ios",
    "review-ios",
    "setup-ios",
    "keys-empty",
    "keys-selected",
    "keys-not-found",
    "game-empty",
    "game-selected",
    "nca",
    "update-empty",
    "update-selected",
    "mods-folder",
    "mods-folder-ios",
    "review-skip-mods",
    "mods-empty",
    "mods-selected",
    "mods-exefs-only",
    "mods-ips-ready",
    "mods-ips-ios-ready",
    "review-mod",
    "error",
    "error-details",
    "error-disk",
    "review",
    "demo-review",
    "setup",
    "progress",
    "progress-details",
    "preflight-running",
    "preflight-details",
    "finished",
    "long-name",
    "demo",
];

pub struct Capture {
    pub scenes: Vec<&'static str>,
    pub directory: PathBuf,
    pub index: usize,
    pub waiting: bool,
    pub layout_errors: Vec<String>,
}

impl Capture {
    pub fn new(directory: PathBuf, scenes: Vec<&'static str>) -> Self {
        Self {
            scenes: if scenes.is_empty() {
                vec!["target"]
            } else {
                scenes
            },
            directory,
            index: 0,
            waiting: false,
            layout_errors: Vec::new(),
        }
    }
    pub fn filename(&self) -> PathBuf {
        self.directory
            .join(format!("dark-{}.png", self.scenes[self.index]))
    }
}

pub async fn save(screenshot: iced::window::Screenshot, path: PathBuf) -> Result<PathBuf, String> {
    tokio::task::spawn_blocking(move || {
        fs::create_dir_all(path.parent().ok_or("Screenshot-Pfad hat keinen Ordner")?)
            .map_err(|e| e.to_string())?;
        let file = fs::File::create(&path).map_err(|e| e.to_string())?;
        let mut encoder = png::Encoder::new(
            BufWriter::new(file),
            screenshot.size.width,
            screenshot.size.height,
        );
        encoder.set_color(png::ColorType::Rgba);
        encoder.set_depth(png::BitDepth::Eight);
        let mut writer = encoder.write_header().map_err(|e| e.to_string())?;
        writer
            .write_image_data(&screenshot.rgba)
            .map_err(|e| e.to_string())?;
        writer.finish().map_err(|e| e.to_string())?;
        Ok(path)
    })
    .await
    .map_err(|e| e.to_string())?
}

/// Inspect the actual laid-out main content, excluding the intentionally scrollable log.
#[derive(Default)]
pub struct LayoutCheck(Option<iced::Size>);

impl iced::advanced::widget::Operation<Option<iced::Size>> for LayoutCheck {
    fn traverse(
        &mut self,
        operate: &mut dyn FnMut(&mut dyn iced::advanced::widget::Operation<Option<iced::Size>>),
    ) {
        operate(self);
    }
    fn scrollable(
        &mut self,
        id: Option<&iced::advanced::widget::Id>,
        bounds: iced::Rectangle,
        content: iced::Rectangle,
        _: iced::Vector,
        _: &mut dyn iced::advanced::widget::operation::Scrollable,
    ) {
        if id == Some(&iced::advanced::widget::Id::new("main-content")) {
            self.0 = Some(iced::Size::new(
                (content.width - bounds.width).max(0.0),
                (content.height - bounds.height).max(0.0),
            ));
        }
    }
    fn finish(&self) -> iced::advanced::widget::operation::Outcome<Option<iced::Size>> {
        iced::advanced::widget::operation::Outcome::Some(self.0)
    }
}
