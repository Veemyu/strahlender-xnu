//! Facts about the machine for the top of the session log, so a later failure arrives with its platform data. Nothing here
//! contains key material, and the callers redact the home directory. The probes run in `blocking()` tasks, never on the UI thread.
use crate::process::Hidden;
use std::{
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

/// The cheap facts that need no probe: written synchronously when the window starts, before any step.
pub fn header(
    host: &str,
    target: &str,
    language: &str,
    data_folder: Option<&Path>,
    log_file: Option<&str>,
) -> Vec<String> {
    vec![
        format!(
            "Installer {} ({} {}, {} build)",
            env!("CARGO_PKG_VERSION"),
            std::env::consts::OS,
            std::env::consts::ARCH,
            if cfg!(debug_assertions) {
                "debug"
            } else {
                "release"
            }
        ),
        format!("Host platform: {host}; selected target: {target}; language: {language}"),
        format!(
            "Data folder: {}; log file: {}",
            data_folder.map_or_else(|| "unavailable".into(), |p| p.display().to_string()),
            log_file.unwrap_or("not written")
        ),
    ]
}

pub fn gib(bytes: u64) -> String {
    format!("{:.1} GB", bytes as f64 / (1u64 << 30) as f64)
}

/// The slow facts: operating system, memory, graphics, disks, tools, the Windows components. Each entry is (log step, message).
pub fn probe(target: &str, data: Option<PathBuf>) -> Vec<(&'static str, String)> {
    let mut lines = Vec::new();
    let windows = cfg!(target_os = "windows");
    let (mut os, mut ram, mut gpus) = if windows {
        parse_windows_probe(&windows_probe())
    } else {
        (None, None, Vec::new())
    };
    if !windows {
        os = unix_os();
        ram = unix_ram();
        gpus = unix_gpus();
    }
    lines.push((
        "SYSTEM",
        format!(
            "Operating system: {}; architecture: {}",
            os.unwrap_or_else(|| format!("{} (version unavailable)", std::env::consts::OS)),
            std::env::consts::ARCH
        ),
    ));
    lines.push((
        "SYSTEM",
        format!("Memory: {}", ram.map_or_else(|| "unavailable".into(), gib)),
    ));
    lines.push((
        "SYSTEM",
        if gpus.is_empty() {
            "Graphics adapters: unavailable".into()
        } else {
            format!("Graphics adapters: {}", gpus.join("; "))
        },
    ));
    let free = |path: Option<&Path>| {
        path.and_then(free_bytes)
            .map_or_else(|| "unavailable".into(), gib)
    };
    let install = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(Path::to_path_buf));
    lines.push((
        "SYSTEM",
        format!(
            "Free disk space: data volume {}; install volume {}",
            free(data.as_deref()),
            free(install.as_deref())
        ),
    ));
    lines.push(("SYSTEM", tools_line(target)));
    if windows {
        lines.push(("SYSTEM", components_line()));
        lines.extend(
            diagnostics(data.as_deref())
                .into_iter()
                .map(|line| ("Diagnostics", line)),
        );
    }
    lines
}

fn tools_line(target: &str) -> String {
    match crate::dependencies::inspect(target) {
        Ok(plan) if plan.ready() => "Tools: all required tools found".into(),
        Ok(plan) => format!("Tools: {}", plan.log_lines().join(" | ")),
        Err(error) => format!("Tools: check unavailable ({error})"),
    }
}

fn components_line() -> String {
    let installed = crate::components::root()
        .ok()
        .and_then(|root| crate::components::installed(&root));
    match installed {
        Some(meta) => format!(
            "Windows components: installed, archive {}, created {}",
            meta.sha256.get(..12).unwrap_or(&meta.sha256),
            meta.created
        ),
        None => "Windows components: not installed".into(),
    }
}

/// The report of scripts/install/diagnostics.py (GPU, Vulkan, Defender, tools), when the script and a Python are at hand.
fn diagnostics(work: Option<&Path>) -> Vec<String> {
    let Some(script) = crate::runtime::project_root()
        .map(|root| root.join("scripts/install/diagnostics.py"))
        .filter(|script| script.is_file())
    else {
        return Vec::new();
    };
    let Some((python, _)) = crate::runtime::backend_python() else {
        return Vec::new();
    };
    let mut command = Command::new(python);
    command.hidden().arg(script);
    if let Some(work) = work {
        command.arg("--work").arg(work);
    }
    let Ok(output) = command.stdin(Stdio::null()).stderr(Stdio::null()).output() else {
        return Vec::new();
    };
    diagnostic_lines(&String::from_utf8_lossy(&output.stdout))
}

