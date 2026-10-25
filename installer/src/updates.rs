//! Only separately signed release metadata may authorize an installer replacement.
use base64::{Engine, engine::general_purpose::STANDARD};
use ed25519_dalek::{Signature, VerifyingKey};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    io::{Read, Write},
    path::PathBuf,
};

#[derive(Debug, Clone, Deserialize)]
pub struct Release {
    pub version: String,
    pub assets: Vec<Asset>,
    #[serde(skip)]
    pub(crate) tag: Option<String>,
}
#[derive(Debug, Clone, Deserialize)]
pub struct Asset {
    pub target: String,
    pub name: String,
    pub sha256: String,
}

pub fn host() -> String {
    format!(
        "{}-{}",
        if cfg!(target_os = "macos") {
            "macos"
        } else {
            std::env::consts::OS
        },
        std::env::consts::ARCH
    )
}
fn version(value: &str) -> Option<[u64; 3]> {
    let value = value.strip_prefix("installer-").unwrap_or(value);
    let numbers: Vec<_> = value
        .strip_prefix('v')
        .unwrap_or(value)
        .split('.')
        .map(str::parse)
        .collect::<Result<_, _>>()
        .ok()?;
    numbers.try_into().ok()
}
pub fn verify(bytes: &[u8], signature: &str, key: &str) -> Result<Release, String> {
    let key: [u8; 32] = STANDARD
        .decode(key.trim())
        .map_err(|e| e.to_string())?
        .try_into()
        .map_err(|_| "Invalid update public key.")?;
    let signature = Signature::from_slice(
        &STANDARD
            .decode(signature.trim())
            .map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    VerifyingKey::from_bytes(&key)
        .map_err(|e| e.to_string())?
        .verify_strict(bytes, &signature)
        .map_err(|_| "Installer update signature is invalid.")?;
    let release: Release = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
    if version(&release.version).is_none() {
        return Err("Invalid installer release version.".into());
    }
    for asset in &release.assets {
        if asset.name.is_empty()
            || asset.name.starts_with('.')
            || !asset
                .name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
            || asset.sha256.len() != 64
            || !asset.sha256.bytes().all(|b| b.is_ascii_hexdigit())
        {
            return Err("Invalid installer release asset.".into());
        }
    }
    Ok(release)
}
pub fn check() -> Result<Option<Release>, String> {
    let Some(key) = option_env!("BDSP_INSTALLER_UPDATE_PUBLIC_KEY").filter(|k| !k.is_empty())
    else {
        return Ok(None);
    };
    let client = crate::workspace::client()?;
    let response = client
        .get("https://api.github.com/repos/Veemyu/strahlender-xnu/releases?per_page=100")
        .send()
        .map_err(|e| e.to_string())?;
    if response.status() == reqwest::StatusCode::NOT_FOUND {
        return Ok(None);
    }
    let releases: Vec<serde_json::Value> = response
        .error_for_status()
        .and_then(|r| r.json())
        .map_err(|e| e.to_string())?;
    let Some(latest) = releases.iter().find(|release| {
        release["draft"].as_bool() == Some(false)
            && release["prerelease"].as_bool() == Some(false)
            && release["tag_name"].as_str().and_then(version).is_some()
            && release["assets"].as_array().is_some_and(|assets| {
                ["installer-update.json", "installer-update.json.sig"]
                    .iter()
                    .all(|name| {
                        assets
                            .iter()
                            .any(|asset| asset["name"].as_str() == Some(name))
                    })
            })
    }) else {
        return Ok(None);
    };
    let tag = latest["tag_name"]
        .as_str()
        .ok_or("Release version missing.")?;
    if version(tag).is_none() {
        return Ok(None);
    }
    let prefix = format!("https://github.com/Veemyu/strahlender-xnu/releases/download/{tag}");
    let bytes = download_small(&client, &format!("{prefix}/installer-update.json"))?;
    let signature = String::from_utf8(download_small(
        &client,
        &format!("{prefix}/installer-update.json.sig"),
    )?)
    .map_err(|e| e.to_string())?;
    let mut release = verify(&bytes, &signature, key)?;
    if version(tag) != version(&release.version) {
        return Err("Release tag and signed manifest disagree.".into());
    }
    release.tag = Some(tag.to_owned());
    Ok(
        (version(&release.version) > version(env!("CARGO_PKG_VERSION"))
            && release.assets.iter().any(|a| a.target == host()))
        .then_some(release),
    )
}
fn download_small(client: &reqwest::blocking::Client, url: &str) -> Result<Vec<u8>, String> {
    let mut bytes = Vec::new();
    client
        .get(url)
        .send()
        .and_then(|r| r.error_for_status())
        .map_err(|e| e.to_string())?
        .take(1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() > 1024 * 1024 {
        return Err("Update metadata is too large.".into());
    }
    Ok(bytes)
}
pub fn download(release: &Release) -> Result<PathBuf, String> {
    let asset = release
        .assets
        .iter()
        .find(|a| a.target == host())
        .ok_or("No update for this computer.")?;
    let folder = crate::workspace::data_dir()?
        .join("updates")
        .join(&release.version);
    std::fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
    let destination = folder.join(&asset.name);
    let partial = destination.with_extension("partial");
    let result = (|| {
        let tag = release
            .tag
            .clone()
            .unwrap_or_else(|| format!("v{}", release.version.trim_start_matches('v')));
        let url = format!(
            "https://github.com/Veemyu/strahlender-xnu/releases/download/{}/{}",
            tag, asset.name
        );
        let mut response = crate::workspace::client()?
            .get(url)
            .send()
            .and_then(|r| r.error_for_status())
            .map_err(|e| e.to_string())?;
        let mut file = std::fs::File::create(&partial).map_err(|e| e.to_string())?;
        let mut hash = Sha256::new();
        let mut buffer = [0_u8; 65536];
        loop {
            let count = response.read(&mut buffer).map_err(|e| e.to_string())?;
            if count == 0 {
                break;
            }
            hash.update(&buffer[..count]);
            file.write_all(&buffer[..count])
                .map_err(|e| e.to_string())?;
        }
        file.sync_all().map_err(|e| e.to_string())?;
        if format!("{:x}", hash.finalize()) != asset.sha256 {
            return Err("Installer download is damaged. Retry the update.".into());
        }
        std::fs::rename(&partial, &destination).map_err(|e| e.to_string())?;
        Ok(destination)
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(partial);
    }
    result
}

pub fn apply(download: &std::path::Path) -> Result<(), String> {
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    if cfg!(target_os = "macos") {
        let current = exe
            .parent()
            .and_then(|p| p.parent())
            .and_then(|p| p.parent())
            .filter(|p| p.extension().is_some_and(|x| x == "app"))
            .ok_or("Updates require the packaged installer app.")?;
        let stage = download
            .parent()
            .ok_or("Update folder missing.")?
            .join(format!(
                "unpacked-{}",
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map_err(|e| e.to_string())?
                    .as_nanos()
            ));
        std::fs::create_dir(&stage).map_err(|e| e.to_string())?;
        tar::Archive::new(flate2::read::GzDecoder::new(
            std::fs::File::open(download).map_err(|e| e.to_string())?,
        ))
        .unpack(&stage)
        .map_err(|e| e.to_string())?;
        let app = stage.join("Strahlender Installer.app");
        for (tool, args) in [
            ("codesign", vec!["--verify", "--deep", "--strict"]),
            ("spctl", vec!["--assess", "--type", "execute"]),
        ] {
            if !std::process::Command::new(tool)
                .args(args)
                .arg(&app)
                .status()
                .is_ok_and(|s| s.success())
            {
                return Err("The update is not signed and approved by macOS. The current installer remains installed.".into());
            }
        }
        start_helper(&exe, &app, current)
    } else if let Some(appimage) = std::env::var_os("APPIMAGE") {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(download, std::fs::Permissions::from_mode(0o755))
                .map_err(|e| e.to_string())?;
        }
        start_helper(&exe, download, std::path::Path::new(&appimage))
    } else {
        Err(format!(
            "The verified update was saved as {}. Extract it to replace your portable installer.",
            download.file_name().unwrap_or_default().to_string_lossy()
        ))
    }
}
fn start_helper(
    exe: &std::path::Path,
    source: &std::path::Path,
    destination: &std::path::Path,
) -> Result<(), String> {
    let parent = destination.parent().ok_or("Install folder missing.")?;
    let probe = parent.join(format!(".strahlender-write-check-{}", std::process::id()));
    let file = std::fs::OpenOptions::new().write(true).create_new(true).open(&probe)
        .map_err(|_| format!("This installation folder is read-only. Your verified update remains saved as {}. Copy it to a writable Applications folder to update.", source.file_name().unwrap_or_default().to_string_lossy()))?;
    drop(file);
    std::fs::remove_file(probe).map_err(|e| e.to_string())?;
    let helper = exe.with_file_name("installer_update");
    let temporary = source
        .parent()
        .ok_or("Update folder missing.")?
        .join("installer_update");
    std::fs::copy(helper, &temporary).map_err(|e| e.to_string())?;
    std::process::Command::new(temporary)
        .arg(std::process::id().to_string())
        .arg(source)
        .arg(destination)
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};
    #[test]
    fn signed_metadata_rejects_tampering() {
        let key = SigningKey::from_bytes(&[19; 32]);
        let bytes = br#"{"version":"0.2.0","assets":[]}"#;
        let signature = STANDARD.encode(key.sign(bytes).to_bytes());
        let public = STANDARD.encode(key.verifying_key().as_bytes());
        assert!(verify(bytes, &signature, &public).is_ok());
        assert!(verify(br#"{"version":"9.0.0","assets":[]}"#, &signature, &public).is_err());
    }
    #[test]
    fn versions_compare_numerically() {
        assert!(version("0.10.0") > version("0.9.9"));
        assert_eq!(version("v0.2.1"), Some([0, 2, 1]));
        assert_eq!(version("installer-v0.2.1"), Some([0, 2, 1]));
        assert_eq!(version("installer-nightly-123-1"), None);
        assert_eq!(version("../main"), None);
    }
    #[test]
    fn signed_unsafe_asset_names_are_rejected() {
        let key = SigningKey::from_bytes(&[21; 32]);
        let bytes=serde_json::to_vec(&serde_json::json!({"version":"0.2.0","assets":[{"target":"macos-aarch64","name":"../../installer.tar.gz","sha256":"0".repeat(64)}]})).unwrap();
        let signature = STANDARD.encode(key.sign(&bytes).to_bytes());
        let public = STANDARD.encode(key.verifying_key().as_bytes());
        assert!(verify(&bytes, &signature, &public).is_err());
    }
}
