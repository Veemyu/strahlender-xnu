//! The driver start of a build as plain data: the program, the argument vector, the environment changes and the working
//! folder. The window and `--cli build` both go through `backend::build`, which computes this plan and starts exactly it, so
//! neither path assembles arguments or environment on its own. `HostFacts` holds everything read from the machine, which
//! keeps `DriverPlan::new` free of file system and process state (and testable for every target on every host).
use crate::backend::{BuildRequest, IosDelivery};
use crate::platform::Platform;
use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};

/// What the machine contributes to the driver command line.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HostFacts {
    pub host: Platform,
    /// This executable; the scripts run `--cli extract` through it.
    pub own_exe: Option<PathBuf>,
    pub data_dir: Result<PathBuf, String>,
    /// `BDSP_SHADER_CACHE_DIR` / `BDSP_IOS_FFMPEG_DIR` were already set by the caller and stay as they are.
    pub shader_cache_inherited: bool,
    pub ffmpeg_inherited: bool,
    pub vma_dir: Option<PathBuf>,
    pub git: String,
    pub mac_tool_paths: Vec<PathBuf>,
    pub inherited_path: OsString,
    pub windows_catalog: Option<PathBuf>,
    pub firmware_helper: PathBuf,
    pub firmware_cache: Option<PathBuf>,
    pub ips_helper: Option<PathBuf>,
    /// Debug builds only: `--install-root` for isolated development installs.
    pub dev_install_root: Option<OsString>,
    /// Windows only: the install folder chosen in the build options.
    pub chosen_install_folder: Option<PathBuf>,
}

impl HostFacts {
    pub fn detect() -> Self {
        let host = Platform::native();
        Self {
            host,
            own_exe: std::env::current_exe().ok(),
            data_dir: crate::workspace::data_dir(),
            shader_cache_inherited: std::env::var_os("BDSP_SHADER_CACHE_DIR").is_some(),
            ffmpeg_inherited: std::env::var_os("BDSP_IOS_FFMPEG_DIR").is_some(),
            vma_dir: crate::vma::cached(),
            git: if host == Platform::Windows {
                String::new()
            } else {
                crate::dependencies::git()
            },
            mac_tool_paths: if host == Platform::Mac {
                crate::dependencies::mac_tool_paths()
            } else {
                Vec::new()
            },
            inherited_path: std::env::var_os("PATH").unwrap_or_default(),
            windows_catalog: crate::components::root()
                .ok()
                .and_then(|root| crate::components::catalog(&root)),
            firmware_helper: crate::bundle::helper("firmware_import").unwrap_or_else(|| {
                std::env::current_exe()
                    .unwrap_or_default()
                    .with_file_name("firmware_import")
            }),
            firmware_cache: crate::appdir::data_local_dir().map(|data| data.join("firmware")),
            ips_helper: ips_helper(),
            dev_install_root: dev_install_root(),
            chosen_install_folder: if host == Platform::Windows {
                crate::appdir::chosen_folder(crate::appdir::INSTALL_FOLDER)
            } else {
                None
            },
        }
    }
}

fn ips_helper() -> Option<PathBuf> {
    let sibling = if cfg!(windows) {
        crate::bundle::helper("ips_patch")
    } else {
        let executable = std::env::current_exe().ok()?;
        Some(executable.with_file_name("ips_patch")).filter(|path| path.is_file())
    };
    if sibling.is_some() {
        return sibling;
    }
    if cfg!(debug_assertions) {
        let root = crate::runtime::project_root()?;
        let debug = root.join("installer/target/debug/ips_patch");
        if debug.is_file() {
            return Some(debug);
        }
    }
    None
}

#[cfg(debug_assertions)]
fn dev_install_root() -> Option<OsString> {
    development_install_root(
        std::env::var_os("BDSP_INSTALLER_DEV_CHECKOUT").as_deref() == Some(OsStr::new("1")),
        std::env::var_os("BDSP_INSTALLER_DEV_INSTALL_ROOT"),
    )
}

#[cfg(not(debug_assertions))]
fn dev_install_root() -> Option<OsString> {
    None
}

