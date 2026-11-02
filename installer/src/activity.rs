//! What the build is doing right now, in words. It is derived from the backend events that already exist (steps, counters and
//! log lines), so every released backend keeps working: a line this module does not know is shown as it is.
use crate::{i18n::Label, progress::Stage};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Activity {
    Source,
    Requirements,
    Firmware,
    PrepareGame,
    Unpack,
    UnpackUpdate,
    Classify,
    TitleKeys,
    ExtractFs,
    ReadMeta,
    Hashing,
    Exefs,
    Signing,
    ShadersRead,
    ShadersBuild,
    ShadersTranslate,
    ShadersCompile,
    Generate,
    Compile,
    Images,
    Runtime,
    Link,
    Package,
    Install,
}

impl Activity {
    pub fn label(self) -> Label {
        match self {
            Self::Source => Label::StepSource,
            Self::Requirements => Label::CheckingRequirements,
            Self::Firmware => Label::ActFirmware,
            Self::PrepareGame => Label::ActPrepareGame,
            Self::Unpack => Label::ActUnpack,
            Self::UnpackUpdate => Label::ActUnpackUpdate,
            Self::Classify => Label::ActClassify,
            Self::TitleKeys => Label::ActTitleKeys,
            Self::ExtractFs => Label::ActExtractFs,
            Self::ReadMeta => Label::ActReadMeta,
            Self::Hashing => Label::ActHashing,
            Self::Exefs => Label::ActExefs,
            Self::Signing => Label::ActSigning,
            Self::ShadersRead => Label::ActShadersRead,
            Self::ShadersBuild => Label::ActShadersBuild,
            Self::ShadersTranslate => Label::ActShadersTranslate,
            Self::ShadersCompile => Label::ActShadersCompile,
            Self::Generate => Label::ActGenerate,
            Self::Compile => Label::ActCompile,
            Self::Images => Label::ActImages,
            Self::Runtime => Label::ActRuntime,
            Self::Link => Label::ActLink,
            Self::Package => Label::ActPackage,
            Self::Install => Label::ActInstall,
        }
    }

    pub fn for_stage(stage: Stage) -> Self {
        match stage {
            Stage::Source => Self::Source,
            Stage::Requirements => Self::Requirements,
            Stage::Firmware => Self::Firmware,
            Stage::Extract => Self::PrepareGame,
            Stage::Exefs => Self::Exefs,
            Stage::Signing => Self::Signing,
            Stage::Shaders => Self::ShadersRead,
            Stage::Generate => Self::Generate,
            Stage::Compile => Self::Compile,
            Stage::Images => Self::Images,
            Stage::Runtime => Self::Runtime,
            Stage::Package => Self::Package,
            Stage::Install => Self::Install,
        }
    }

    /// The backend step id tells more than the stage: Windows reports linking as its own step.
    pub fn for_step(id: &str, stage: Stage) -> Self {
        if id == "link" {
            Self::Link
        } else {
            Self::for_stage(stage)
        }
    }
}

#[derive(Debug, Default, PartialEq, Eq)]
pub struct Observation {
    pub activity: Option<Activity>,
    /// "Step n of m" of a stage that announces its steps (`1/5 ...` lines of the game extraction).
    pub step: Option<(u32, u32)>,
    /// A line nobody here knows: it is shown as it is.
    pub detail: Option<String>,
}

const MAX_LINE: usize = 110;

/// One readable line: control characters and runs of blanks collapse, a leading `[HH:MM:SS]` is dropped, and a long
/// line ends in an ellipsis.
pub fn one_line(text: &str) -> String {
    let flat: String = text
        .chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ");
    let flat = match flat
        .strip_prefix('[')
        .and_then(|rest| rest.split_once("] "))
    {
        Some((clock, rest))
            if clock.len() <= 8 && clock.chars().all(|c| c.is_ascii_digit() || c == ':') =>
        {
            rest.to_owned()
        }
        _ => flat,
    };
    if flat.chars().count() > MAX_LINE {
        let mut cut: String = flat.chars().take(MAX_LINE - 1).collect();
        cut.push('\u{2026}');
        cut
    } else {
        flat
    }
}

/// `1/5 unpack ...` is step 1 of 5.
fn step_marker(line: &str) -> Option<(u32, u32)> {
    let bytes = line.as_bytes();
    match bytes {
        [n @ b'1'..=b'9', b'/', m @ b'1'..=b'9', b' ', ..] => {
            Some(((n - b'0') as u32, (m - b'0') as u32))
        }
        _ => None,
    }
}

/// Lines that only repeat a counter the progress bar already shows.
fn is_counter(line: &str) -> bool {
    line.starts_with("extract progress ")
        || line.starts_with("Firmware NCA scan: ")
        || line.contains(": progress ") && line.contains(" files ")
        || line.contains(": scan round ")
}

