//! Window-free rules of the build flow. The GUI (app.rs) and `--cli build` (headless.rs) both call these, so the build
//! request, the support matrix and the stage list cannot drift between the two paths.
use crate::app::InstallTarget;
use crate::backend::{BuildRequest, IosDelivery};
use crate::mod_support::ModEntry;
use crate::platform::Platform;
use crate::progress::Stage;
use std::path::{Path, PathBuf};

/// Which host, target and CPU architecture have a real build path. Linux aarch64 is allowed but experimental.
pub fn platform_backend_supported(host: Platform, target: InstallTarget, arch: &str) -> bool {
    matches!(
        (host, target, arch),
        (
            Platform::Mac,
            InstallTarget::Mac | InstallTarget::Ios,
            "aarch64"
        ) | (Platform::Linux, InstallTarget::Linux, "x86_64" | "aarch64")
            | (
                Platform::Windows,
                InstallTarget::Windows,
                "x86_64" | "aarch64"
            )
    )
}

/// Targets whose build stages IPS/IPS32 and subsdk1 into a separate mod app. Linux still installs one fixed app.
pub fn ips_target(host: Platform, target: InstallTarget) -> bool {
    matches!(
        (host, target),
        (Platform::Mac, InstallTarget::Mac | InstallTarget::Ios)
            | (Platform::Windows, InstallTarget::Windows)
            | (Platform::Linux, InstallTarget::Linux)
    )
}

/// The `--target` value of the driver.
pub fn target_name(target: InstallTarget, arch: &str) -> Option<&'static str> {
    match target {
        InstallTarget::Mac => Some("macos"),
        InstallTarget::Linux => Some("linux"),
        InstallTarget::Windows => Some(if arch == "aarch64" {
            "windows-arm64"
        } else {
            "windows"
        }),
        InstallTarget::Ios => Some("ios"),
        InstallTarget::Android => None,
    }
}

/// A game folder, or an XCI or NSP file.
pub fn base_is_buildable(path: &Path) -> bool {
    path.is_dir()
        || path
            .extension()
            .is_some_and(|ext| ext.eq_ignore_ascii_case("xci") || ext.eq_ignore_ascii_case("nsp"))
}

pub fn backend_supported(
    host: Platform,
    target: InstallTarget,
    arch: &str,
    base: Option<&Path>,
    selected_mod: Option<&str>,
    mods: &[ModEntry],
) -> bool {
    platform_backend_supported(host, target, arch)
        && base.is_some_and(base_is_buildable)
        && selected_mod.is_none_or(|name| {
            mods.iter().any(|item| {
                item.name == name
                    && (!item.has_exefs || (ips_target(host, target) && item.ips_buildable()))
            })
        })
}

pub fn build_stages(
    target: InstallTarget,
    ios_delivery: IosDelivery,
    has_firmware: bool,
    code_mod: bool,
) -> Vec<Stage> {
    Stage::ALL
        .into_iter()
        .filter(|stage| *stage != Stage::Firmware || has_firmware)
        .filter(|stage| *stage != Stage::Exefs || code_mod)
        .filter(|stage| {
            // prebuilt Metal libraries: only the Apple targets (Mac and iPhone/iPad)
            *stage != Stage::Shaders || matches!(target, InstallTarget::Mac | InstallTarget::Ios)
        })
        .filter(|stage| {
            *stage != Stage::Signing
                || (target == InstallTarget::Ios && ios_delivery == IosDelivery::Device)
        })
        .collect()
}

/// Whether the selected mod replaces game code (needs the Exefs stage).
pub fn code_mod_selected(
    mods_skipped: bool,
    selected_mod: Option<&str>,
    mods: &[ModEntry],
) -> bool {
    !mods_skipped
        && mods
            .iter()
            .any(|entry| selected_mod == Some(entry.name.as_str()) && entry.has_exefs)
}

pub struct RequestInputs<'a> {
    pub target: InstallTarget,
    pub arch: &'a str,
    pub ios_delivery: IosDelivery,
    pub ios_device: Option<String>,
    pub ios_team: &'a str,
    pub ios_profile: Option<crate::ios_profile::Profile>,
    pub ios_new_profile: Option<String>,
    pub portable_cpu: bool,
    pub clean_build: bool,
    pub ios_export_no_embed: bool,
    pub auto_cleanup: bool,
    pub base: Option<PathBuf>,
    pub keys: Option<PathBuf>,
    pub firmware: Option<PathBuf>,
    pub update: Option<PathBuf>,
    pub selected_mod: Option<String>,
    pub mods: &'a [ModEntry],
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RequestError {
    MissingInput,
    UnsupportedTarget,
}

