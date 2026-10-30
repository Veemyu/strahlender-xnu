//! Locating the source checkout and the private Python runtime. Shared by the GUI and the `installer_setup` binary.
use std::path::{Path, PathBuf};

pub fn project_root() -> Option<PathBuf> {
    let starts = vec![std::env::current_dir().ok()?, std::env::current_exe().ok()?];
    #[cfg(debug_assertions)]
    let mut starts = starts;
    #[cfg(debug_assertions)]
    if let Some(manifest) = option_env!("CARGO_MANIFEST_DIR") {
        starts.push(PathBuf::from(manifest));
    }
    starts.into_iter().find_map(|start| find_root_from(&start))
}

pub fn host_target() -> Option<&'static str> {
    match (std::env::consts::OS, std::env::consts::ARCH) {
        ("macos", "aarch64") => Some("macos-aarch64"),
        ("macos", "x86_64") => Some("macos-x86_64"),
        ("linux", "aarch64") => Some("linux-aarch64"),
        ("linux", "x86_64") => Some("linux-x86_64"),
        ("windows", "aarch64") => Some("windows-aarch64"),
        ("windows", "x86_64") => Some("windows-x86_64"),
        _ => None,
    }
}

pub fn verified_runtime_python(runtime: &Path) -> Option<PathBuf> {
    let marker: serde_json::Value =
        serde_json::from_slice(&std::fs::read(runtime.join("runtime.json")).ok()?).ok()?;
    if marker.get("schema")?.as_u64()? != 1
        || marker.get("target")?.as_str()? != host_target()?
        || marker.get("python")?.as_str()? != "3.13.15"
    {
        return None;
    }
    if cfg!(windows) && !runtime_inventory_matches(runtime, marker.get("files")?) {
        return None;
    }
    let executable = if cfg!(windows) {
        runtime.join("python/python.exe")
    } else {
        runtime.join("python/bin/python3")
    };
    executable.is_file().then_some(executable)
}

pub fn runtime_inventory_matches(runtime: &Path, record: &serde_json::Value) -> bool {
    use std::collections::BTreeSet;

    fn regular_tree(root: &Path, files: &mut BTreeSet<PathBuf>) -> std::io::Result<()> {
        let metadata = std::fs::symlink_metadata(root)?;
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            if metadata.file_attributes() & 0x400 != 0 {
                return Err(std::io::Error::other("Runtime contains a reparse point"));
            }
        }
        if metadata.file_type().is_symlink() {
            return Err(std::io::Error::other("Runtime contains a link"));
        }
        if metadata.is_file() {
            files.insert(root.to_path_buf());
        } else if metadata.is_dir() {
            for entry in std::fs::read_dir(root)? {
                regular_tree(&entry?.path(), files)?;
            }
        } else {
            return Err(std::io::Error::other("Runtime contains a non-regular file"));
        }
        Ok(())
    }

    let Some(expected) = record.as_object().filter(|files| !files.is_empty()) else {
        return false;
    };
    let mut actual = BTreeSet::new();
    if regular_tree(runtime, &mut actual).is_err() {
        return false;
    }
    actual.remove(&runtime.join("runtime.json"));
    if actual.len() != expected.len() {
        return false;
    }
    for (name, digest) in expected {
        if name
            .split('/')
            .any(|part| part.is_empty() || part == "." || part == "..")
            || name.contains(['\\', ':'])
        {
            return false;
        }
        let path = runtime.join(name);
        if !actual.remove(&path) {
            return false;
        }
        if bdsp_extract::manifest::file_sha256(&path).ok().as_deref() != digest.as_str() {
            return false;
        }
    }
    actual.is_empty()
}

pub fn bundled_runtime() -> Option<PathBuf> {
    let executable = std::env::current_exe().ok()?;
    runtime_beside_executable(&executable)
}

pub fn runtime_beside_executable(executable: &Path) -> Option<PathBuf> {
    let parent = executable.parent()?;
    if cfg!(target_os = "windows") {
        runtime_in_resources(&parent.join("resources"))
    } else {
        runtime_in_resources(&parent.parent()?.join("Resources"))
    }
}

pub fn runtime_in_resources(resources: &Path) -> Option<PathBuf> {
    let runtime = resources.join("runtime");
    if let Some(host) = host_target()
        && let Some(python) = verified_runtime_python(&runtime.join(host))
    {
        return Some(python);
    }
    // Existing single-architecture Mac bundles and Linux AppImages.
    verified_runtime_python(&runtime)
}

pub fn backend_python() -> Option<(PathBuf, bool)> {
    if let Some(runtime) = std::env::var_os("BDSP_INSTALLER_RUNTIME") {
        return verified_runtime_python(Path::new(&runtime)).map(|python| (python, true));
    }

    if let Some(python) = bundled_runtime() {
        return Some((python, true));
    }
    if let Some(dirs) = directories::ProjectDirs::from("dev", "Veemyu", "strahlender-xnu-installer")
        && let Some(target) = host_target()
        && let Some(python) =
            verified_runtime_python(&dirs.data_dir().join("runtimes/3.13.15").join(target))
    {
        return Some((python, true));
    }
    cfg!(debug_assertions).then(|| {
        (
            PathBuf::from(if cfg!(target_os = "windows") {
                "python"
            } else {
                "python3"
            }),
            false,
        )
    })
}

pub fn runtime_smoke() -> Result<(), String> {
    let (python, private) = backend_python().ok_or("The bundled Python runtime is missing.")?;
    if !private {
        return Err("Runtime smoke checks require private Python.".into());
    }
    let status = std::process::Command::new(python)
        .args([
            "-I",
            "-B",
            "-c",
            concat!(
                include_str!("../runtime/native_smoke.py"),
                "\nimport UnityPy, UnityPy.UnityPyBoost\n"
            ),
        ])
        .status()
        .map_err(|e| e.to_string())?;
    if status.success() {
        Ok(())
    } else {
        Err("Private runtime smoke check failed.".into())
    }
}

pub fn find_root_from(start: &Path) -> Option<PathBuf> {
    let mut current = if start.is_file() {
        start.parent()?.to_path_buf()
    } else {
        start.to_path_buf()
    };
    loop {
        if current.join("scripts/install/driver.py").is_file()
            && current.join("scripts/build_stages.py").is_file()
        {
            return Some(current);
        }
        if !current.pop() {
            return None;
        }
    }
}
