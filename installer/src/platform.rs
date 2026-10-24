//! Simulation changes presentation only, never OS APIs or emulator search paths.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Platform {
    Mac,
    Windows,
    Linux,
}

impl Platform {
    pub fn native() -> Self {
        if cfg!(target_os = "macos") {
            Self::Mac
        } else if cfg!(target_os = "windows") {
            Self::Windows
        } else {
            Self::Linux
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "mac" | "macos" => Some(Self::Mac),
            "windows" => Some(Self::Windows),
            "linux" => Some(Self::Linux),
            _ => None,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Mac => "Mac",
            Self::Windows => "Windows",
            Self::Linux => "Linux",
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct Options {
    pub demo: bool,
    pub capture: Option<std::path::PathBuf>,
    pub platform: Option<Platform>,
    pub scenes: Vec<&'static str>,
}

impl Options {
    pub fn parse(args: &[String]) -> Result<Self, &'static str> {
        let mut options = Self::default();
        let mut args = args.iter();
        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--demo" if !options.demo => options.demo = true,
                "--capture-dir" if options.capture.is_none() => {
                    options.capture = Some(args.next().ok_or("Missing capture directory")?.into())
                }
                "--platform" if options.platform.is_none() => {
                    options.platform = Some(
                        Platform::parse(args.next().ok_or("Missing platform")?)
                            .ok_or("Platform must be mac, windows or linux")?,
                    )
                }
                "--scenes" if options.scenes.is_empty() => {
                    let scenes = args.next().ok_or("Missing capture scenes")?;
                    options.scenes = if scenes == "all" {
                        crate::capture::SCENARIOS.to_vec()
                    } else {
                        scenes
                            .split(',')
                            .map(|name| {
                                crate::capture::SCENARIOS
                                    .iter()
                                    .copied()
                                    .find(|scene| *scene == name)
                                    .ok_or("Unknown capture scene")
                            })
                            .collect::<Result<Vec<_>, _>>()?
                    };
                }
                _ => return Err("Unknown or repeated argument"),
            }
        }
        if options.demo && options.capture.is_some() {
            return Err("Choose demo or capture mode");
        }
        if !options.scenes.is_empty() && options.capture.is_none() {
            return Err("--scenes requires --capture-dir");
        }
        if options.platform.is_some() && !options.demo && options.capture.is_none() {
            return Err("--platform requires --demo or --capture-dir");
        }
        Ok(options)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn args(values: &[&str]) -> Vec<String> {
        values.iter().map(|s| (*s).into()).collect()
    }
    #[test]
    fn platform_override_requires_simulation_and_valid_arguments() {
        assert!(Options::parse(&args(&["--platform", "windows"])).is_err());
        assert!(Options::parse(&args(&["--demo", "--platform", "unknown"])).is_err());
        assert!(Options::parse(&args(&["--demo", "--capture-dir", "tmp"])).is_err());
        for platform in ["mac", "windows", "linux"] {
            assert!(Options::parse(&args(&["--demo", "--platform", platform])).is_ok());
            assert!(
                Options::parse(&args(&["--capture-dir", "tmp", "--platform", platform])).is_ok()
            );
        }
    }

    #[test]
    fn captures_require_explicit_valid_scene_selection() {
        assert!(Options::parse(&args(&["--demo", "--scenes", "target"])).is_err());
        assert!(Options::parse(&args(&["--capture-dir", "tmp", "--scenes", "unknown"])).is_err());
        let options = Options::parse(&args(&[
            "--capture-dir",
            "tmp",
            "--scenes",
            "target-ios,setup-ios",
        ]))
        .unwrap();
        assert_eq!(options.scenes, vec!["target-ios", "setup-ios"]);
        let options = Options::parse(&args(&["--capture-dir", "tmp"])).unwrap();
        let capture = crate::capture::Capture::new(options.capture.unwrap(), options.scenes);
        assert_eq!(capture.scenes, vec!["target"]);
    }
}
