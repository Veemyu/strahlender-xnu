//! Shared package plans. Only explicit install actions may change the host.
use crate::process::Hidden;
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeSet,
    path::PathBuf,
    process::{Command, Stdio},
};

#[derive(Debug, Clone, Deserialize)]
struct Catalog {
    schema: u32,
    components: Vec<Component>,
}
#[derive(Debug, Clone, Deserialize)]
struct Component {
    id: String,
    purpose: String,
    #[serde(default)]
    probe: Vec<String>,
    module: Option<String>,
    alternative: Option<String>,
    manual_pacman: Option<String>,
    /// Pinned download done by the installer when the package manager has no package (see vma.rs).
    fetch: Option<String>,
    #[serde(default)]
    header: bool,
    #[serde(default)]
    linux: bool,
    #[serde(default)]
    wayland: bool,
    #[serde(default)]
    brew: Vec<String>,
    #[serde(default)]
    apt: Vec<String>,
    #[serde(default)]
    dnf: Vec<String>,
    #[serde(default)]
    pacman: Vec<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Missing {
    pub id: String,
    pub purpose: String,
}
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Plan {
    pub manager: String,
    pub packages: Vec<String>,
    pub missing: Vec<Missing>,
    /// The failed probe of each entry in `missing`, in the same order.
    #[serde(default)]
    pub checks: Vec<String>,
    pub manual: Vec<String>,
    /// Components the installer downloads itself, pinned and SHA-256 checked (no package exists on this system).
    #[serde(default)]
    pub fetch: Vec<String>,
    pub bootstrap_brew: bool,
}
impl Plan {
    /// One log line per unmet requirement, naming the check that failed.
    pub fn log_lines(&self) -> Vec<String> {
        let mut lines: Vec<String> = self
            .missing
            .iter()
            .enumerate()
            .map(|(i, m)| match self.checks.get(i) {
                Some(check) => format!("Missing: {} (failed check: {check})", m.id),
                None => format!("Missing: {}", m.id),
            })
            .collect();
        lines.extend(self.fetch.iter().map(|id| {
            if id == "vma" {
                format!(
                    "Download: {id} {} (pinned, SHA-256 checked)",
                    crate::vma::lock().version
                )
            } else {
                format!("Download: {id}")
            }
        }));
        lines.extend(
            self.manual
                .iter()
                .map(|note| format!("Manual step: {note}")),
        );
        if !self.packages.is_empty() {
            lines.push(format!("{}: {}", self.manager, self.packages.join(", ")));
        }
        lines
    }
    pub fn ready(&self) -> bool {
        self.missing.is_empty()
            && self.manual.is_empty()
            && self.fetch.is_empty()
            && !self.bootstrap_brew
    }
}
fn succeeds(program: &str, args: &[&str]) -> bool {
    Command::new(program)
        .hidden()
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .is_ok_and(|s| s.success())
}
pub fn brew() -> String {
    mac_prefixes(std::env::consts::ARCH)
        .into_iter()
        .map(|prefix| format!("{prefix}/bin/brew"))
        .find(|p| std::path::Path::new(p).is_file())
        .unwrap_or_else(|| "brew".into())
}

fn select_git(mac: bool, mut probe: impl FnMut(&str, &[&str]) -> bool) -> String {
    if mac && probe("/usr/bin/git", &["--version"]) {
        "/usr/bin/git".into()
    } else {
        "git".into()
    }
}

pub fn git() -> String {
    select_git(cfg!(target_os = "macos"), succeeds)
}
fn mac_prefixes(architecture: &str) -> [&'static str; 2] {
    if architecture == "x86_64" {
        ["/usr/local", "/opt/homebrew"]
    } else {
        ["/opt/homebrew", "/usr/local"]
    }
}
pub fn mac_tool_paths() -> Vec<PathBuf> {
    mac_prefixes(std::env::consts::ARCH)
        .into_iter()
        .flat_map(|prefix| {
            [
                PathBuf::from(format!("{prefix}/opt/llvm/bin")),
                PathBuf::from(format!("{prefix}/bin")),
            ]
        })
        .collect()
}
pub fn detect_manager(os: &str) -> Option<&'static str> {
    let ids: Vec<_> = os
        .lines()
        .filter_map(|line| line.split_once('='))
        .filter(|(k, _)| *k == "ID" || *k == "ID_LIKE")
        .flat_map(|(_, v)| v.trim_matches(['\"', '\'']).split_whitespace())
        .collect();
    if ids.iter().any(|id| ["debian", "ubuntu"].contains(id)) {
        Some("apt")
    } else if ids
        .iter()
        .any(|id| ["fedora", "rhel", "nobara"].contains(id))
    {
        Some("dnf")
    } else if ids.contains(&"arch") {
        Some("pacman")
    } else {
        None
    }
}