fn diagnostic_lines(text: &str) -> Vec<String> {
    text.lines()
        .filter_map(|line| line.trim().strip_prefix("[Diagnostics]"))
        .map(|line| line.trim().to_owned())
        .filter(|line| !line.is_empty())
        .collect()
}

fn run(program: &str, args: &[&str]) -> Option<String> {
    let output = Command::new(program)
        .hidden()
        .args(args)
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
        .ok()?;
    output
        .status
        .success()
        .then(|| String::from_utf8_lossy(&output.stdout).into_owned())
}

fn windows_probe() -> String {
    run(
        "powershell",
        &[
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$o=Get-CimInstance Win32_OperatingSystem;'OS='+$o.Caption+' '+$o.Version;'RAM='+([int64]$o.TotalVisibleMemorySize*1024);Get-CimInstance Win32_VideoController|ForEach-Object{'GPU='+$_.Name+' driver '+$_.DriverVersion}",
        ],
    )
    .unwrap_or_default()
}

fn parse_windows_probe(text: &str) -> (Option<String>, Option<u64>, Vec<String>) {
    let (mut os, mut ram, mut gpus) = (None, None, Vec::new());
    for line in text.lines().map(str::trim) {
        if let Some(value) = line.strip_prefix("OS=") {
            os = Some(value.trim().to_owned()).filter(|v| !v.is_empty());
        } else if let Some(value) = line.strip_prefix("RAM=") {
            ram = value.trim().parse().ok();
        } else if let Some(value) = line.strip_prefix("GPU=") {
            gpus.push(value.trim().to_owned());
        }
    }
    (os, ram, gpus)
}

#[allow(dead_code)] // only called off Windows, but tested everywhere
fn parse_meminfo(text: &str) -> Option<u64> {
    let kib: u64 = text
        .lines()
        .find_map(|line| line.strip_prefix("MemTotal:"))?
        .split_whitespace()
        .next()?
        .parse()
        .ok()?;
    Some(kib * 1024)
}

#[allow(dead_code)]
fn parse_os_release(text: &str) -> Option<String> {
    text.lines()
        .find_map(|line| line.strip_prefix("PRETTY_NAME="))
        .map(|value| value.trim().trim_matches('"').to_owned())
        .filter(|value| !value.is_empty())
}

#[allow(dead_code)]
fn parse_display_names(text: &str) -> Vec<String> {
    text.lines()
        .filter_map(|line| line.trim().strip_prefix("Chipset Model:"))
        .map(|name| name.trim().to_owned())
        .collect()
}

#[allow(dead_code)]
fn parse_lspci(text: &str) -> Vec<String> {
    text.lines()
        .filter(|line| {
            ["VGA compatible", "3D controller", "Display controller"]
                .iter()
                .any(|kind| line.contains(kind))
        })
        .filter_map(|line| {
            line.split_once(": ")
                .map(|(_, name)| name.trim().to_owned())
        })
        .collect()
}

#[cfg(target_os = "macos")]
fn unix_os() -> Option<String> {
    let version = run("sw_vers", &["-productVersion"])?;
    Some(format!("macOS {}", version.trim()))
}

#[cfg(all(unix, not(target_os = "macos")))]
fn unix_os() -> Option<String> {
    parse_os_release(&std::fs::read_to_string("/etc/os-release").ok()?)
}

#[cfg(not(unix))]
fn unix_os() -> Option<String> {
    None
}

#[cfg(target_os = "macos")]
fn unix_ram() -> Option<u64> {
    run("sysctl", &["-n", "hw.memsize"])?.trim().parse().ok()
}

#[cfg(all(unix, not(target_os = "macos")))]
fn unix_ram() -> Option<u64> {
    parse_meminfo(&std::fs::read_to_string("/proc/meminfo").ok()?)
}

