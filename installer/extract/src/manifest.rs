//! Extraction receipt (manifest.json): hashes, title ID, version and sizes; no key material, no paths.
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::Read,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

pub const SCHEMA: u64 = 1;

pub fn file_sha256(path: &Path) -> std::io::Result<String> {
    let mut file = fs::File::open(path)?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0u8; 1 << 20];
    loop {
        let n = file.read(&mut buffer)?;
        if n == 0 {
            return Ok(crate::nca::hex(&digest.finalize()));
        }
        digest.update(&buffer[..n]);
    }
}

/// Files of a directory first, then its subdirectories, both sorted (the order of os.walk).
fn walk(root: &Path, out: &mut Vec<PathBuf>) -> std::io::Result<()> {
    let mut files = Vec::new();
    let mut dirs = Vec::new();
    for entry in fs::read_dir(root)? {
        let path = entry?.path();
        if path.is_dir() {
            dirs.push(path)
        } else {
            files.push(path)
        }
    }
    files.sort();
    dirs.sort();
    out.extend(files);
    for dir in dirs {
        walk(&dir, out)?;
    }
    Ok(())
}

/// Content identity of one container or of a folder of NCAs and tickets, without recording its path.
pub fn fingerprint(path: Option<&Path>) -> std::io::Result<String> {
    let Some(path) = path else {
        return Ok(String::new());
    };
    if path.is_file() {
        return file_sha256(path);
    }
    let mut files = Vec::new();
    walk(path, &mut files)?;
    let mut digest = Sha256::new();
    for file in files {
        let wanted = file
            .extension()
            .is_some_and(|e| e.eq_ignore_ascii_case("nca") || e.eq_ignore_ascii_case("tik"));
        if !wanted {
            continue;
        }
        let relative = file
            .strip_prefix(path)
            .unwrap()
            .to_string_lossy()
            .replace('\\', "/");
        digest.update(relative.as_bytes());
        digest.update([0u8]);
        digest.update(hex_bytes(&file_sha256(&file)?));
    }
    Ok(crate::nca::hex(&digest.finalize()))
}

fn hex_bytes(text: &str) -> Vec<u8> {
    (0..text.len() / 2)
        .map(|i| u8::from_str_radix(&text[i * 2..i * 2 + 2], 16).unwrap_or(0))
        .collect()
}

pub fn romfs_stats(romfs: &Path) -> std::io::Result<(u64, u64)> {
    let mut files = Vec::new();
    walk(romfs, &mut files)?;
    let mut total = (0, 0);
    for file in files
        .iter()
        .filter(|f| f.file_name().is_some_and(|n| n != ".DS_Store"))
    {
        total = (total.0 + 1, total.1 + fs::metadata(file)?.len());
    }
    Ok(total)
}

fn timestamp() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0) as i64;
    let (days, rest) = (seconds.div_euclid(86400), seconds.rem_euclid(86400));
    // Civil date from days since 1970-01-01 (Howard Hinnant's algorithm).
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        rest / 3600,
        rest % 3600 / 60,
        rest % 60
    )
}

pub struct Inputs<'a> {
    pub base_kind: &'a str,
    pub base: &'a Path,
    pub update: Option<&'a Path>,
    pub base_size: u64,
    pub update_size: u64,
}

pub struct Game<'a> {
    pub title_id: &'a str,
    pub title_version: u32,
    pub display_version: &'a str,
    pub update_applied: bool,
}

pub fn build(work: &Path, game: &Game, inputs: &Inputs) -> std::io::Result<Value> {
    let exefs = work.join("exefs");
    let mut files = serde_json::Map::new();
    let mut names: Vec<_> = fs::read_dir(&exefs)?
        .flatten()
        .filter(|e| e.path().is_file())
        .collect();
    names.sort_by_key(|e| e.file_name());
    for entry in names {
        files.insert(
            entry.file_name().to_string_lossy().into_owned(),
            json!(file_sha256(&entry.path())?),
        );
    }
    let (count, bytes) = romfs_stats(&work.join("romfs"))?;
    Ok(json!({
        "schema": SCHEMA,
        "stage": "extract",
        "created": timestamp(),
        "title_id": game.title_id,
        "title_version": game.title_version,
        "display_version": game.display_version,
        "update_applied": game.update_applied,
        "inputs": {
            "xci_size": inputs.base_size,
            "nsp_size": inputs.update_size,
            "base_kind": inputs.base_kind,
            "base_sha256": fingerprint(Some(inputs.base))?,
            "update_sha256": fingerprint(inputs.update)?,
        },
        "exefs": {"main": {"sha256": file_sha256(&exefs.join("main"))?}, "files_sha256": files},
        "romfs": {"files": count, "bytes": bytes},
    }))
}

/// True if manifest.json matches the inputs and the results still on disk.
pub fn matches(work: &Path, inputs: &Inputs) -> bool {
    let check = || -> Option<bool> {
        let record: Value =
            serde_json::from_slice(&fs::read(work.join("manifest.json")).ok()?).ok()?;
        if record["schema"] != SCHEMA || record["stage"] != "extract" {
            return Some(false);
        }
        let recorded = &record["inputs"];
        if recorded["xci_size"] != inputs.base_size
            || recorded["nsp_size"] != inputs.update_size
            || recorded["base_kind"] != inputs.base_kind
            || recorded["base_sha256"] != fingerprint(Some(inputs.base)).ok()?
            || recorded["update_sha256"] != fingerprint(inputs.update).ok()?
        {
            return Some(false);
        }
        let exefs = work.join("exefs");
        if record["exefs"]["main"]["sha256"] != file_sha256(&exefs.join("main")).ok()? {
            return Some(false);
        }
        for (name, digest) in record["exefs"]["files_sha256"].as_object()? {
            if name.contains(['/', '\\']) || name == "." || name == ".." {
                return Some(false);
            }
            if name != "main" && *digest != file_sha256(&exefs.join(name)).ok()? {
                return Some(false);
            }
        }
        let (count, bytes) = romfs_stats(&work.join("romfs")).ok()?;
        Some(count > 0 && record["romfs"]["files"] == count && record["romfs"]["bytes"] == bytes)
    };
    check().unwrap_or(false)
}