/// Windows needs one thing: the build environment that GitHub Actions publishes (see components.rs).
/// The oldest Clang the generated code builds with: `rt/cpu.h` supplies the vector builtins Clang 14 lacks.
const MIN_CLANG: u32 = 14;

fn clang_major_from(text: &str) -> Option<u32> {
    let rest = &text[text.find("clang version ")? + "clang version ".len()..];
    rest.split(|c: char| !c.is_ascii_digit())
        .next()?
        .parse()
        .ok()
}

fn clang_major() -> Option<u32> {
    let output = Command::new("clang")
        .hidden()
        .arg("--version")
        .output()
        .ok()?;
    clang_major_from(&String::from_utf8_lossy(&output.stdout))
}

pub(crate) fn windows_plan(architecture: &str, installed: bool) -> Plan {
    let mut plan = Plan {
        manager: "windows-components".into(),
        ..Plan::default()
    };
    if !installed {
        plan.missing.push(Missing {
            id: "windows-components".into(),
            purpose: "Compiler, Qt, FFmpeg and SDL3 are downloaded once from their publishers and checked; the build tools are part of this installer".into(),
        });
    }
    if architecture != "x86_64" {
        plan.manual
            .push("The native Windows build currently supports amd64 only.".into());
    }
    plan
}

#[cfg(target_os = "windows")]
fn windows_version() -> Result<(u32, u32), String> {
    #[repr(C)]
    struct Version {
        size: u32,
        major: u32,
        minor: u32,
        build: u32,
        platform: u32,
        service_pack: [u16; 128],
    }
    #[link(name = "ntdll")]
    unsafe extern "system" {
        fn RtlGetVersion(version: *mut Version) -> i32;
    }
    let mut version = Version {
        size: std::mem::size_of::<Version>() as u32,
        major: 0,
        minor: 0,
        build: 0,
        platform: 0,
        service_pack: [0; 128],
    };
    let status = unsafe { RtlGetVersion(&mut version) };
    if status < 0 {
        return Err(format!(
            "Could not check Windows version (NTSTATUS {status:#x})."
        ));
    }
    Ok((version.major, version.build))
}

pub fn inspect(target: &str) -> Result<Plan, String> {
    if cfg!(target_os = "windows") {
        if !matches!(target, "native" | "windows" | "windows-arm64") {
            return Err("Build this target on its native host.".into());
        }
        let installed = crate::components::root()
            .ok()
            .is_some_and(|root| crate::components::catalog(&root).is_some());
        let plan = windows_plan(std::env::consts::ARCH, installed);
        #[cfg(target_os = "windows")]
        let plan = {
            let mut plan = plan;
            let (major, build) = windows_version()?;
            if major < 10 || build < 19045 {
                plan.manual
                    .push("Windows 10 22H2 (build 19045) or Windows 11 is required.".into());
            }

            plan
        };
        return Ok(plan);
    }
    let catalog: Catalog = serde_json::from_str(include_str!("../assets/dependencies.json"))
        .map_err(|e| e.to_string())?;
    if catalog.schema != 1 {
        return Err("Unsupported dependency catalog.".into());
    }
    let mac = cfg!(target_os = "macos");
    let manager = if mac {
        "brew"
    } else {
        detect_manager(&std::fs::read_to_string("/etc/os-release").map_err(|e| e.to_string())?)
            .ok_or("This distribution needs manual dependency installation.")?
    };
    let mut plan = Plan {
        manager: manager.into(),
        ..Plan::default()
    };
    plan.bootstrap_brew = mac && !succeeds(&brew(), &["--version"]);
    if mac && !succeeds("xcrun", &["--find", "clang"]) {
        plan.manual
            .push("Install Apple's Command Line Tools in the system dialog, then retry.".into());
    }
    if target == "ios" && !succeeds("xcrun", &["--sdk", "iphoneos", "--show-sdk-path"]) {
        plan.manual.push("Install and open Xcode, accept its license, and install the iOS platform. An Apple signing team is needed only for direct device installation.".into());
    }
    if target == "ios"
        && succeeds("xcrun", &["--sdk", "iphoneos", "--show-sdk-path"])
        && !succeeds("xcodebuild", &["-checkFirstLaunchStatus"])
    {
        plan.manual.push(
            "Open Xcode to finish its first-launch setup and license acceptance, then check again."
                .into(),
        );
    }
    let wayland = std::env::var("XDG_SESSION_TYPE").as_deref() == Ok("wayland");
    check_components(
        catalog.components,
        &mut plan,
        mac,
        wayland,
        &mut succeeds,
        &mut vma_header_found,
    );
    Ok(plan)
}