#[cfg(not(unix))]
fn unix_ram() -> Option<u64> {
    None
}

#[cfg(target_os = "macos")]
fn unix_gpus() -> Vec<String> {
    run("system_profiler", &["SPDisplaysDataType"])
        .map(|text| parse_display_names(&text))
        .unwrap_or_default()
}

#[cfg(all(unix, not(target_os = "macos")))]
fn unix_gpus() -> Vec<String> {
    run("lspci", &[])
        .map(|text| parse_lspci(&text))
        .unwrap_or_default()
}

#[cfg(not(unix))]
fn unix_gpus() -> Vec<String> {
    Vec::new()
}

/// Free bytes on the volume of `path`, or of its nearest existing parent.
pub fn free_bytes(path: &Path) -> Option<u64> {
    let mut existing = path;
    while !existing.exists() {
        existing = existing.parent()?;
    }
    volume_free(existing)
}

#[cfg(unix)]
#[allow(clippy::unnecessary_cast)]
fn volume_free(path: &Path) -> Option<u64> {
    use std::os::unix::ffi::OsStrExt;
    let path = std::ffi::CString::new(path.as_os_str().as_bytes()).ok()?;
    // SAFETY: `path` is a valid C string and `stats` is a plain output struct that statvfs fills in.
    let stats = unsafe {
        let mut stats: libc::statvfs = std::mem::zeroed();
        if libc::statvfs(path.as_ptr(), &mut stats) != 0 {
            return None;
        }
        stats
    };
    Some(stats.f_bavail as u64 * stats.f_frsize as u64)
}

#[cfg(windows)]
fn volume_free(path: &Path) -> Option<u64> {
    use std::os::windows::ffi::OsStrExt;
    unsafe extern "system" {
        fn GetDiskFreeSpaceExW(
            directory: *const u16,
            available: *mut u64,
            total: *mut u64,
            free: *mut u64,
        ) -> i32;
    }
    let wide: Vec<u16> = path.as_os_str().encode_wide().chain([0]).collect();
    let (mut available, mut total, mut free) = (0u64, 0u64, 0u64);
    // SAFETY: `wide` is NUL terminated and the three outputs are valid for writes.
    let ok = unsafe { GetDiskFreeSpaceExW(wide.as_ptr(), &mut available, &mut total, &mut free) };
    (ok != 0).then_some(available)
}

#[cfg(not(any(unix, windows)))]
fn volume_free(_: &Path) -> Option<u64> {
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_probe_output_of_each_system_is_parsed() {
        let (os, ram, gpus) = parse_windows_probe(
            "OS=Microsoft Windows 11 Pro 10.0.26100\r\nRAM=17179869184\r\nGPU=NVIDIA GeForce RTX 4070 driver 31.0.15.5\r\nGPU=Intel(R) UHD driver 30.0\r\n",
        );
        assert_eq!(os.as_deref(), Some("Microsoft Windows 11 Pro 10.0.26100"));
        assert_eq!(ram, Some(17_179_869_184));
        assert_eq!(gpus.len(), 2);
        assert_eq!(
            parse_meminfo("MemFree: 1 kB\nMemTotal:       16384 kB\n"),
            Some(16_777_216)
        );
        assert_eq!(
            parse_os_release("NAME=X\nPRETTY_NAME=\"Ubuntu 24.04 LTS\"\n").as_deref(),
            Some("Ubuntu 24.04 LTS")
        );
        assert_eq!(
            parse_display_names("Graphics:\n  Chipset Model: Apple M2\n"),
            ["Apple M2"]
        );
        assert_eq!(
            parse_lspci(
                "00:02.0 VGA compatible controller: Intel Corp UHD\n00:1f.3 Audio device: X\n"
            ),
            ["Intel Corp UHD"]
        );
        assert_eq!(
            diagnostic_lines("[Diagnostics] GPU: x\nnoise\n[Diagnostics]\n"),
            ["GPU: x"]
        );
    }

    #[test]
    fn free_space_of_a_missing_folder_uses_its_existing_parent() {
        let missing = std::env::temp_dir().join("strahlender-no-such-folder/deeper");
        assert_eq!(
            free_bytes(&missing).is_some(),
            free_bytes(&std::env::temp_dir()).is_some()
        );
    }
}