pub fn observe(stage: Stage, message: &str) -> Observation {
    let line = one_line(message);
    if line.is_empty() || is_counter(&line) {
        return Observation::default();
    }
    let known = |activity| Observation {
        activity: Some(activity),
        ..Default::default()
    };
    match stage {
        Stage::Extract => {
            if let Some((n, total)) = step_marker(&line).filter(|(n, total)| *total == 5 && *n <= 5)
            {
                return Observation {
                    activity: Some(match n {
                        1 => Activity::Unpack,
                        2 => Activity::Classify,
                        3 => Activity::TitleKeys,
                        4 => Activity::ExtractFs,
                        _ => Activity::ReadMeta,
                    }),
                    step: Some((n, total)),
                    detail: None,
                };
            }
            if line.contains("checking the earlier extraction")
                || line.contains("recording the SHA-256")
            {
                return known(Activity::Hashing);
            }
            if line.contains("unpacking the update") {
                return known(Activity::UnpackUpdate);
            }
        }
        Stage::Shaders => {
            if let Some(rest) = line.strip_prefix("shaders: ") {
                let activity = [
                    ("reading the shader programs", Activity::ShadersRead),
                    ("building the translator", Activity::ShadersBuild),
                    ("translating", Activity::ShadersTranslate),
                    ("compiling the Metal libraries", Activity::ShadersCompile),
                ]
                .into_iter()
                .find(|(prefix, _)| rest.starts_with(prefix))
                .map(|(_, activity)| activity);
                if let Some(activity) = activity {
                    return known(activity);
                }
            }
        }
        _ => {}
    }
    Observation {
        detail: Some(line),
        ..Default::default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_five_steps_of_the_game_extraction_name_their_activity() {
        let expected = [
            ("1/5 unpack the game containers", Activity::Unpack),
            (
                "2/5 classify NCAs (content type, title ID)",
                Activity::Classify,
            ),
            ("3/5 title keys (ticket or title.keys)", Activity::TitleKeys),
            (
                "4/5 extract ExeFS and RomFS (the update applied to the base NCA)",
                Activity::ExtractFs,
            ),
            ("5/5 version, icons and manifest", Activity::ReadMeta),
        ];
        for (index, (line, activity)) in expected.into_iter().enumerate() {
            let seen = observe(Stage::Extract, line);
            assert_eq!(seen.activity, Some(activity), "{line}");
            assert_eq!(seen.step, Some((index as u32 + 1, 5)));
            assert_eq!(seen.detail, None);
        }
    }

    #[test]
    fn silent_hashing_is_announced_by_its_log_lines() {
        for line in [
            "    recording the SHA-256 of the game files",
            "    checking the earlier extraction (SHA-256 of the game files)",
        ] {
            assert_eq!(
                observe(Stage::Extract, line).activity,
                Some(Activity::Hashing)
            );
        }
        assert_eq!(
            observe(Stage::Extract, "    unpacking the update (NSP)").activity,
            Some(Activity::UnpackUpdate)
        );
    }

    #[test]
    fn the_shader_phases_follow_the_bootstrap_lines() {
        for (line, activity) in [
            (
                "shaders: reading the shader programs of the game",
                Activity::ShadersRead,
            ),
            ("shaders: building the translator", Activity::ShadersBuild),
            ("shaders: translating", Activity::ShadersTranslate),
            (
                "shaders: compiling the Metal libraries for macosx",
                Activity::ShadersCompile,
            ),
        ] {
            assert_eq!(observe(Stage::Shaders, line).activity, Some(activity));
        }
    }

    #[test]
    fn an_unknown_line_is_kept_as_one_short_sanitised_line() {
        let seen = observe(
            Stage::Extract,
            "[12:03:44] Original icons:\t9   language variants\r",
        );
        assert_eq!(seen.activity, None);
        assert_eq!(
            seen.detail.as_deref(),
            Some("Original icons: 9 language variants")
        );
        let long = observe(Stage::Compile, &"x".repeat(500)).detail.unwrap();
        assert_eq!(long.chars().count(), MAX_LINE);
        assert!(long.ends_with('\u{2026}'));
        // The same text in another stage is not a step marker of the extraction.
        assert_eq!(observe(Stage::Compile, "1/5 something").step, None);
    }

    #[test]
    fn counter_lines_do_not_replace_the_activity() {
        for line in [
            "extract progress 420",
            "Firmware NCA scan: 10/200",
            "main: progress 100/200 files 200",
            "rtld: scan round 1 progress 42/42",
            "   ",
        ] {
            assert_eq!(
                observe(Stage::Extract, line),
                Observation::default(),
                "{line}"
            );
        }
    }
}