/// Probes every catalog component; `run` and `header` are injected so tests need no real host tools.
fn check_components(
    components: Vec<Component>,
    plan: &mut Plan,
    mac: bool,
    wayland: bool,
    run: &mut dyn FnMut(&str, &[&str]) -> bool,
    header: &mut dyn FnMut() -> bool,
) {
    let manager = plan.manager.clone();
    let mut packages = BTreeSet::new();
    for component in components {
        if component.linux && mac {
            continue;
        }
        if component.wayland && !wayland {
            continue;
        }
        let names = match manager.as_str() {
            "brew" => &component.brew,
            "apt" => &component.apt,
            "dnf" => &component.dnf,
            _ => &component.pacman,
        };
        let (present, check) = if mac && component.id == "git" {
            // Git is provided by Apple's tools; it need not be a Brew formula.
            (run(&git(), &["--version"]), "git --version".to_string())
        } else if mac {
            (
                names
                    .iter()
                    .all(|p| run(&brew(), &["list", "--versions", p])),
                format!("brew list --versions {}", names.join(" ")),
            )
        } else if let Some(module) = &component.module {
            let mut check = format!("pkg-config --exists {module}");
            let mut found = run("pkg-config", &["--exists", module]);
            if let Some(alternative) = component.alternative.as_ref().filter(|_| !found) {
                found = run("pkg-config", &["--exists", alternative]);
                check.push_str(&format!(" and pkg-config --exists {alternative}"));
            }
            (found, check)
        } else if component.header && !run("clang++", &["--version"]) {
            (false, "clang++ --version".to_string())
        } else if component.header {
            (
                header(),
                "clang++ -fsyntax-only with <vma/vk_mem_alloc.h> or <vk_mem_alloc.h>".to_string(),
            )
        } else {
            let check = component.probe.join(" ");
            let found = !component.probe.is_empty()
                && run(
                    &component.probe[0],
                    &component.probe[1..]
                        .iter()
                        .map(String::as_str)
                        .collect::<Vec<_>>(),
                );
            (found, check)
        };
        if present
            && !mac
            && component.id == "compiler"
            && let Some(major) = clang_major()
            && major < MIN_CLANG
        {
            plan.manual.push(format!(
                "Your Clang is version {major}; version {MIN_CLANG} or newer is needed. Install a newer Clang (for example from apt.llvm.org or a clang-{MIN_CLANG}+ package of your distribution), then check again."
            ));
        }
        if !present {
            if names.is_empty()
                && let Some(id) = &component.fetch
            {
                plan.fetch.push(id.clone());
            } else if manager == "pacman"
                && let Some(note) = &component.manual_pacman
            {
                plan.manual.push(note.clone());
            }
            packages.extend(names.iter().cloned());
            plan.missing.push(Missing {
                id: component.id,
                purpose: component.purpose,
            });
            plan.checks.push(check);
        }
    }
    plan.packages = packages.into_iter().collect();
}

