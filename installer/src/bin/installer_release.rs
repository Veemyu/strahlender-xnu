//! Offline release metadata signing. No upload or release publication happens here.
use base64::{Engine, engine::general_purpose::STANDARD};
use ed25519_dalek::{Signer, SigningKey};

use std::path::Path;

/// The public download for a target: one universal Mac zip, one AppImage per Linux architecture, one Windows zip.
fn asset_name(host: &str) -> String {
    match host.split_once('-') {
        Some(("macos", _)) => "installer-macos-universal.zip".into(),
        Some(("linux", arch)) => format!("Strahlender-Installer-{arch}.AppImage"),
        _ => format!("installer-{host}.zip"),
    }
}

fn seed(path: &str) -> Result<SigningKey, String> {
    let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let seed: [u8; 32] = STANDARD
        .decode(text.trim())
        .map_err(|e| e.to_string())?
        .try_into()
        .map_err(|_| "Expected a base64-encoded 32-byte Ed25519 seed.")?;
    Ok(SigningKey::from_bytes(&seed))
}

fn manifest(version: &str, folder: &Path) -> Result<Vec<u8>, String> {
    let version = version.trim_start_matches('v');
    if version.split('.').count() != 3 || !version.split('.').all(|p| p.parse::<u64>().is_ok()) {
        return Err("Use a stable version such as 0.2.0.".into());
    }
    let mut assets = Vec::new();
    for host in [
        "macos-aarch64",
        "macos-x86_64",
        "linux-aarch64",
        "linux-x86_64",
        "windows-x86_64",
    ] {
        let name = asset_name(host);
        let path = folder.join(&name);
        if !path.is_file() {
            continue;
        }
        let sha256 = bdsp_extract::manifest::file_sha256(&path).map_err(|e| e.to_string())?;
        assets.push(serde_json::json!({"target":host,"name":name,"sha256":sha256}));
    }
    if assets.is_empty() {
        return Err("No installer release assets found.".into());
    }
    serde_json::to_vec_pretty(&serde_json::json!({"version":version,"assets":assets}))
        .map_err(|e| e.to_string())
}
fn run() -> Result<(), String> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if let [command, seed_file] = args.as_slice()
        && command == "public-key"
    {
        println!(
            "{}",
            STANDARD.encode(seed(seed_file)?.verifying_key().as_bytes())
        );
        return Ok(());
    }
    if args.len() != 3 {
        return Err("Usage: installer_release VERSION ASSET-DIRECTORY BASE64-SEED-FILE | installer_release public-key BASE64-SEED-FILE".into());
    }
    let key = seed(&args[2])?;
    let bytes = manifest(&args[0], Path::new(&args[1]))?;
    let signature = STANDARD.encode(key.sign(&bytes).to_bytes());
    std::fs::write(Path::new(&args[1]).join("installer-update.json"), bytes)
        .map_err(|e| e.to_string())?;
    std::fs::write(
        Path::new(&args[1]).join("installer-update.json.sig"),
        signature,
    )
    .map_err(|e| e.to_string())?;
    println!(
        "Public key for INSTALLER_UPDATE_PUBLIC_KEY: {}",
        STANDARD.encode(key.verifying_key().as_bytes())
    );
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn every_target_names_its_public_download() {
        assert_eq!(
            super::asset_name("linux-x86_64"),
            "Strahlender-Installer-x86_64.AppImage"
        );
        assert_eq!(
            super::asset_name("linux-aarch64"),
            "Strahlender-Installer-aarch64.AppImage"
        );
        assert_eq!(
            super::asset_name("windows-x86_64"),
            "installer-windows-x86_64.zip"
        );
        assert_eq!(
            super::asset_name("macos-x86_64"),
            "installer-macos-universal.zip"
        );
        // The release publishes exactly these names (installer/scripts/release.py PACKAGES).
    }

    #[test]
    fn one_universal_zip_serves_both_mac_update_targets() {
        let folder =
            std::env::temp_dir().join(format!("universal-manifest-test-{}", std::process::id()));
        std::fs::create_dir(&folder).unwrap();
        std::fs::write(folder.join("installer-macos-universal.zip"), b"fixture").unwrap();
        let manifest: serde_json::Value =
            serde_json::from_slice(&super::manifest("0.2.0", &folder).unwrap()).unwrap();
        let assets = manifest["assets"].as_array().unwrap();
        assert_eq!(assets.len(), 2);
        assert_eq!(assets[0]["target"], "macos-aarch64");
        assert_eq!(assets[1]["target"], "macos-x86_64");
        for asset in assets {
            assert_eq!(asset["name"], "installer-macos-universal.zip");
        }
        assert_eq!(assets[0]["sha256"], assets[1]["sha256"]);
        std::fs::remove_dir_all(folder).unwrap();
    }
}
