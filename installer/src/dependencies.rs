//! Shared package plans. Only explicit install actions may change the host.
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
    pub manual: Vec<String>,
    pub bootstrap_brew: bool,
}
impl Plan {
    pub fn ready(&self) -> bool {
        self.missing.is_empty() && self.manual.is_empty() && !self.bootstrap_brew
    }
    pub fn description(&self) -> String {
        let mut lines: Vec<String> = self
            .missing
            .iter()
            .map(|m| format!("{}: {}", m.id, m.purpose))
            .collect();
        lines.extend(self.manual.clone());
        if !self.packages.is_empty() {
            lines.push(format!("{}: {}", self.manager, self.packages.join(", ")));
        }
        lines.join("\n")
    }
}
fn succeeds(program: &str, args: &[&str]) -> bool {
    Command::new(program)
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
pub fn inspect(target: &str) -> Result<Plan, String> {
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
    let mut packages = BTreeSet::new();
    if target == "ios"
        && succeeds("xcrun", &["--sdk", "iphoneos", "--show-sdk-path"])
        && !succeeds("xcodebuild", &["-checkFirstLaunchStatus"])
    {
        plan.manual.push(
            "Open Xcode to finish its first-launch setup and license acceptance, then check again."
                .into(),
        );
    }
    for component in catalog.components {
        if component.linux && mac {
            continue;
        }
        if component.wayland && std::env::var("XDG_SESSION_TYPE").as_deref() != Ok("wayland") {
            continue;
        }
        let names = match manager {
            "brew" => &component.brew,
            "apt" => &component.apt,
            "dnf" => &component.dnf,
            _ => &component.pacman,
        };
        let present = if mac && component.id == "git" {
            // Git is provided by Apple's tools; it need not be a Brew formula.
            succeeds(&git(), &["--version"])
        } else if mac {
            names
                .iter()
                .all(|p| succeeds(&brew(), &["list", "--versions", p]))
        } else if let Some(module) = &component.module {
            succeeds("pkg-config", &["--exists", module])
                || component
                    .alternative
                    .as_ref()
                    .is_some_and(|m| succeeds("pkg-config", &["--exists", m]))
        } else if component.header && !succeeds("clang++", &["--version"]) {
            false
        } else if component.header {
            let mut child = Command::new("clang++")
                .args(["-x", "c++", "-fsyntax-only", "-"])
                .stdin(Stdio::piped())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .map_err(|e| e.to_string())?;
            use std::io::Write;
            if let Some(mut input) = child.stdin.take() {
                let _ = input.write_all(b"#if __has_include(<vma/vk_mem_alloc.h>)\n#include <vma/vk_mem_alloc.h>\n#else\n#include <vk_mem_alloc.h>\n#endif\n");
            }
            child.wait().is_ok_and(|s| s.success())
        } else {
            !component.probe.is_empty()
                && succeeds(
                    &component.probe[0],
                    &component.probe[1..]
                        .iter()
                        .map(String::as_str)
                        .collect::<Vec<_>>(),
                )
        };
        if !present {
            if manager == "pacman"
                && let Some(note) = &component.manual_pacman
            {
                plan.manual.push(note.clone());
            }
            packages.extend(names.iter().cloned());
            plan.missing.push(Missing {
                id: component.id,
                purpose: component.purpose,
            });
        }
    }
    plan.packages = packages.into_iter().collect();
    Ok(plan)
}

pub fn installation_script(plan: &Plan) -> Result<String, String> {
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

pub fn install(plan: &Plan) -> Result<(), String> {
    let script = installation_script(plan)?;
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