#[cfg(debug_assertions)]
fn development_install_root(
    local_checkout: bool,
    destination: Option<OsString>,
) -> Option<OsString> {
    destination.filter(|_| local_checkout)
}

/// The Python runtime that runs the driver.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Python {
    pub program: PathBuf,
    /// The private runtime (isolated mode `-I`, its folder first on PATH).
    pub private: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DriverPlan {
    pub program: PathBuf,
    pub args: Vec<OsString>,
    /// In order; `None` removes the variable from the inherited environment.
    pub env: Vec<(OsString, Option<OsString>)>,
    pub cwd: PathBuf,
}

impl DriverPlan {
    fn set(&mut self, key: &str, value: impl Into<OsString>) {
        self.env.retain(|(name, _)| name != key);
        self.env.push((key.into(), Some(value.into())));
    }

    fn remove(&mut self, key: &str) {
        self.env.retain(|(name, _)| name != key);
        self.env.push((key.into(), None));
    }

    fn arg(&mut self, value: impl Into<OsString>) {
        self.args.push(value.into());
    }

    fn option(&mut self, flag: &str, value: impl Into<OsString>) {
        self.arg(flag);
        self.arg(value);
    }

    /// The process to start: piped output, no console window, ends with the installer.
    pub fn command(&self) -> tokio::process::Command {
        use crate::process::Hidden;
        let mut command = tokio::process::Command::new(&self.program);
        command.hidden().args(&self.args).current_dir(&self.cwd);
        for (key, value) in &self.env {
            match value {
                Some(value) => command.env(key, value),
                None => command.env_remove(key),
            };
        }
        command
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .kill_on_drop(true);
        command
    }

    /// The value the plan sets for `key` (`None` when it is removed or untouched).
    #[cfg(test)]
    pub fn env_value(&self, key: &str) -> Option<&OsStr> {
        self.env
            .iter()
            .find(|(name, _)| name == key)
            .and_then(|(_, value)| value.as_deref())
    }

    pub fn new(
        facts: &HostFacts,
        python: &Python,
        root: &Path,
        request: &BuildRequest,
        mods_folder: Option<&Path>,
        selected_mod: Option<&str>,
    ) -> Result<Self, String> {
        let mut plan = Self {
            program: python.program.clone(),
            args: Vec::new(),
            env: Vec::new(),
            cwd: root.to_path_buf(),
        };
        if let Some(own) = &facts.own_exe {
            for (key, value) in crate::components::extract_env(own) {
                plan.set(key, value);
            }
        }
        // The shader libraries prepared from the game's own shaders stay between builds.
        if !facts.shader_cache_inherited
            && let Ok(data) = &facts.data_dir
        {
            plan.set("BDSP_SHADER_CACHE_DIR", data.join("shader-cache"));
        }
        // The iPhone/iPad FFmpeg libraries stay between builds too.
        if !facts.ffmpeg_inherited
            && let Ok(data) = &facts.data_dir
        {
            plan.set("BDSP_IOS_FFMPEG_DIR", data.join("ios-ffmpeg"));
        }
        if let Some(folder) = &facts.vma_dir {
            plan.set("BDSP_VMA_DIR", folder.as_os_str());
        }
        // LLVM still leads PATH; Git is selected separately so Brew cannot shadow Apple Git.
        if facts.host != Platform::Windows {
            plan.set("BDSP_GIT", facts.git.as_str());
        }
        let mut search_paths: Vec<PathBuf> = facts.mac_tool_paths.clone();
        if python.private
            && let Some(directory) = python.program.parent()
        {
            search_paths.insert(0, directory.to_path_buf());
        }
        search_paths.extend(std::env::split_paths(&facts.inherited_path));
        if let Ok(path) = std::env::join_paths(search_paths) {
            plan.set("PATH", path);
        }
        plan.set("BDSP_MOD", selected_mod.unwrap_or("none"));
        if let Some(folder) = mods_folder {
            plan.set("BDSP_MODS_DIR", folder.as_os_str());
        }
        if python.private {
            plan.arg("-I");
            plan.set("BDSP_INSTALLER_PRIVATE_RUNTIME", "1");
        } else {
            plan.remove("BDSP_INSTALLER_PRIVATE_RUNTIME");
        }
        plan.arg("-B");
        plan.arg(root.join("scripts/install/driver.py"));
        plan.build_arguments(facts, root, request, mods_folder)?;
        plan.set("PYTHONDONTWRITEBYTECODE", "1");
        plan.set("PYTHONUNBUFFERED", "1");
        plan.remove("PYTHONPATH");
        plan.remove("PYTHONHOME");
        Ok(plan)
    }