fn vma_header_found() -> bool {
    let mut command = Command::new("clang++");
    command.hidden().args(["-x", "c++", "-fsyntax-only"]);
    // The pinned copy comes after the system's own headers.
    if let Some(folder) = crate::vma::cached() {
        command.arg("-idirafter").arg(folder.join("include"));
    }
    let Ok(mut child) = command
        .arg("-")
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    else {
        return false;
    };
    use std::io::Write;
    if let Some(mut input) = child.stdin.take() {
        let _ = input.write_all(b"#if __has_include(<vma/vk_mem_alloc.h>)\n#include <vma/vk_mem_alloc.h>\n#else\n#include <vk_mem_alloc.h>\n#endif\n");
    }
    child.wait().is_ok_and(|s| s.success())
}

pub fn installation_script(plan: &Plan) -> Result<String, String> {
    if plan.manager == "windows-components" {
        return Err("The Windows components is downloaded directly, not by script.".into());
    }
    // The terminal owns authentication; no password is read by this process.
    let mut script = String::from(
        "#!/bin/bash\nset -e\ntrap 'echo \"Setup stopped. Return to the installer, open Details and check again.\"; read -r -p \"Press Enter to close.\"' ERR\n",
    );
    if cfg!(target_os = "macos") {
        let paths = mac_tool_paths()
            .iter()
            .map(|p| p.to_string_lossy().into_owned())
            .collect::<Vec<_>>()
            .join(":");
        script.push_str(&format!("export PATH={paths}:$PATH\n"));
    }
    if plan.bootstrap_brew {
        script.push_str("echo 'Installing Homebrew to provide the game build tools.'\n/bin/bash -c \"$(/usr/bin/curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"\n");
    }
    for package in &plan.packages {
        if package.is_empty()
            || !package
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"+-._".contains(&b))
        {
            return Err("Invalid package name.".into());
        }
    }
    let names = plan.packages.join(" ");
    if !names.is_empty() {
        script.push_str(&match plan.manager.as_str() {
            "brew" => format!("for p in {names}; do {} info --formula \"$p\" >/dev/null || {{ echo \"Unavailable package: $p\"; exit 1; }}; done\n{} install {names}\n", brew(), brew()),
            "apt" => format!("sudo apt-get update\nfor p in {names}; do apt-cache show \"$p\" >/dev/null || {{ echo \"Unavailable package: $p. Your distribution version may not provide this dependency.\"; exit 1; }}; done\nsudo apt-get install --yes {names}\n"),
            "dnf" => format!("for p in {names}; do dnf info \"$p\" >/dev/null || {{ echo \"Unavailable package: $p\"; exit 1; }}; done\nsudo dnf install --assumeyes {names}\n"),
            "pacman" => format!("for p in {names}; do pacman -Si \"$p\" >/dev/null || {{ echo \"Unavailable package: $p\"; exit 1; }}; done\nsudo pacman -S --needed {names}\n"),
            _ => return Err("Unsupported package manager.".into()),
        });
    }
    if cfg!(target_os = "macos") && plan.manual.iter().any(|s| s.contains("Command Line")) {
        script.push_str("xcode-select --install\n");
    }
    script.push_str("echo 'Return to Strahlender Installer and check again.'\nread -r -p 'Press Enter to close.'\n");
    if cfg!(target_os = "macos") && plan.manual.iter().any(|s| s.contains("Xcode")) {
        script = script.replace("echo 'Return to Strahlender", "echo 'Finish Xcode setup, install its iOS platform, add your Apple account in Settings > Accounts only for direct device installation.'\nopen -a Xcode || open 'macappstore://itunes.apple.com/app/id497799835'\necho 'Return to Strahlender");
    }
    Ok(script)
}

/// False for Linux plans that only download (VMA on Arch) or only list manual steps: no terminal script has anything to do.
pub fn needs_terminal(plan: &Plan) -> bool {
    cfg!(target_os = "macos") || !plan.packages.is_empty() || plan.bootstrap_brew
}

