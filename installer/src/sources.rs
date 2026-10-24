use crate::i18n::{Label as L, Language};
use std::{fs, path::PathBuf};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Slot {
    Base,
    Update,
    Keys,
}

#[derive(Debug, Clone)]
pub struct Source {
    pub path: PathBuf,
    pub description: String,
}

impl Source {
    pub fn name(&self) -> String {
        self.path
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned()
    }

    pub fn fixture(name: &str, description: &str) -> Self {
        Self {
            path: PathBuf::from(name),
            description: description.into(),
        }
    }
}

// Only cheap filesystem checks belong to the UI prototype. Container contents,
// key validity and game compatibility must be checked by the shared backend.
// Never read or return the contents of a key file here.
pub fn inspect(path: PathBuf, slot: Slot, language: Language) -> Result<Source, String> {
    let metadata = fs::metadata(&path).map_err(|_| language.t(L::Unreadable).to_owned())?;
    let description = if metadata.is_dir() {
        if slot == Slot::Keys {
            return Err(language.t(L::KeysFileOnly).into());
        }
        if slot == Slot::Update {
            return Err(language.t(L::WrongFile).into());
        }
        let entries = fs::read_dir(&path).map_err(|_| language.t(L::Unreadable).to_owned())?;
        let mut count = 0;
        for entry in entries {
            let entry = entry.map_err(|_| language.t(L::Unreadable).to_owned())?;
            if entry
                .path()
                .extension()
                .is_some_and(|ext| ext.eq_ignore_ascii_case("nca"))
                && entry.file_type().is_ok_and(|kind| kind.is_file())
            {
                count += 1;
            }
        }
        if count == 0 {
            return Err(language.t(L::NoNca).into());
        }
        format!(
            "{} · {count} {}",
            language.t(L::NcaFolder),
            language.t(if count == 1 { L::SingleFile } else { L::Files })
        )
    } else if metadata.is_file() {
        let extension = path
            .extension()
            .and_then(|ext| ext.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        let valid = match slot {
            Slot::Keys => extension == "keys",
            Slot::Base => matches!(extension.as_str(), "xci" | "nsp"),
            Slot::Update => extension == "nsp",
        };
        if !valid {
            return Err(match slot {
                Slot::Keys => language.t(L::WrongKeys),
                _ => language.t(L::WrongFile),
            }
            .into());
        }
        if metadata.len() == 0 {
            return Err(language.t(L::EmptyFile).into());
        }
        let _readable = fs::File::open(&path).map_err(|_| language.t(L::Unreadable).to_owned())?;
        if slot == Slot::Keys {
            language.t(L::PrivateKeys).into()
        } else {
            format!(
                "{} · {}",
                extension.to_ascii_uppercase(),
                size_label(metadata.len(), language)
            )
        }
    } else {
        return Err(language.t(L::WrongFile).into());
    };
    Ok(Source { path, description })
}

fn size_label(bytes: u64, language: Language) -> String {
    let size = if bytes >= 1 << 30 {
        format!("{:.1} GB", bytes as f64 / (1_u64 << 30) as f64)
    } else if bytes >= 1 << 20 {
        format!("{:.1} MB", bytes as f64 / (1_u64 << 20) as f64)
    } else {
        format!("{} KB", bytes.div_ceil(1024))
    };
    match language {
        Language::German => size.replace('.', ","),
        Language::English => size,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn file_sizes_use_the_ui_decimal_separator() {
        assert_eq!(size_label(1 << 30, Language::German), "1,0 GB");
        assert_eq!(size_label(1 << 30, Language::English), "1.0 GB");
    }

    #[test]
    fn checks_sources_without_modifying_or_reading_keys() {
        let root =
            std::env::temp_dir().join(format!("strahlender-source-test-{}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let game = root.join("Mein Spiel.NSP");
        fs::write(&game, b"synthetic").unwrap();
        assert!(inspect(game.clone(), Slot::Base, Language::English).is_ok());
        assert!(inspect(game.clone(), Slot::Keys, Language::English).is_err());
        assert_eq!(fs::read(&game).unwrap(), b"synthetic");
        let empty = root.join("empty.xci");
        fs::write(&empty, b"").unwrap();
        assert!(inspect(empty, Slot::Base, Language::English).is_err());
        let ncas = root.join("NCA Ordner");
        fs::create_dir_all(&ncas).unwrap();
        assert!(inspect(ncas.clone(), Slot::Base, Language::English).is_err());
        fs::write(ncas.join("content.NCA"), b"synthetic").unwrap();
        assert!(inspect(ncas.clone(), Slot::Base, Language::English).is_ok());
        assert!(inspect(ncas, Slot::Keys, Language::English).is_err());
        fs::remove_dir_all(root).unwrap();
    }
}