    fn build_arguments(
        &mut self,
        facts: &HostFacts,
        root: &Path,
        request: &BuildRequest,
        mods_folder: Option<&Path>,
    ) -> Result<(), String> {
        let target = request.target;
        let ios = target == "ios";
        let ipa = ios && request.ios_delivery == IosDelivery::Ipa;
        let device = ios && request.ios_delivery == IosDelivery::Device;
        // Inherited shell state must not override the UI, including Apple cross targets.
        if target == "linux" {
            self.set(
                "BDSP_CPU_TARGET",
                if request.portable_cpu {
                    "portable"
                } else {
                    "native"
                },
            );
        } else {
            self.remove("BDSP_CPU_TARGET");
        }
        self.arg("build");
        self.option("--root", root);
        self.option("--work", root.join("work"));
        self.option("--target", target);
        self.option("--base", &request.base);
        self.option("--prod-keys", &request.prod_keys);
        if target.starts_with("windows")
            && let Some(catalog) = &facts.windows_catalog
        {
            self.option("--windows-catalog", catalog);
        }
        if ios {
            self.option("--ios-delivery", request.ios_delivery.as_str());
            if device && let Some(device) = &request.ios_device {
                self.option("--ios-device", device);
            }
            if device && let Some(team) = &request.ios_team {
                self.option("--ios-team", team);
            }
            if ipa {
                let data = facts.data_dir.as_ref().map_err(Clone::clone)?;
                self.option("--ios-export-dir", data.join("exports/ios"));
            }
        }
        if request.clean_build {
            self.arg("--clean-build");
        }
        if ipa && request.ios_export_no_embed {
            self.arg("--ios-export-no-embed");
        }
        if ipa && let Some(profile) = &request.ios_profile {
            self.option("--ios-profile-id", &profile.id);
            self.option("--ios-profile-game", &profile.game);
            self.option("--ios-bundle-id", &profile.bundle);
        } else if ipa && let Some(id) = &request.ios_new_profile {
            self.option("--ios-profile-id", id);
        }
        if let Some(destination) = &facts.dev_install_root {
            self.option("--install-root", destination);
        } else if target.starts_with("windows")
            && let Some(folder) = &facts.chosen_install_folder
        {
            self.option("--install-root", folder);
        }
        if let Some(source) = &request.firmware {
            self.option("--firmware", source);
            self.option("--firmware-helper", &facts.firmware_helper);
            if let Some(cache) = &facts.firmware_cache {
                self.option("--firmware-cache", cache);
            }
        }
        if let Some(update) = &request.update {
            self.option("--update", update);
        }
        if let Some(mod_root) = &request.mod_root {
            self.option("--mod-root", mod_root);
        }
        if let Some(mod_name) = &request.mod_name {
            self.option("--mod-name", mod_name);
        }
        if let Some(mods_dir) = mods_folder {
            self.option("--mods-dir", mods_dir);
        }
        if let Some(helper) = &facts.ips_helper {
            self.option("--ips-helper", helper);
        }
        Ok(())
    }
}

#[cfg(test)]
pub mod tests {
    use super::*;

