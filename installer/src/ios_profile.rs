//! Read identity only from an earlier installer IPA; never unpack its game data.
use serde_json::Value;
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Profile {
    pub game: String,
    pub id: String,
    pub bundle: String,
    pub name: String,
    #[serde(default)]
    pub aliases: Vec<String>,
}

pub fn new_id() -> String {
    use sha2::{Digest, Sha256};
    use std::io::Read;
    static SEQUENCE: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let mut bytes = [0u8; 32];
    if std::fs::File::open("/dev/urandom")
        .and_then(|mut file| file.read_exact(&mut bytes))
        .is_err()
    {
        let value = format!(
            "{:?}-{}-{}",
            std::time::SystemTime::now(),
            std::process::id(),
            SEQUENCE.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        );
        bytes.copy_from_slice(&Sha256::digest(value));
    }
    bytes[..10]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

pub fn load() -> Result<Vec<Profile>, String> {
    let path = crate::workspace::data_dir()?.join("ios-profiles.json");
    let bytes = match std::fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(error.to_string()),
    };
    if bytes.len() > 1024 * 1024 {
        return Err("The saved app profile list is too large.".into());
    }
    serde_json::from_slice(&bytes).map_err(|_| {
        "The saved app profile list is unreadable. Choose a previous IPA for updates.".into()
    })
}

pub fn matching<'a>(profiles: &'a [Profile], name: &str) -> Option<&'a Profile> {
    let name = name.to_lowercase();
    let mut found = profiles.iter().filter(|profile| {
        profile.name.to_lowercase() == name
            || profile
                .aliases
                .iter()
                .any(|alias| alias.to_lowercase() == name)
    });
    let first = found.next()?;
    if found.next().is_some() {
        None
    } else {
        Some(first)
    }
}