pub fn install(plan: &Plan) -> Result<(), String> {
    if plan.manager == "windows-components" {
        return crate::components::install_latest(&crate::components::root()?).map(|_| ());
    }
    let script = installation_script(plan)?;
    let downloaded = !plan.fetch.is_empty();
    for id in &plan.fetch {
        if id == "vma" {
            crate::vma::fetch()?;
        }
    }
    if !needs_terminal(plan) {
        return if downloaded {
            Ok(())
        } else {
            Err("Nothing can be installed automatically. Follow the manual steps in the list, then check again.".into())
        };
    }
    let directory = directories::ProjectDirs::from("dev", "Veemyu", "strahlender-xnu-installer")
        .ok_or("Application data unavailable.")?
        .data_dir()
        .join("setup");
    std::fs::create_dir_all(&directory).map_err(|e| e.to_string())?;
    let log = directory.join(format!("install-{}.log", std::process::id()));
    let quoted = format!("'{}'", log.to_string_lossy().replace('\'', "'\\''"));
    let script = script.replacen(
        "set -e\n",
        &format!("set -e\nexec > >(tee {quoted}) 2>&1\n"),
        1,
    );
    let file: PathBuf = directory.join(format!("install-{}.command", std::process::id()));
    std::fs::write(&file, script).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o700))
            .map_err(|e| e.to_string())?;
    }
    let status = if cfg!(target_os = "macos") {
        Command::new("open")
            .args(["-a", "Terminal"])
            .arg(&file)
            .status()
    } else {
        let terminal = ["x-terminal-emulator", "konsole", "gnome-terminal", "xterm"]
            .into_iter()
            .find(|p| succeeds("which", &[p]))
            .ok_or("No terminal found. Install the listed packages manually, then check again.")?;
        let mut command = Command::new(terminal);
        command
            .arg(if terminal == "gnome-terminal" {
                "--"
            } else {
                "-e"
            })
            .arg("bash")
            .arg(&file);
        command.spawn().map(|_| return_success())
    }
    .map_err(|e| e.to_string())?;
    if status.success() {
        Ok(())
    } else {
        Err("Could not open the guided installation terminal.".into())
    }
}

pub fn read_setup_log() -> String {
    use std::io::Read;
    let Some(dirs) = directories::ProjectDirs::from("dev", "Veemyu", "strahlender-xnu-installer")
    else {
        return String::new();
    };
    let path = dirs
        .data_dir()
        .join("setup")
        .join(format!("install-{}.log", std::process::id()));
    let Ok(file) = std::fs::File::open(path) else {
        return String::new();
    };
    let mut text = String::new();
    let _ = file.take(200_000).read_to_string(&mut text);
    text
}
#[cfg(unix)]
fn return_success() -> std::process::ExitStatus {
    use std::os::unix::process::ExitStatusExt;
    std::process::ExitStatus::from_raw(0)
}
#[cfg(windows)]
fn return_success() -> std::process::ExitStatus {
    use std::os::windows::process::ExitStatusExt;
    std::process::ExitStatus::from_raw(0)
}

#[cfg(test)]
mod tests {
    #[test]
    fn windows_needs_only_the_downloaded_build_environment() {
        let missing = super::windows_plan("x86_64", false);
        assert_eq!(missing.manager, "windows-components");
        assert!(!missing.ready() && missing.packages.is_empty() && !missing.bootstrap_brew);
        assert!(
            missing
                .missing
                .iter()
                .any(|item| item.id == "windows-components")
        );
        assert!(super::installation_script(&missing).is_err());
        assert!(super::windows_plan("x86_64", true).ready());
        assert!(
            !super::windows_plan("aarch64", true).ready(),
            "ARM64 is not supported yet"
        );
    }
    #[test]
    fn apple_git_is_accepted_without_a_homebrew_formula() {
        let selected = super::select_git(true, |program, args| {
            assert_eq!(program, "/usr/bin/git");
            assert_eq!(args, &["--version"]);
            true
        });
        assert_eq!(selected, "/usr/bin/git");
        assert_eq!(super::select_git(true, |_, _| false), "git");
        assert_eq!(
            super::select_git(false, |_, _| panic!("No Apple probe on Linux")),
            "git"
        );
    }
    #[test]
    fn clang_versions_are_read_from_the_first_line() {
        assert_eq!(
            super::clang_major_from("Ubuntu clang version 14.0.0-1ubuntu1.1\nTarget: x86_64"),
            Some(14)
        );
        assert_eq!(
            super::clang_major_from(
                "clang version 22.1.7 (https://github.com/llvm/llvm-project.git)"
            ),
            Some(22)
        );
        assert_eq!(
            super::clang_major_from("Debian clang version 11.0.1-2"),
            Some(11)
        );
        assert_eq!(super::clang_major_from("gcc (GCC) 14.2.1"), None);
    }

