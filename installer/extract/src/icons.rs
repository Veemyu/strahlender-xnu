//! Original icon variants and localized titles from the Control NCAs; everything stays outside Git.
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, fs, io::Cursor, path::Path};

use crate::nca::{hex, read_nacp};

/// NACP file name suffix, locale and display label.
const LANGUAGES: [(&str, &str, &str); 16] = [
    ("AmericanEnglish", "en-US", "English (US)"),
    ("BritishEnglish", "en-GB", "English (UK)"),
    ("Japanese", "ja", "日本語"),
    ("French", "fr", "Français"),
    ("German", "de", "Deutsch"),
    ("LatinAmericanSpanish", "es-419", "Español (Latinoamérica)"),
    ("Spanish", "es-ES", "Español"),
    ("Italian", "it", "Italiano"),
    ("Dutch", "nl", "Nederlands"),
    ("CanadianFrench", "fr-CA", "Français (Canada)"),
    ("Portuguese", "pt-PT", "Português"),
    ("BrazilianPortuguese", "pt-BR", "Português (Brasil)"),
    ("Russian", "ru", "Русский"),
    ("Korean", "ko", "한국어"),
    ("TraditionalChinese", "zh-Hant", "繁體中文"),
    ("SimplifiedChinese", "zh-Hans", "简体中文"),
];

/// Square RGB PNG between 16 and 4096 pixels.
fn normalize(data: &[u8]) -> Result<Vec<u8>, String> {
    let image = image::load_from_memory(data).map_err(|e| e.to_string())?;
    if image.width() != image.height() || !(16..=4096).contains(&image.width()) {
        return Err("Icon must be square and between 16 and 4096 pixels".into());
    }
    let mut out = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgb8(image.to_rgb8())
        .write_to(&mut out, image::ImageFormat::Png)
        .map_err(|e| e.to_string())?;
    Ok(out.into_inner())
}

fn default_variant(ids: &[&str]) -> String {
    ["en-US", "en-GB", "de"]
        .into_iter()
        .find(|id| ids.contains(id))
        .map(str::to_string)
        .or_else(|| ids.iter().min().map(|id| id.to_string()))
        .unwrap_or_default()
}

/// Reads the base Control, then the update Control on top, and writes the PNGs plus icons.json.
pub fn ingest(
    controls: &[&Path],
    destination: &Path,
    title_id: &str,
    log: &mut dyn FnMut(&str),
) -> Result<Value, String> {
    fs::create_dir_all(destination).map_err(|e| e.to_string())?;
    let mut variants: BTreeMap<&str, Value> = BTreeMap::new();
    let mut titles = Map::new();
    let mut version = String::new();
    for directory in controls {
        let entries: Vec<_> = fs::read_dir(directory)
            .map(|r| r.flatten().collect())
            .unwrap_or_default();
        let nacp = entries.iter().find(|e| {
            e.file_name()
                .to_string_lossy()
                .eq_ignore_ascii_case("control.nacp")
                && e.file_type().is_ok_and(|t| t.is_file())
        });
        if let Some(entry) = nacp {
            let (localized, display) =
                read_nacp(&fs::read(entry.path()).map_err(|e| e.to_string())?)?;
            for (locale, name, publisher) in localized {
                titles.insert(
                    locale.to_string(),
                    json!({"name": name, "publisher": publisher}),
                );
            }
            if !display.is_empty() {
                version = display;
            }
        }
        for (name, locale, label) in LANGUAGES {
            let path = directory.join(format!("icon_{name}.dat"));
            if !path.is_file() {
                continue;
            }
            let png = match fs::read(&path)
                .map_err(|e| e.to_string())
                .and_then(|d| normalize(&d))
            {
                Ok(png) => png,
                Err(_) => {
                    log(&format!("Notice: invalid icon variant {locale}"));
                    continue;
                }
            };
            let digest = hex(&Sha256::digest(&png));
            let image = format!("{digest}.png");
            fs::write(destination.join(&image), &png).map_err(|e| e.to_string())?;
            variants.insert(
                locale,
                json!({"id": locale, "label": label, "image": image, "sha256": digest, "icon": format!("BDSP_{}", &digest[..24])}),
            );
        }
    }
    let ids: Vec<&str> = variants.keys().copied().collect();
    let manifest = json!({
        "schema": 1,
        "title_id": title_id,
        "default": default_variant(&ids),
        "variants": variants.values().collect::<Vec<_>>(),
        "titles": titles,
        "display_version": version,
    });
    let text = serde_json::to_string_pretty(&manifest).map_err(|e| e.to_string())? + "\n";
    let temporary = destination.join("icons.json.tmp");
    fs::write(&temporary, text)
        .and_then(|_| fs::rename(&temporary, destination.join("icons.json")))
        .map_err(|e| e.to_string())?;
    log(&format!("Original icons: {} language variants", ids.len()));
    Ok(manifest)
}
