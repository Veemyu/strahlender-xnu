//! Only the live owner of a downloaded per-run workspace can retire it.
//! There is intentionally no recursive search for historical or developer folders.
use std::{
    fs,
    io::{Read, Write},
    path::{Path, PathBuf},
};

pub struct OwnedWorkspace {
    root: PathBuf,
    parent: PathBuf,
    receipt: String,
}

impl OwnedWorkspace {
    pub fn register(root: &Path, parent: &Path) -> Result<Self, String> {
        let parent = parent.canonicalize().map_err(|e| e.to_string())?;
        let root = root.canonicalize().map_err(|e| e.to_string())?;
        if root.parent() != Some(parent.as_path()) || root.join(".git").exists() {
            return Err("This is not an isolated installer workspace.".into());
        }
        let receipt = format!(
            "installer-workspace-v1\n{}\n{}\n",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_err(|e| e.to_string())?
                .as_nanos()
        );
        let mut marker = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(root.join(".installer-workspace-owner"))
            .map_err(|e| e.to_string())?;
        marker
            .write_all(receipt.as_bytes())
            .map_err(|e| e.to_string())?;
        Ok(Self {
            root,
            parent,
            receipt,
        })
    }

    fn validate(&self) -> Result<(), String> {
        let metadata = fs::symlink_metadata(&self.root).map_err(|e| e.to_string())?;
        let marker = self.root.join(".installer-workspace-owner");
        if metadata.file_type().is_symlink()
            || !metadata.is_dir()
            || self.root.canonicalize().map_err(|e| e.to_string())? != self.root
            || self.root.parent() != Some(self.parent.as_path())
            || self.parent.canonicalize().map_err(|e| e.to_string())? != self.parent
            || self.root.join(".git").exists()
            || fs::symlink_metadata(&marker)
                .map_err(|e| e.to_string())?
                .file_type()
                .is_symlink()
            || fs::read_to_string(marker).map_err(|e| e.to_string())? != self.receipt
        {
            return Err("Workspace ownership changed; temporary files were kept.".into());
        }
        Ok(())
    }

