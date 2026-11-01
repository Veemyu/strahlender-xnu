//! The Windows installer is one .exe. Its resources (private Python, build tools, helper programs, licences) are a ZIP
//! appended to the executable, closed by a trailer: MAGIC, ZIP length (u64, little endian), SHA-256 of the ZIP. The first
//! start unpacks the ZIP next to the other installer data; later starts find it again by its checksum.
//! Everywhere else, and for the helpers inside the unpacked folder, the folder with `resources/` beside the executable is used.
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::{Cursor, Read, Seek, SeekFrom},
    path::{Path, PathBuf},
};

pub const MAGIC: &[u8; 8] = b"BDSPBNDL";
const TRAILER: u64 = 8 + 8 + 32;
const DONE: &str = ".complete";

/// The folder holding `resources/` and the helper programs of this installer.
pub fn dir() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let beside = exe.parent()?;
    if beside.join("resources").is_dir() {
        return Some(beside.to_path_buf());
    }
    let data = directories::ProjectDirs::from("dev", "Veemyu", "strahlender-xnu-installer")?;
    unpacked(&exe, &data.data_dir().join("bundle")).ok().flatten()
}

#[allow(dead_code)] // the installer_setup binary shares this module but starts no helper
/// A helper program (`ips_patch`, `firmware_import`, `installer_update`) of the installer.
pub fn helper(name: &str) -> Option<PathBuf> {
    let file = format!("{name}{}", std::env::consts::EXE_SUFFIX);
    let path = dir()?.join(&file);
    path.is_file().then_some(path)
}

/// Unpacks the ZIP appended to `exe` below `root` (once) and returns the folder; `None` if `exe` carries no bundle.
pub fn unpacked(exe: &Path, root: &Path) -> Result<Option<PathBuf>, String> {
    let Some((offset, length, sha)) = trailer(exe)? else {
        return Ok(None);
    };
    let name: String = sha.iter().take(8).map(|b| format!("{b:02x}")).collect();
    let target = root.join(&name);
    if target.join(DONE).is_file() {
        return Ok(Some(target));
    }
    let mut file = fs::File::open(exe).map_err(|e| e.to_string())?;
    file.seek(SeekFrom::Start(offset)).map_err(|e| e.to_string())?;
    let mut bytes = vec![0u8; length as usize];
    file.read_exact(&mut bytes).map_err(|e| e.to_string())?;
    if Sha256::digest(&bytes).as_slice() != sha {
        return Err("The installer file is damaged. Download it again.".into());
    }
    fs::create_dir_all(root).map_err(|e| e.to_string())?;
    let partial = root.join(format!("{name}.partial-{}", std::process::id()));
    let _ = fs::remove_dir_all(&partial);
    zip::ZipArchive::new(Cursor::new(bytes))
        .and_then(|mut archive| archive.extract(&partial))
        .map_err(|e| format!("The installer files could not be unpacked: {e}"))?;
    fs::write(partial.join(DONE), b"").map_err(|e| e.to_string())?;
    if fs::rename(&partial, &target).is_err() {
        // Another start was faster; keep its result.
        let _ = fs::remove_dir_all(&partial);
        if !target.join(DONE).is_file() {
            return Err("The installer files could not be put in place.".into());
        }
    }
    prune(root, &name);
    Ok(Some(target))
}

fn prune(root: &Path, keep: &str) {
    if let Ok(entries) = fs::read_dir(root) {
        for entry in entries.flatten() {
            if entry.file_name() != keep && entry.path().is_dir() {
                let _ = fs::remove_dir_all(entry.path());
            }
        }
    }
}

/// (offset, length, checksum) of the appended ZIP.
fn trailer(exe: &Path) -> Result<Option<(u64, u64, [u8; 32])>, String> {
    let mut file = fs::File::open(exe).map_err(|e| e.to_string())?;
    let size = file.metadata().map_err(|e| e.to_string())?.len();
    if size < TRAILER {
        return Ok(None);
    }
    file.seek(SeekFrom::Start(size - TRAILER)).map_err(|e| e.to_string())?;
    let mut tail = [0u8; TRAILER as usize];
    file.read_exact(&mut tail).map_err(|e| e.to_string())?;
    if &tail[..8] != MAGIC {
        return Ok(None);
    }
    let length = u64::from_le_bytes(tail[8..16].try_into().unwrap());
    if length == 0 || length > size - TRAILER {
        return Err("The installer file is damaged. Download it again.".into());
    }
    let mut sha = [0u8; 32];
    sha.copy_from_slice(&tail[16..]);
    Ok(Some((size - TRAILER - length, length, sha)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("bdsp-bundle-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn archive() -> Vec<u8> {
        let mut out = Cursor::new(Vec::new());
        let mut zipped = zip::ZipWriter::new(&mut out);
        zipped.start_file("resources/a.txt", zip::write::SimpleFileOptions::default()).unwrap();
        zipped.write_all(b"hello").unwrap();
        zipped.finish().unwrap();
        out.into_inner()
    }

    fn with_bundle(path: &Path, zip: &[u8], sha: [u8; 32]) {
        let mut exe = b"MZ program bytes".to_vec();
        exe.extend_from_slice(zip);
        exe.extend_from_slice(MAGIC);
        exe.extend_from_slice(&(zip.len() as u64).to_le_bytes());
        exe.extend_from_slice(&sha);
        fs::write(path, exe).unwrap();
    }

    #[test]
    fn unpacks_once_and_reuses_the_folder() {
        let dir = scratch("once");
        let zip = archive();
        let exe = dir.join("installer.exe");
        with_bundle(&exe, &zip, Sha256::digest(&zip).into());
        let first = unpacked(&exe, &dir.join("bundle")).unwrap().unwrap();
        assert_eq!(fs::read(first.join("resources/a.txt")).unwrap(), b"hello");
        fs::write(first.join("resources/a.txt"), b"kept").unwrap();
        assert_eq!(unpacked(&exe, &dir.join("bundle")).unwrap(), Some(first.clone()));
        assert_eq!(fs::read(first.join("resources/a.txt")).unwrap(), b"kept");
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn an_older_folder_is_removed_when_a_new_bundle_arrives() {
        let dir = scratch("prune");
        let root = dir.join("bundle");
        fs::create_dir_all(root.join("oldoldol")).unwrap();
        let zip = archive();
        let exe = dir.join("installer.exe");
        with_bundle(&exe, &zip, Sha256::digest(&zip).into());
        unpacked(&exe, &root).unwrap().unwrap();
        assert!(!root.join("oldoldol").exists());
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_damaged_or_plain_executable_is_not_unpacked() {
        let dir = scratch("damaged");
        let zip = archive();
        let bad = dir.join("bad.exe");
        with_bundle(&bad, &zip, [7; 32]);
        assert!(unpacked(&bad, &dir.join("bundle")).is_err());
        let plain = dir.join("plain.exe");
        fs::write(&plain, b"MZ no bundle at all, just a program of some size......").unwrap();
        assert_eq!(unpacked(&plain, &dir.join("bundle")).unwrap(), None);
        let cut = dir.join("cut.exe");
        let mut bytes = Vec::from(MAGIC.as_slice());
        bytes.extend_from_slice(&u64::MAX.to_le_bytes());
        bytes.extend_from_slice(&[0; 32]);
        fs::write(&cut, bytes).unwrap();
        assert!(unpacked(&cut, &dir.join("bundle")).is_err());
        let _ = fs::remove_dir_all(&dir);
    }
}