pub fn build_request(inputs: RequestInputs) -> Result<BuildRequest, RequestError> {
    let (Some(base), Some(prod_keys)) = (inputs.base, inputs.keys) else {
        return Err(RequestError::MissingInput);
    };
    let target = target_name(inputs.target, inputs.arch).ok_or(RequestError::UnsupportedTarget)?;
    let mod_root = inputs
        .selected_mod
        .as_ref()
        .and_then(|name| inputs.mods.iter().find(|item| &item.name == name))
        .map(|item| item.root.clone());
    Ok(BuildRequest {
        target,
        ios_delivery: inputs.ios_delivery,
        ios_device: inputs.ios_device,
        ios_team: crate::ios_signing::valid_id(inputs.ios_team)
            .then(|| inputs.ios_team.to_string()),
        ios_profile: inputs.ios_profile,
        ios_new_profile: inputs.ios_new_profile,
        portable_cpu: inputs.portable_cpu,
        clean_build: inputs.clean_build,
        ios_export_no_embed: inputs.ios_export_no_embed,
        auto_cleanup: inputs.auto_cleanup,
        base,
        prod_keys,
        firmware: inputs.firmware,
        update: inputs.update,
        mod_root,
        mod_name: inputs.selected_mod,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn inputs<'a>(mods: &'a [ModEntry]) -> RequestInputs<'a> {
        RequestInputs {
            target: InstallTarget::Linux,
            arch: "x86_64",
            ios_delivery: IosDelivery::Device,
            ios_device: None,
            ios_team: "",
            ios_profile: None,
            ios_new_profile: None,
            portable_cpu: false,
            clean_build: false,
            ios_export_no_embed: false,
            auto_cleanup: true,
            base: Some(PathBuf::from("game")),
            keys: Some(PathBuf::from("prod.keys")),
            firmware: None,
            update: None,
            selected_mod: None,
            mods,
        }
    }

    fn entry(name: &str, has_exefs: bool) -> ModEntry {
        ModEntry {
            name: name.into(),
            root: PathBuf::from("mods").join(name),
            has_romfs: true,
            has_exefs,
        }
    }

    #[test]
    fn target_names_follow_the_host_architecture() {
        assert_eq!(target_name(InstallTarget::Mac, "aarch64"), Some("macos"));
        assert_eq!(target_name(InstallTarget::Linux, "x86_64"), Some("linux"));
        assert_eq!(
            target_name(InstallTarget::Windows, "x86_64"),
            Some("windows")
        );
        assert_eq!(
            target_name(InstallTarget::Windows, "aarch64"),
            Some("windows-arm64")
        );
        assert_eq!(target_name(InstallTarget::Ios, "aarch64"), Some("ios"));
        assert_eq!(target_name(InstallTarget::Android, "aarch64"), None);
    }

    #[test]
    fn request_needs_base_and_keys() {
        let mut missing = inputs(&[]);
        missing.keys = None;
        assert_eq!(build_request(missing), Err(RequestError::MissingInput));
        let mut android = inputs(&[]);
        android.target = InstallTarget::Android;
        assert_eq!(build_request(android), Err(RequestError::UnsupportedTarget));
    }

    #[test]
    fn request_carries_mod_root_and_only_a_valid_team() {
        let mods = [entry("alpha", false), entry("beta", true)];
        let mut input = inputs(&mods);
        input.selected_mod = Some("beta".into());
        input.ios_team = "not a team";
        let request = build_request(input).unwrap();
        assert_eq!(request.mod_root, Some(PathBuf::from("mods").join("beta")));
        assert_eq!(request.mod_name.as_deref(), Some("beta"));
        assert_eq!(request.ios_team, None);
        assert_eq!(request.target, "linux");
        let mut input = inputs(&mods);
        input.selected_mod = Some("gone".into());
        let request = build_request(input).unwrap();
        assert_eq!(request.mod_root, None);
        assert_eq!(request.mod_name.as_deref(), Some("gone"));
    }

    #[test]
    fn buildable_base_is_a_folder_or_an_xci_or_nsp_file() {
        let folder = std::env::temp_dir();
        assert!(base_is_buildable(&folder));
        assert!(base_is_buildable(Path::new("game.XCI")));
        assert!(base_is_buildable(Path::new("game.nsp")));
        assert!(!base_is_buildable(Path::new("game.zip")));
    }

    #[test]
    fn support_requires_a_buildable_base_and_a_buildable_mod() {
        let base = std::env::temp_dir();
        let mods = [entry("data", false), entry("code", true)];
        let supported = |mod_name: Option<&str>, base: Option<&Path>| {
            backend_supported(
                Platform::Linux,
                InstallTarget::Linux,
                "x86_64",
                base,
                mod_name,
                &mods,
            )
        };
        assert!(supported(None, Some(&base)));
        assert!(supported(Some("data"), Some(&base)));
        assert!(!supported(Some("code"), Some(&base)));
        assert!(!supported(Some("missing"), Some(&base)));
        assert!(!supported(None, None));
    }

    #[test]
    fn stages_depend_on_target_firmware_and_code_mod() {
        let linux = build_stages(InstallTarget::Linux, IosDelivery::Device, false, false);
        assert!(!linux.contains(&Stage::Firmware));
        assert!(!linux.contains(&Stage::Exefs));
        assert!(!linux.contains(&Stage::Shaders));
        assert!(!linux.contains(&Stage::Signing));
        let ios = build_stages(InstallTarget::Ios, IosDelivery::Device, true, true);
        assert!(ios.contains(&Stage::Firmware));
        assert!(ios.contains(&Stage::Exefs));
        assert!(ios.contains(&Stage::Shaders));
        assert!(ios.contains(&Stage::Signing));
        let ipa = build_stages(InstallTarget::Ios, IosDelivery::Ipa, false, false);
        assert!(!ipa.contains(&Stage::Signing));
    }

    #[test]
    fn code_mod_needs_the_mods_step_and_an_exefs_payload() {
        let mods = [entry("data", false), entry("code", true)];
        assert!(code_mod_selected(false, Some("code"), &mods));
        assert!(!code_mod_selected(true, Some("code"), &mods));
        assert!(!code_mod_selected(false, Some("data"), &mods));
        assert!(!code_mod_selected(false, None, &mods));
    }
}
