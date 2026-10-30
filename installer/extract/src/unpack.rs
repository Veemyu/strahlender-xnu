//! `--cli unpack ARCHIVE DESTINATION`: safe extraction of the upstream archives the Windows setup downloads
//! (.zip, .tar.gz, .7z). Python cannot read 7z, so the build scripts call this executable instead.
use std::fs;
use std::io::{self, Read};
use std::path::{Component, Path, PathBuf};

const MAX_UNPACKED: u64 = 6 << 30;

fn target(destination: &Path, name: &str) -> Result<PathBuf, String> {
    let relative = Path::new(name);
    if relative.as_os_str().is_empty()
        || relative
            .components()
            .any(|c| !matches!(c, Component::Normal(_) | Component::CurDir))
    {
        return Err(format!("The archive contains an unsafe path: {name}"));
    }
    Ok(destination.join(relative))
}

fn write(
    path: &Path,
    reader: &mut dyn Read,
    total: &mut u64,
    size_hint: u64,
) -> Result<(), String> {
    *total += size_hint;
    if *total > MAX_UNPACKED {
        return Err("The archive is larger than expected.".into());
    }
    fs::create_dir_all(path.parent().ok_or("Invalid path")?).map_err(|e| e.to_string())?;
    let mut file = fs::File::create(path).map_err(|e| e.to_string())?;
    io::copy(reader, &mut file)
        .map(|_| ())
        .map_err(|e| e.to_string())
}

pub fn unpack(archive: &Path, destination: &Path) -> Result<(), String> {
    fs::create_dir_all(destination).map_err(|e| e.to_string())?;
    let name = archive
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    let file = fs::File::open(archive).map_err(|e| format!("{}: {e}", archive.display()))?;
    let mut total = 0u64;
    if name.ends_with(".zip") {
        let mut zip = zip::ZipArchive::new(file).map_err(|e| e.to_string())?;
        for index in 0..zip.len() {
            let mut entry = zip.by_index(index).map_err(|e| e.to_string())?;
            if entry.unix_mode().is_some_and(|m| m & 0o170000 == 0o120000) {
                return Err("The archive contains a symbolic link.".into());
            }
            let path = target(destination, entry.name())?;
            if entry.is_dir() {
                fs::create_dir_all(&path).map_err(|e| e.to_string())?;
            } else {
                let size = entry.size();
                write(&path, &mut entry, &mut total, size)?;
            }
        }
    } else if name.ends_with(".tar.gz") || name.ends_with(".tgz") {
        let mut tar = tar::Archive::new(flate2::read::GzDecoder::new(file));
        for entry in tar.entries().map_err(|e| e.to_string())? {
            let mut entry = entry.map_err(|e| e.to_string())?;
            let kind = entry.header().entry_type();
            let path = target(
                destination,
                &entry.path().map_err(|e| e.to_string())?.to_string_lossy(),
            )?;
            if kind.is_dir() {
                fs::create_dir_all(&path).map_err(|e| e.to_string())?;
            } else if kind.is_file() {
                let size = entry.size();
                write(&path, &mut entry, &mut total, size)?;
            } else if !kind.is_pax_global_extensions() && !kind.is_pax_local_extensions() {
                return Err("The archive contains a link or special file.".into());
            }
        }
    } else if name.ends_with(".7z") {
        let mut reader = sevenz_rust2::ArchiveReader::new(file, sevenz_rust2::Password::empty())
            .map_err(|e| e.to_string())?;
        let mut failure = None;
        reader
            .for_each_entries(|entry, data| {
                if entry.name().is_empty() {
                    return Ok(true); // the archive's root directory
                }
                let result = target(destination, entry.name()).and_then(|path| {
                    if entry.is_directory() {
                        fs::create_dir_all(&path).map_err(|e| e.to_string())
                    } else if entry.is_anti_item() {
                        Ok(())
                    } else {
                        write(&path, data, &mut total, entry.size())
                    }
                });
                match result {
                    Ok(()) => Ok(true),
                    Err(error) => {
                        failure = Some(error);
                        Ok(false)
                    }
                }
            })
            .map_err(|e| e.to_string())?;
        if let Some(error) = failure {
            return Err(error);
        }
    } else {
        return Err("Unknown archive type (expected .zip, .tar.gz or .7z).".into());
    }
    Ok(())
}

/// `unpack ARCHIVE DESTINATION`; returns the process exit code.
pub fn cli(args: &[std::ffi::OsString]) -> i32 {
    let [archive, destination] = args else {
        eprintln!("Usage: --cli unpack ARCHIVE DESTINATION");
        return 2;
    };
    match unpack(Path::new(archive), Path::new(destination)) {
        Ok(()) => 0,
        Err(error) => {
            eprintln!("unpack failed: {error}");
            1
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn dir(name: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!("bdsp-unpack-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).unwrap();
        path
    }

    #[test]
    fn zip_and_tar_gz_unpack_and_reject_traversal() {
        let root = dir("zip");
        let zip_path = root.join("a.zip");
        let mut writer = zip::ZipWriter::new(fs::File::create(&zip_path).unwrap());
        writer
            .start_file("sub/hello.txt", zip::write::SimpleFileOptions::default())
            .unwrap();
        writer.write_all(b"hi").unwrap();
        writer.finish().unwrap();
        unpack(&zip_path, &root.join("out")).unwrap();
        assert_eq!(fs::read(root.join("out/sub/hello.txt")).unwrap(), b"hi");

        let tgz = root.join("a.tar.gz");
        let encoder = flate2::write::GzEncoder::new(
            fs::File::create(&tgz).unwrap(),
            flate2::Compression::fast(),
        );
        let mut builder = tar::Builder::new(encoder);
        let mut header = tar::Header::new_gnu();
        header.set_size(2);
        header.set_cksum();
        builder
            .append_data(&mut header, "pkg/x.txt", &b"ok"[..])
            .unwrap();
        builder.into_inner().unwrap().finish().unwrap();
        unpack(&tgz, &root.join("out2")).unwrap();
        assert_eq!(fs::read(root.join("out2/pkg/x.txt")).unwrap(), b"ok");

        assert!(target(&root, "../evil").is_err());
        assert!(target(&root, "/abs").is_err());
        assert!(unpack(&root.join("a.txt"), &root.join("o")).is_err());
    }

    #[test]
    fn seven_zip_unpacks() {
        let root = dir("7z");
        let source = root.join("src");
        fs::create_dir_all(source.join("d")).unwrap();
        fs::write(source.join("d/f.txt"), b"seven").unwrap();
        let archive = root.join("a.7z");
        sevenz_rust2::compress_to_path(&source, &archive).unwrap();
        unpack(&archive, &root.join("out")).unwrap();
        assert_eq!(fs::read(root.join("out/d/f.txt")).unwrap(), b"seven");
    }
}
