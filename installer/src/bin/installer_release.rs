//! Offline release metadata signing. No upload or release publication happens here.
use base64::{Engine, engine::general_purpose::STANDARD};
use ed25519_dalek::{Signer, SigningKey};
use sha2::{Digest, Sha256};
use std::{io::Read, path::Path};

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
    ] {
        let name = format!(
            "installer-{host}.{}",
            if host.starts_with("macos") {
                "tar.gz"
            } else {
                "AppImage"
            }
        );
        let path = folder.join(&name);
        if !path.is_file() {
            continue;
        }
        let mut file = std::fs::File::open(path).map_err(|e| e.to_string())?;
        let mut hash = Sha256::new();
        let mut buffer = [0_u8; 65536];
        loop {
            let n = file.read(&mut buffer).map_err(|e| e.to_string())?;
            if n == 0 {
                break;
            }
            hash.update(&buffer[..n]);
        }
        assets.push(
            serde_json::json!({"target":host,"name":name,"sha256":format!("{:x}",hash.finalize())}),
        );
    }
    if assets.is_empty() {
        return Err("No installer release assets found.".into());
    }
    serde_json::to_vec_pretty(&serde_json::json!({"version":version,"assets":assets}))
        .map_err(|e| e.to_string())
}
fn run() -> Result<(), String> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 3 {
        return Err("Usage: installer_release VERSION ASSET-DIRECTORY BASE64-SEED-FILE".into());
    }
    let key_bytes = std::fs::read_to_string(&args[2]).map_err(|e| e.to_string())?;
    let seed: [u8; 32] = STANDARD
        .decode(key_bytes.trim())
        .map_err(|e| e.to_string())?
        .try_into()
        .map_err(|_| "Expected a base64-encoded 32-byte Ed25519 seed.")?;
    let key = SigningKey::from_bytes(&seed);
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