    pub fn export_ipa(&self, source: &Path) -> Result<PathBuf, String> {
        self.validate()?;
        let source = source.canonicalize().map_err(|e| e.to_string())?;
        if !source.starts_with(&self.root)
            || source.extension().is_none_or(|e| e != "ipa")
            || !source.is_file()
        {
            return Err("The device package is not inside this build workspace.".into());
        }
        let folder = self
            .parent
            .parent()
            .ok_or("Missing installer data directory")?
            .join("exports");
        fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
        if fs::symlink_metadata(&folder)
            .map_err(|e| e.to_string())?
            .file_type()
            .is_symlink()
        {
            return Err("The export folder is a symbolic link; the workspace was kept.".into());
        }
        let destination = folder
            .join(self.root.file_name().ok_or("Missing build identity")?)
            .with_extension("ipa");
        let mut output = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&destination)
            .map_err(|e| e.to_string())?;
        let result =
            fs::File::open(source).and_then(|mut input| std::io::copy(&mut input, &mut output));
        if let Err(error) = result {
            let _ = fs::remove_file(&destination);
            return Err(error.to_string());
        }
        Ok(destination)
    }

    pub fn finish(self, installed: &Path) -> Result<(), String> {
        self.validate()?;
        // A local output or symlink into the workspace is not an installation.
        let installed = installed.canonicalize().map_err(|e| e.to_string())?;
        if installed.starts_with(&self.root) {
            return Err("The installed application still depends on the workspace.".into());
        }
        self.check_installed_links(&installed)?;
        self.preserve_diagnostics()?;
        self.validate()?;
        fs::remove_dir_all(&self.root).map_err(|e| e.to_string())
    }

    fn check_installed_links(&self, installed: &Path) -> Result<(), String> {
        if !installed.is_dir() {
            return Ok(());
        }
        let mut pending = vec![installed.to_path_buf()];
        while let Some(directory) = pending.pop() {
            for entry in fs::read_dir(directory).map_err(|e| e.to_string())? {
                let path = entry.map_err(|e| e.to_string())?.path();
                let metadata = fs::symlink_metadata(&path).map_err(|e| e.to_string())?;
                if metadata.file_type().is_symlink() {
                    if path
                        .canonicalize()
                        .is_ok_and(|target| target.starts_with(&self.root))
                    {
                        return Err(
                            "An installed resource still points into the build workspace.".into(),
                        );
                    }
                } else if metadata.is_dir() {
                    pending.push(path);
                }
            }
        }
        Ok(())
    }

    fn preserve_diagnostics(&self) -> Result<(), String> {
        let folder = self
            .parent
            .parent()
            .ok_or("Missing installer data directory")?
            .join("diagnostics");
        fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
        if fs::symlink_metadata(&folder)
            .map_err(|e| e.to_string())?
            .file_type()
            .is_symlink()
        {
            return Err("Diagnostics folder is a symbolic link; temporary files were kept.".into());
        }
        for name in [
            "recomp-compile.log",
            "recomp-images.log",
            "recomp-runtime.log",
        ] {
            let source = self.root.join("work/logs").join(name);
            if !source.is_file() {
                continue;
            }
            let resolved = source.canonicalize().map_err(|e| e.to_string())?;
            if !resolved.starts_with(&self.root) {
                return Err("A build log points outside the workspace.".into());
            }
            let mut bytes = Vec::new();
            fs::File::open(source)
                .map_err(|e| e.to_string())?
                .take(256 * 1024)
                .read_to_end(&mut bytes)
                .map_err(|e| e.to_string())?;
            let mut text = String::from_utf8_lossy(&bytes)
                .replace(self.root.to_string_lossy().as_ref(), "<project>");
            if let Some(dirs) = directories::UserDirs::new() {
                text = text.replace(dirs.home_dir().to_string_lossy().as_ref(), "~");
            }
            // Fixed bounded diagnostic files, never a growing archive of old runs.
            let temporary = folder.join(format!(".last-{name}-{}", std::process::id()));
            let mut output = fs::OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(&temporary)
                .map_err(|e| e.to_string())?;
            output
                .write_all(text.as_bytes())
                .map_err(|e| e.to_string())?;
            drop(output);
            if let Err(error) = fs::rename(&temporary, folder.join(format!("last-{name}"))) {
                let _ = fs::remove_file(temporary);
                return Err(error.to_string());
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let unique = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            let root = std::env::temp_dir()
                .join(format!("installer-cleanup-{}-{unique}", std::process::id()));
            fs::create_dir_all(root.join("sources/run/work/logs")).unwrap();
            Self(root.canonicalize().unwrap())
        }
        fn owner(&self) -> OwnedWorkspace {
            OwnedWorkspace::register(&self.0.join("sources/run"), &self.0.join("sources")).unwrap()
        }
        fn installed(&self) -> PathBuf {
            let path = self.0.join("installed/BDSP.app");
            fs::create_dir_all(&path).unwrap();
            path
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn cleanup_keeps_installed_data_originals_and_bounded_diagnostics() {
        let fixture = Fixture::new();
        let owner = fixture.owner();
        let installed = fixture.installed();
        for name in ["prod.keys", "game.xci", "update.nsp", "save", "mod"] {
            fs::write(fixture.0.join(name), name).unwrap();
        }
        let source = owner.root.join("work/logs/recomp-compile.log");
        fs::write(&source, format!("compile {}", owner.root.display())).unwrap();
        owner.finish(&installed).unwrap();
        assert!(!fixture.0.join("sources/run").exists());
        assert!(installed.is_dir());
        for name in ["prod.keys", "game.xci", "update.nsp", "save", "mod"] {
            assert_eq!(fs::read_to_string(fixture.0.join(name)).unwrap(), name);
        }
        assert_eq!(
            fs::read_to_string(fixture.0.join("diagnostics/last-recomp-compile.log")).unwrap(),
            "compile <project>"
        );
    }

    #[test]
    fn cleanup_requires_the_live_receipt_and_an_external_installation() {
        let fixture = Fixture::new();
        let owner = fixture.owner();
        fs::write(
            owner.root.join(".installer-workspace-owner"),
            "different run",
        )
        .unwrap();
        assert!(owner.finish(&fixture.installed()).is_err());
        assert!(fixture.0.join("sources/run").is_dir());
        let fixture = Fixture::new();
        let owner = fixture.owner();
        let output = owner.root.join("BDSP.app");
        fs::create_dir(&output).unwrap();
        assert!(owner.finish(&output).is_err());
        assert!(output.is_dir());
    }

    #[test]
    fn developer_checkouts_and_missing_installations_are_kept() {
        let fixture = Fixture::new();
        fs::create_dir(fixture.0.join("sources/run/.git")).unwrap();
        assert!(
            OwnedWorkspace::register(&fixture.0.join("sources/run"), &fixture.0.join("sources"))
                .is_err()
        );
        let fixture = Fixture::new();
        let owner = fixture.owner();
        assert!(owner.finish(&fixture.0.join("missing.app")).is_err());
        assert!(fixture.0.join("sources/run").exists());
    }

    #[cfg(unix)]
    #[test]
    fn cleanup_refuses_replaced_roots_and_does_not_follow_data_links() {
        let fixture = Fixture::new();
        let owner = fixture.owner();
        let outside = fixture.0.join("original-data");
        fs::create_dir(&outside).unwrap();
        fs::write(outside.join("save"), "original").unwrap();
        std::os::unix::fs::symlink(&outside, owner.root.join("romfs")).unwrap();
        owner.finish(&fixture.installed()).unwrap();
        assert_eq!(
            fs::read_to_string(outside.join("save")).unwrap(),
            "original"
        );
        let fixture = Fixture::new();
        let owner = fixture.owner();
        fs::rename(&owner.root, fixture.0.join("held")).unwrap();
        std::os::unix::fs::symlink(fixture.installed(), &owner.root).unwrap();
        assert!(owner.finish(&fixture.installed()).is_err());
        assert!(fixture.0.join("held").is_dir());
    }

    #[cfg(unix)]
    #[test]
    fn installed_resource_links_into_workspace_block_cleanup() {
        let fixture = Fixture::new();
        let owner = fixture.owner();
        let installed = fixture.installed();
        fs::write(owner.root.join("image"), "data").unwrap();
        std::os::unix::fs::symlink(owner.root.join("image"), installed.join("image")).unwrap();
        assert!(owner.finish(&installed).is_err());
        assert!(fixture.0.join("sources/run/image").is_file());
    }

    #[test]
    fn device_package_is_exported_before_workspace_removal() {
        let fixture = Fixture::new();
        let owner = fixture.owner();
        let package = owner.root.join("BDSP.ipa");
        fs::write(&package, "signed package").unwrap();
        let exported = owner.export_ipa(&package).unwrap();
        assert!(owner.export_ipa(&fixture.0.join("missing.ipa")).is_err());
        owner.finish(&exported).unwrap();
        assert_eq!(fs::read_to_string(exported).unwrap(), "signed package");
    }
}