    pub fn facts(host: Platform) -> HostFacts {
        HostFacts {
            host,
            own_exe: Some(PathBuf::from("installer-exe")),
            data_dir: Ok(PathBuf::from("data")),
            shader_cache_inherited: false,
            ffmpeg_inherited: false,
            vma_dir: Some(PathBuf::from("vma")),
            git: "git-tool".into(),
            mac_tool_paths: vec![PathBuf::from("llvm-bin")],
            inherited_path: std::env::join_paths(["shell-bin"]).unwrap(),
            windows_catalog: Some(PathBuf::from("catalog.json")),
            firmware_helper: PathBuf::from("fw-helper"),
            firmware_cache: Some(PathBuf::from("data").join("firmware")),
            ips_helper: Some(PathBuf::from("ips-helper")),
            dev_install_root: None,
            chosen_install_folder: None,
        }
    }

    pub fn request(target: &'static str) -> BuildRequest {
        BuildRequest {
            target,
            ios_delivery: IosDelivery::Device,
            ios_device: None,
            ios_team: None,
            ios_profile: None,
            ios_new_profile: None,
            portable_cpu: false,
            clean_build: false,
            ios_export_no_embed: false,
            auto_cleanup: false,
            base: PathBuf::from("game"),
            prod_keys: PathBuf::from("prod.keys"),
            firmware: None,
            update: None,
            mod_root: None,
            mod_name: None,
        }
    }

    fn python(private: bool) -> Python {
        Python {
            program: PathBuf::from("runtime").join("python"),
            private,
        }
    }

    fn plan(facts: &HostFacts, private: bool, request: &BuildRequest) -> DriverPlan {
        DriverPlan::new(
            facts,
            &python(private),
            Path::new("root"),
            request,
            None,
            None,
        )
        .unwrap()
    }

    fn text(plan: &DriverPlan) -> Vec<String> {
        plan.args
            .iter()
            .map(|arg| arg.to_string_lossy().into_owned())
            .collect()
    }

    fn pair(args: &[String], flag: &str) -> Option<String> {
        let at = args.iter().position(|arg| arg == flag)?;
        args.get(at + 1).cloned()
    }

    #[test]
    fn arguments_start_with_the_isolation_flags_and_the_driver() {
        let private = text(&plan(&facts(Platform::Linux), true, &request("linux")));
        assert_eq!(
            private[..3],
            ["-I", "-B", &*path("root/scripts/install/driver.py")]
        );
        assert_eq!(private[3], "build");
        let system = text(&plan(&facts(Platform::Linux), false, &request("linux")));
        assert_eq!(
            system[..2],
            ["-B", &*path("root/scripts/install/driver.py")]
        );
    }

    fn path(value: &str) -> String {
        value
            .split('/')
            .collect::<PathBuf>()
            .to_string_lossy()
            .into_owned()
    }

    #[test]
    fn cpu_choice_reaches_linux_and_does_not_leak_to_apple_builds() {
        for (target, portable, expected) in [
            ("linux", false, Some("native")),
            ("linux", true, Some("portable")),
            ("macos", true, None),
            ("ios", false, None),
        ] {
            let mut input = request(target);
            input.portable_cpu = portable;
            let plan = plan(&facts(Platform::Mac), false, &input);
            assert_eq!(
                plan.env_value("BDSP_CPU_TARGET").and_then(OsStr::to_str),
                expected
            );
            if expected.is_none() {
                assert!(
                    plan.env
                        .contains(&(OsString::from("BDSP_CPU_TARGET"), None)),
                    "inherited value must be removed"
                );
            }
        }
    }

    #[test]
    fn windows_targets_pass_the_catalog_and_other_targets_do_not() {
        for target in ["windows", "windows-arm64"] {
            let args = text(&plan(&facts(Platform::Windows), true, &request(target)));
            assert_eq!(pair(&args, "--target").as_deref(), Some(target));
            assert_eq!(
                pair(&args, "--windows-catalog").as_deref(),
                Some("catalog.json")
            );
        }
        let args = text(&plan(&facts(Platform::Mac), true, &request("macos")));
        assert_eq!(pair(&args, "--windows-catalog"), None);
    }