    #[test]
    fn homebrew_prefix_order_matches_each_mac_architecture() {
        assert_eq!(
            super::mac_prefixes("aarch64"),
            ["/opt/homebrew", "/usr/local"]
        );
        assert_eq!(
            super::mac_prefixes("x86_64"),
            ["/usr/local", "/opt/homebrew"]
        );
    }
    #[test]
    fn scripts_validate_package_names_and_use_only_the_selected_manager() {
        for (manager, expected) in [
            ("apt", "apt-get install"),
            ("dnf", "dnf install"),
            ("pacman", "pacman -S"),
            ("brew", "brew install"),
        ] {
            let plan = super::Plan {
                manager: manager.into(),
                packages: vec!["clang".into()],
                ..Default::default()
            };
            let script = super::installation_script(&plan).unwrap();
            assert!(script.contains(expected));
            assert!(!script.contains("pip install"));
            let bad = super::Plan {
                packages: vec!["$(touch /tmp/unwanted)".into()],
                ..plan
            };
            assert!(super::installation_script(&bad).is_err());
        }
    }
    #[test]
    fn steamos_with_all_packages_but_no_vma_plans_the_pinned_download_and_names_the_check() {
        let manager = super::detect_manager("NAME=\"SteamOS\"\nID=steamos\nID_LIKE=arch\n");
        assert_eq!(manager, Some("pacman"));
        let catalog: super::Catalog =
            serde_json::from_str(include_str!("../assets/dependencies.json")).unwrap();
        let mut plan = super::Plan {
            manager: "pacman".into(),
            ..Default::default()
        };
        let mut probes = Vec::new();
        super::check_components(
            catalog.components,
            &mut plan,
            false,
            false,
            &mut |program, args| {
                probes.push(format!("{program} {}", args.join(" ")));
                true
            },
            &mut || false,
        );
        assert!(!plan.ready());
        assert_eq!(plan.missing.len(), 1);
        assert_eq!(plan.missing[0].id, "vma");
        assert!(plan.packages.is_empty(), "nothing pacman can install");
        assert_eq!(
            plan.fetch,
            ["vma"],
            "the installer downloads the pinned header itself"
        );
        assert!(plan.manual.is_empty());
        let lines = plan.log_lines();
        assert!(
            lines[0].starts_with("Missing: vma (failed check: clang++ "),
            "{lines:?}"
        );
        assert!(lines[1].starts_with("Download: vma 3."), "{lines:?}");
        assert!(!super::needs_terminal(&plan) || cfg!(target_os = "macos"));
        assert!(probes.iter().any(|p| p == "pkg-config --exists sdl3"));
    }
    #[test]
    fn linux_catalog_installs_xdg_utils_for_folder_actions() {
        let catalog: super::Catalog =
            serde_json::from_str(include_str!("../assets/dependencies.json")).unwrap();
        let component = catalog
            .components
            .iter()
            .find(|component| component.id == "xdg-utils")
            .expect("xdg-utils is a Linux requirement");
        assert!(component.linux);
        assert_eq!(
            component.probe,
            vec!["xdg-open".to_string(), "--version".to_string()]
        );
        assert_eq!(component.apt, vec!["xdg-utils".to_string()]);
        assert_eq!(component.dnf, vec!["xdg-utils".to_string()]);
        assert_eq!(component.pacman, vec!["xdg-utils".to_string()]);
    }
    #[test]
    fn detects_distribution_families() {
        assert_eq!(
            super::detect_manager("ID=nobara\nID_LIKE=\"fedora\""),
            Some("dnf")
        );
        assert_eq!(
            super::detect_manager("ID=linuxmint\nID_LIKE=\"ubuntu debian\""),
            Some("apt")
        );
        assert_eq!(
            super::detect_manager("ID=endeavouros\nID_LIKE=arch"),
            Some("pacman")
        );
        assert_eq!(super::detect_manager("PRETTY_NAME=Arch"), None);
    }
}