pub fn remember(profile: &Profile) -> Result<(), String> {
    use std::io::Write;
    let mut profiles = load()?;
    let mut updated = profile.clone();
    if let Some(previous) = profiles
        .iter()
        .find(|item| item.game == profile.game && item.id == profile.id)
    {
        updated.aliases.extend(previous.aliases.iter().cloned());
        updated.aliases.push(previous.name.clone());
    }
    updated.aliases.sort();
    updated.aliases.dedup();
    profiles.retain(|item| item.game != updated.game || item.id != updated.id);
    profiles.push(updated);
    let parent = crate::workspace::data_dir()?;
    std::fs::create_dir_all(&parent).map_err(|e| e.to_string())?;
    let temporary = parent.join(format!(".ios-profiles-{}", new_id()));
    let result = (|| {
        let mut output = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
            .map_err(|e| e.to_string())?;
        output
            .write_all(&serde_json::to_vec(&profiles).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        output.sync_all().map_err(|e| e.to_string())?;
        std::fs::rename(&temporary, parent.join("ios-profiles.json")).map_err(|e| e.to_string())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

fn parse(metadata: Value, info: Value) -> Result<Profile, String> {
    let string = |key| {
        metadata
            .get(key)
            .and_then(Value::as_str)
            .map(str::to_owned)
            .ok_or_else(|| format!("IPA has no {key}"))
    };
    let game = string("GameID")?;
    let id = string("SaveProfile")?;
    let name = string("ModName")?;
    let bundle = info
        .get("CFBundleIdentifier")
        .and_then(Value::as_str)
        .ok_or("IPA has no bundle identity")?
        .to_owned();
    let hex = |s: &str, len| {
        s.len() == len
            && s.bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    };
    if !hex(&game, 16)
        || !hex(&id, 20)
        || name.trim().is_empty()
        || metadata["ExternalLibrary"] != true
        || metadata["SaveStorageVersion"] != 2
        || bundle != format!("dev.local.xnubdsp.game.{game}.{id}")
    {
        return Err("Choose a mod IPA from this installer with a stable save profile. Older device builds need an explicit save export and import.".into());
    }
    Ok(Profile {
        game,
        id,
        bundle,
        name,
        aliases: Vec::new(),
    })
}

#[cfg(target_os = "macos")]
pub fn read_ipa(path: &Path) -> Result<Profile, String> {
    use std::io::{Read, Write};
    use std::process::{Command, Stdio};
    let path = path
        .canonicalize()
        .map_err(|_| "The selected IPA is no longer readable.")?;
    fn entry(path: &Path, name: &str) -> Result<Value, String> {
        let mut unzip = Command::new("/usr/bin/unzip")
            .args(["-p"])
            .arg(path)
            .arg(name)
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| "Could not read the IPA archive.")?;
        let mut bytes = Vec::new();
        let read = unzip
            .stdout
            .take()
            .ok_or("Missing archive output")?
            .take(128 * 1024 + 1)
            .read_to_end(&mut bytes);
        if read.is_err() || bytes.len() > 128 * 1024 {
            let _ = unzip.kill();
            let _ = unzip.wait();
            return Err("The IPA identity is too large or unreadable.".into());
        }
        if !unzip
            .wait()
            .map_err(|_| "Could not read IPA identity")?
            .success()
            || bytes.is_empty()
        {
            return Err("This IPA has no compatible installer identity.".into());
        }
        let mut convert = Command::new("/usr/bin/plutil")
            .args(["-convert", "json", "-o", "-", "-"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| "Could not read the IPA property list.")?;
        let write = convert
            .stdin
            .take()
            .ok_or("Missing property-list input")?
            .write_all(&bytes);
        if write.is_err() {
            let _ = convert.kill();
            let _ = convert.wait();
            return Err("Invalid IPA property list.".into());
        }
        let result = convert
            .wait_with_output()
            .map_err(|_| "Could not parse IPA identity")?;
        if !result.status.success() {
            return Err("Invalid IPA property list.".into());
        }
        serde_json::from_slice(&result.stdout).map_err(|_| "Invalid IPA identity.".into())
    }
    parse(
        entry(&path, "Payload/BDSP.app/res/install-data.plist")?,
        entry(&path, "Payload/BDSP.app/Info.plist")?,
    )
}

#[cfg(not(target_os = "macos"))]
pub fn read_ipa(_path: &Path) -> Result<Profile, String> {
    Err("IPA builds currently require macOS.".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    #[cfg(target_os = "macos")]
    fn reads_only_the_profile_metadata_from_an_ipa() {
        let root = std::env::temp_dir().join(format!("installer-profile-{}", new_id()));
        let app = root.join("Payload/BDSP.app");
        std::fs::create_dir_all(app.join("res")).unwrap();
        std::fs::write(app.join("Info.plist"), r#"<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>dev.local.xnubdsp.game.0100000011d90000.0123456789abcdef0123</string></dict></plist>"#).unwrap();
        std::fs::write(app.join("res/install-data.plist"), r#"<?xml version="1.0"?><plist version="1.0"><dict><key>GameID</key><string>0100000011d90000</string><key>SaveProfile</key><string>0123456789abcdef0123</string><key>ModName</key><string>Previous mod name</string><key>ExternalLibrary</key><true/><key>SaveStorageVersion</key><integer>2</integer></dict></plist>"#).unwrap();
        let ipa = root.join("Previous app.ipa");
        assert!(
            std::process::Command::new("/usr/bin/ditto")
                .args(["-c", "-k", "--keepParent"])
                .arg(root.join("Payload"))
                .arg(&ipa)
                .status()
                .unwrap()
                .success()
        );
        let result = read_ipa(&ipa);
        std::fs::remove_dir_all(&root).unwrap();
        assert_eq!(result.unwrap().name, "Previous mod name");
    }

    #[test]
    fn profile_lookup_requires_a_unique_name_or_alias() {
        let profile = Profile {
            game: "0100000011d90000".into(),
            id: new_id(),
            bundle: "test.bundle".into(),
            name: "Renamed mod".into(),
            aliases: vec!["Previous name".into()],
        };
        assert_eq!(profile.id.len(), 20);
        assert_ne!(profile.id, new_id());
        assert_eq!(
            matching(std::slice::from_ref(&profile), "PREVIOUS NAME"),
            Some(&profile)
        );
        assert!(matching(&[profile.clone(), profile], "Renamed mod").is_none());
    }

    #[test]
    fn profiles_are_not_derived_from_the_new_display_name() {
        let data = serde_json::json!({"GameID":"0100000011d90000", "SaveProfile":"0123456789abcdef0123", "ModName":"Previous mod name", "ExternalLibrary":true,"SaveStorageVersion":2});
        let info = serde_json::json!({"CFBundleIdentifier":"dev.local.xnubdsp.game.0100000011d90000.0123456789abcdef0123"});
        assert!(parse(data.clone(), info.clone()).is_ok());
        let mut old = data.clone();
        old["SaveStorageVersion"] = Value::Null;
        assert!(parse(old, info.clone()).is_err());
        let mut base = data;
        base["SaveProfile"] = "vanilla".into();
        assert!(parse(base, info).is_err());
    }
}