    #[test]
    fn ios_device_and_ipa_take_their_own_options() {
        let mut device = request("ios");
        device.ios_device = Some("UDID".into());
        device.ios_team = Some("TEAM123456".into());
        device.ios_export_no_embed = true;
        device.ios_new_profile = Some("new".into());
        let args = text(&plan(&facts(Platform::Mac), true, &device));
        assert_eq!(pair(&args, "--ios-delivery").as_deref(), Some("device"));
        assert_eq!(pair(&args, "--ios-device").as_deref(), Some("UDID"));
        assert_eq!(pair(&args, "--ios-team").as_deref(), Some("TEAM123456"));
        for ipa_only in [
            "--ios-export-dir",
            "--ios-export-no-embed",
            "--ios-profile-id",
        ] {
            assert!(!args.iter().any(|arg| arg == ipa_only), "{ipa_only}");
        }

        let mut ipa = device.clone();
        ipa.ios_delivery = IosDelivery::Ipa;
        let args = text(&plan(&facts(Platform::Mac), true, &ipa));
        assert_eq!(pair(&args, "--ios-delivery").as_deref(), Some("ipa"));
        assert_eq!(
            pair(&args, "--ios-export-dir"),
            Some(path("data/exports/ios"))
        );
        assert_eq!(pair(&args, "--ios-profile-id").as_deref(), Some("new"));
        assert!(args.iter().any(|arg| arg == "--ios-export-no-embed"));
        assert_eq!(pair(&args, "--ios-device"), None);
        assert_eq!(pair(&args, "--ios-team"), None);

        ipa.ios_profile = Some(crate::ios_profile::Profile {
            id: "profile".into(),
            game: "game".into(),
            bundle: "bundle".into(),
            name: "name".into(),
            aliases: Vec::new(),
        });
        let args = text(&plan(&facts(Platform::Mac), true, &ipa));
        assert_eq!(pair(&args, "--ios-profile-id").as_deref(), Some("profile"));
        assert_eq!(pair(&args, "--ios-profile-game").as_deref(), Some("game"));
        assert_eq!(pair(&args, "--ios-bundle-id").as_deref(), Some("bundle"));
    }

    #[test]
    fn an_ipa_export_without_a_data_folder_is_an_error() {
        let mut broken = facts(Platform::Mac);
        broken.data_dir = Err("no data folder".into());
        let mut ipa = request("ios");
        ipa.ios_delivery = IosDelivery::Ipa;
        let result = DriverPlan::new(&broken, &python(true), Path::new("root"), &ipa, None, None);
        assert_eq!(result.unwrap_err(), "no data folder");
        assert!(
            DriverPlan::new(
                &broken,
                &python(true),
                Path::new("root"),
                &request("macos"),
                None,
                None
            )
            .is_ok()
        );
    }

    #[test]
    fn mod_firmware_update_and_helpers_follow_the_request() {
        let mut input = request("macos");
        input.firmware = Some(PathBuf::from("fw"));
        input.update = Some(PathBuf::from("update.nsp"));
        input.mod_root = Some(PathBuf::from("mods").join("alpha"));
        input.mod_name = Some("alpha".into());
        input.clean_build = true;
        let plan = DriverPlan::new(
            &facts(Platform::Mac),
            &python(true),
            Path::new("root"),
            &input,
            Some(Path::new("mods")),
            Some("alpha"),
        )
        .unwrap();
        let args = text(&plan);
        assert_eq!(pair(&args, "--firmware").as_deref(), Some("fw"));
        assert_eq!(
            pair(&args, "--firmware-helper").as_deref(),
            Some("fw-helper")
        );
        assert_eq!(pair(&args, "--firmware-cache"), Some(path("data/firmware")));
        assert_eq!(pair(&args, "--update").as_deref(), Some("update.nsp"));
        assert_eq!(pair(&args, "--mod-root"), Some(path("mods/alpha")));
        assert_eq!(pair(&args, "--mod-name").as_deref(), Some("alpha"));
        assert_eq!(pair(&args, "--mods-dir").as_deref(), Some("mods"));
        assert_eq!(pair(&args, "--ips-helper").as_deref(), Some("ips-helper"));
        assert!(args.iter().any(|arg| arg == "--clean-build"));
        assert_eq!(
            plan.env_value("BDSP_MOD").and_then(OsStr::to_str),
            Some("alpha")
        );
        assert_eq!(
            plan.env_value("BDSP_MODS_DIR").and_then(OsStr::to_str),
            Some("mods")
        );
        let bare = plan_without_mod();
        assert_eq!(
            bare.env_value("BDSP_MOD").and_then(OsStr::to_str),
            Some("none")
        );
        assert_eq!(bare.env_value("BDSP_MODS_DIR"), None);
    }

    fn plan_without_mod() -> DriverPlan {
        plan(&facts(Platform::Mac), true, &request("macos"))
    }

    #[test]
    fn environment_depends_on_host_and_runtime() {
        let mac = plan(&facts(Platform::Mac), true, &request("macos"));
        assert_eq!(
            mac.env_value("BDSP_GIT").and_then(OsStr::to_str),
            Some("git-tool")
        );
        let search: Vec<_> = std::env::split_paths(mac.env_value("PATH").unwrap()).collect();
        assert_eq!(
            search,
            [
                PathBuf::from("runtime"),
                PathBuf::from("llvm-bin"),
                PathBuf::from("shell-bin")
            ]
        );
        assert_eq!(
            mac.env_value("BDSP_INSTALLER_PRIVATE_RUNTIME")
                .and_then(OsStr::to_str),
            Some("1")
        );
        assert_eq!(
            mac.env_value("BDSP_EXTRACT").and_then(OsStr::to_str),
            Some("installer-exe")
        );
        assert_eq!(
            mac.env_value("BDSP_EXTRACT_PREFIX").and_then(OsStr::to_str),
            Some("--cli")
        );
        assert_eq!(
            mac.env_value("BDSP_SHADER_CACHE_DIR").map(PathBuf::from),
            Some(PathBuf::from("data").join("shader-cache"))
        );
        assert_eq!(
            mac.env_value("BDSP_VMA_DIR").and_then(OsStr::to_str),
            Some("vma")
        );
        for removed in ["PYTHONPATH", "PYTHONHOME"] {
            assert!(mac.env.contains(&(OsString::from(removed), None)));
        }
        assert_eq!(mac.cwd, PathBuf::from("root"));

        let mut windows_facts = facts(Platform::Windows);
        windows_facts.mac_tool_paths.clear();
        windows_facts.shader_cache_inherited = true;
        let windows = plan(&windows_facts, false, &request("windows"));
        assert_eq!(windows.env_value("BDSP_GIT"), None);
        assert_eq!(windows.env_value("BDSP_SHADER_CACHE_DIR"), None);
        assert!(
            windows
                .env
                .contains(&(OsString::from("BDSP_INSTALLER_PRIVATE_RUNTIME"), None))
        );
        let search: Vec<_> = std::env::split_paths(windows.env_value("PATH").unwrap()).collect();
        assert_eq!(search, [PathBuf::from("shell-bin")]);
    }

    #[test]
    fn a_chosen_install_folder_is_passed_for_windows_targets_only() {
        let mut chosen = facts(Platform::Windows);
        chosen.chosen_install_folder = Some(PathBuf::from("D:\\games"));
        let args = text(&plan(&chosen, true, &request("windows-x86_64")));
        assert_eq!(pair(&args, "--install-root").as_deref(), Some("D:\\games"));
        let mut other = facts(Platform::Mac);
        other.chosen_install_folder = Some(PathBuf::from("D:\\games"));
        let args = text(&plan(&other, true, &request("macos")));
        assert_eq!(pair(&args, "--install-root"), None);
    }

    #[test]
    #[cfg(debug_assertions)]
    fn development_install_destination_requires_an_explicit_local_checkout() {
        assert_eq!(
            development_install_root(false, Some("isolated apps".into())),
            None
        );
        assert_eq!(
            development_install_root(true, Some("isolated apps".into())),
            Some(OsString::from("isolated apps"))
        );
        let mut dev = facts(Platform::Mac);
        dev.dev_install_root = Some("isolated apps".into());
        let args = text(&plan(&dev, true, &request("macos")));
        assert_eq!(
            pair(&args, "--install-root").as_deref(),
            Some("isolated apps")
        );
    }
}
