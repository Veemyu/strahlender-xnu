//! Build progress comes from backend events. An unknown total stays indeterminate.
use crate::{
    activity::{self, Activity},
    i18n::{Label, Language},
};
use std::{
    collections::VecDeque,
    time::{Duration, Instant},
};

/// A stage that reports nothing for this long is shown as "still working".
pub const SILENCE: Duration = Duration::from_secs(15);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stage {
    Source,
    Requirements,
    Firmware,
    Extract,
    Exefs,
    Signing,
    Shaders,
    Generate,
    Compile,
    Images,
    Runtime,
    Package,
    Install,
}

impl Stage {
    pub const ALL: [Self; 13] = [
        Self::Source,
        Self::Requirements,
        Self::Firmware,
        Self::Extract,
        Self::Exefs,
        Self::Signing,
        Self::Shaders,
        Self::Generate,
        Self::Compile,
        Self::Images,
        Self::Runtime,
        Self::Package,
        Self::Install,
    ];

    pub fn from_id(id: &str) -> Option<Self> {
        Some(match id {
            "source" => Self::Source,
            "prerequisites" => Self::Requirements,
            "firmware" => Self::Firmware,
            "extract" => Self::Extract,
            "exefs" => Self::Exefs,
            "signing" => Self::Signing,
            "shaders" => Self::Shaders,
            "eh_gen" => Self::Generate,
            "clang" => Self::Compile,
            "images" => Self::Images,
            "runtime" | "link" => Self::Runtime,
            "package" => Self::Package,
            "install" => Self::Install,
            _ => return None,
        })
    }

    pub fn index(self) -> usize {
        Self::ALL.iter().position(|item| *item == self).unwrap()
    }
}

#[derive(Debug, Clone, Copy, Default)]
pub struct StageProgress {
    pub completed: u64,
    pub total: u64,
    pub done: bool,
    pub started: bool,
}

impl StageProgress {
    pub fn fraction(self) -> f32 {
        if self.done {
            1.0
        } else if self.total > 0 {
            (self.completed.min(self.total) as f64 / self.total as f64) as f32
        } else {
            0.0
        }
    }
}

/// Bytes of a copy stage and the speed measured from them. Samples arrive once per copied portion, so the speed is
/// averaged over the last `WINDOW`; it is unknown until two samples at least `MIN_SPAN` apart exist.
#[derive(Debug, Clone, Default)]
pub struct Transfer {
    samples: VecDeque<(Instant, u64)>,
    pub completed: u64,
    pub total: u64,
}

impl Transfer {
    const WINDOW: Duration = Duration::from_secs(90);
    const MIN_SPAN: Duration = Duration::from_secs(3);

    pub fn record(&mut self, now: Instant, completed: u64, total: u64) {
        if completed < self.completed || total != self.total {
            self.samples.clear(); // a new copy started
        }
        self.completed = completed.min(total);
        self.total = total;
        self.samples.push_back((now, self.completed));
        while self
            .samples
            .front()
            .is_some_and(|(at, _)| now.saturating_duration_since(*at) > Self::WINDOW)
            && self.samples.len() > 2
        {
            self.samples.pop_front();
        }
    }

    /// Bytes per second, if enough has been measured.
    pub fn speed(&self) -> Option<f64> {
        let (first_at, first) = *self.samples.front()?;
        let (last_at, last) = *self.samples.back()?;
        let span = last_at.saturating_duration_since(first_at);
        (span >= Self::MIN_SPAN && last > first).then(|| (last - first) as f64 / span.as_secs_f64())
    }

    pub fn remaining(&self) -> Option<Duration> {
        let speed = self.speed()?;
        Some(Duration::from_secs_f64(
            self.total.saturating_sub(self.completed) as f64 / speed,
        ))
    }

    pub fn fraction(&self) -> Option<f32> {
        (self.total > 0).then(|| (self.completed as f64 / self.total as f64) as f32)
    }
}

pub fn format_bytes(bytes: u64) -> String {
    if bytes >= 1 << 30 {
        format!("{:.1} GB", bytes as f64 / (1u64 << 30) as f64)
    } else {
        format!("{:.0} MB", bytes as f64 / (1u64 << 20) as f64)
    }
}

pub fn format_speed(bytes_per_second: f64) -> String {
    let mb = bytes_per_second / (1u64 << 20) as f64;
    if mb >= 10.0 {
        format!("{mb:.0} MB/s")
    } else {
        format!("{mb:.1} MB/s")
    }
}

/// "<1 min", "7 min", "1 h 05 min": rounded up, because a countdown that ends early is friendlier than one that overruns.
pub fn format_duration(left: Duration) -> String {
    let minutes = left.as_secs().div_ceil(60);
    match minutes {
        0 | 1 => "<1 min".to_owned(),
        2..=89 => format!("{minutes} min"),
        _ => format!("{} h {:02} min", minutes / 60, minutes % 60),
    }
}

/// "4:07", "1:05:09": minutes and seconds, hours only when needed.
pub fn format_clock(elapsed: Duration) -> String {
    let seconds = elapsed.as_secs();
    match seconds / 3600 {
        0 => format!("{}:{:02}", seconds / 60, seconds % 60),
        hours => format!("{hours}:{:02}:{:02}", seconds / 60 % 60, seconds % 60),
    }
}

#[derive(Debug, Clone, Default)]
pub struct GeneratorProgress {
    pub module: String,
    pub phase: String,
    pub completed: u64,
    pub total: u64,
    pub modules_completed: u64,
    pub modules_total: u64,
}

#[derive(Debug, Clone)]
pub struct BuildProgress {
    pub stages: [StageProgress; Stage::ALL.len()],
    pub active: Stage,
    pub generator: GeneratorProgress,
    pub copy: Transfer,
    /// What the active stage is doing, the step it announced and the last log line nobody here knows.
    pub activity: Option<Activity>,
    pub step: Option<(u32, u32)>,
    pub detail: Option<String>,
    last_event: Option<Instant>,
    stage_started: [Option<Instant>; Stage::ALL.len()],
    started: Option<Instant>,
    finished: Option<Instant>,
}

/// The text under the stage title: the headline always names the current work.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivityText {
    pub headline: String,
    pub detail: Option<String>,
}

impl Default for BuildProgress {
    fn default() -> Self {
        Self {
            stages: [StageProgress::default(); Stage::ALL.len()],
            active: Stage::Source,
            generator: GeneratorProgress::default(),
            copy: Transfer::default(),
            activity: None,
            step: None,
            detail: None,
            last_event: None,
            stage_started: [None; Stage::ALL.len()],
            started: None,
            finished: None,
        }
    }
}

impl BuildProgress {
    pub fn fraction(&self, stage: Stage) -> f32 {
        let state = self.stages[stage.index()];
        if stage == Stage::Install
            && !state.done
            && let Some(bytes) = self.copy.fraction()
        {
            return bytes; // the copy is mostly a few large files: bytes show the real progress
        }
        let g = &self.generator;
        if stage != Stage::Generate || state.done || g.modules_total == 0 {
            return state.fraction();
        }
        let local = if g.phase == "emit" && g.total > 0 {
            g.completed.min(g.total) as f64 / g.total as f64
        } else {
            0.0
        };
        // Module-completion events can arrive immediately after the final function count.
        ((g.modules_completed as f64 + local).max(state.completed as f64) / g.modules_total as f64)
            .min(1.0) as f32
    }

    /// Time since the first step started; it stops counting at `finish`.
    pub fn elapsed(&self, now: Instant) -> Option<Duration> {
        let started = self.started?;
        Some(
            self.finished
                .unwrap_or(now)
                .saturating_duration_since(started),
        )
    }

    pub fn finish(&mut self, now: Instant) {
        if self.started.is_some() && self.finished.is_none() {
            self.finished = Some(now);
        }
    }

    pub fn step(&mut self, id: &str, status: &str) {
        let Some(stage) = Stage::from_id(id) else {
            return;
        };
        let now = Instant::now();
        self.started.get_or_insert(now);
        let item = &mut self.stages[stage.index()];
        if status == "started" {
            self.active = stage;
            item.started = true;
            self.stage_started[stage.index()].get_or_insert(now);
            self.enter(Activity::for_step(id, stage));
        } else if status == "complete" || status == "skipped" {
            item.started = true;
            item.done = true;
            if item.total > 0 {
                item.completed = item.total;
            }
        }
    }

    pub fn transfer(&mut self, id: &str, completed: u64, total: u64, now: Instant) {
        if Stage::from_id(id) == Some(Stage::Install) {
            self.copy.record(now, completed, total);
        }
    }

    pub fn count(&mut self, id: &str, completed: u64, total: u64) {
        let Some(stage) = Stage::from_id(id) else {
            return;
        };
        let now = Instant::now();
        self.started.get_or_insert(now);
        self.stage_started[stage.index()].get_or_insert(now);
        if self.active != stage {
            self.enter(Activity::for_stage(stage));
        }
        let item = &mut self.stages[stage.index()];
        item.started = true;
        item.total = total;
        // Without a total (shader translation) the number is only a count of what is done so far.
        item.completed = if total == 0 {
            completed
        } else {
            completed.min(total)
        };
        self.active = stage;
    }

    fn enter(&mut self, activity: Activity) {
        self.activity = Some(activity);
        self.step = None;
        self.detail = None;
    }

    /// Pretends that `by` more time has passed since everything so far (preview scenes).
    pub fn shift_clock(&mut self, by: Duration) {
        let back = |at: &mut Option<Instant>| *at = at.and_then(|at| at.checked_sub(by)).or(*at);
        back(&mut self.started);
        back(&mut self.last_event);
        self.stage_started.iter_mut().for_each(back);
    }

    /// Any event of the backend proves it is alive.
    pub fn touch(&mut self, now: Instant) {
        self.last_event = Some(now);
    }

    /// A log line of the backend can name the current work (known lines) or be shown as it is (unknown lines).
    pub fn note_log(&mut self, level: &str, message: &str) {
        if level == "error" || self.stages[self.active.index()].done {
            return;
        }
        let seen = activity::observe(self.active, message);
        if let Some(activity) = seen.activity {
            self.activity = Some(activity);
            self.detail = None;
        }
        if seen.step.is_some() {
            self.step = seen.step;
        }
        if seen.detail.is_some() {
            self.detail = seen.detail;
        }
    }

    /// What to show under the stage title while the backend runs; `None` once the stage is done.
    pub fn activity_text(&self, language: Language, now: Instant) -> Option<ActivityText> {
        let stage = self.active;
        let state = self.stages[stage.index()];
        if state.done {
            return None;
        }
        let activity = self.activity.unwrap_or_else(|| Activity::for_stage(stage));
        let counted = |label: Label| {
            language
                .t(label)
                .replacen("{}", &state.completed.to_string(), 1)
                .replacen("{}", &state.total.to_string(), 1)
        };
        let mut headline = match activity {
            Activity::Compile if state.total > 0 => counted(Label::ActCompileCount),
            Activity::ShadersCompile if state.total > 0 => counted(Label::ActShadersCompileCount),
            _ => language.t(activity.label()).to_owned(),
        };
        let silent = self
            .last_event
            .is_some_and(|at| now.saturating_duration_since(at) >= SILENCE);
        if silent {
            let in_stage = self.stage_started[stage.index()]
                .map(|at| format_clock(now.saturating_duration_since(at)))
                .unwrap_or_default();
            headline = language
                .t(Label::ActStillWorking)
                .replacen("{}", &headline, 1)
                .replacen("{}", &in_stage, 1);
        }
        Some(ActivityText {
            headline,
            detail: self.detail.clone(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_clock_shows_minutes_and_seconds() {
        assert_eq!(format_clock(Duration::from_secs(7)), "0:07");
        assert_eq!(format_clock(Duration::from_secs(247)), "4:07");
        assert_eq!(format_clock(Duration::from_secs(3909)), "1:05:09");
    }

    #[test]
    fn elapsed_time_starts_with_the_first_step_and_stops_at_the_end() {
        let mut progress = BuildProgress::default();
        let now = Instant::now();
        assert_eq!(progress.elapsed(now), None);
        progress.step("source", "started");
        let later = now + Duration::from_secs(90);
        assert!(progress.elapsed(later).unwrap() >= Duration::from_secs(89));
        progress.finish(later);
        let much_later = later + Duration::from_secs(500);
        assert_eq!(progress.elapsed(much_later), progress.elapsed(later));
    }

    #[test]
    fn every_declared_stage_has_storage_including_installation() {
        let mut progress = BuildProgress::default();
        for (index, stage) in Stage::ALL.into_iter().enumerate() {
            assert_eq!(stage.index(), index);
            assert_eq!(progress.fraction(stage), 0.0);
        }
        for id in [
            "source",
            "prerequisites",
            "firmware",
            "extract",
            "exefs",
            "signing",
            "shaders",
            "eh_gen",
            "clang",
            "images",
            "runtime",
            "package",
            "install",
        ] {
            progress.step(id, "started");
            progress.count(id, 1, 2);
            progress.step(id, "complete");
        }
        assert!(progress.stages.iter().all(|s| s.done));
    }

    #[test]
    fn native_progress_never_rewinds_at_module_boundaries() {
        let mut p = BuildProgress::default();
        p.step("eh_gen", "started");
        p.generator = GeneratorProgress {
            module: "main".into(),
            phase: "analyze".into(),
            modules_total: 5,
            ..Default::default()
        };
        assert_eq!(p.fraction(Stage::Generate), 0.0);
        p.generator.phase = "emit".into();
        p.generator.total = 2000;
        p.generator.completed = 1000;
        assert!((p.fraction(Stage::Generate) - 0.1).abs() < 0.001);
        p.generator.completed = 2000;
        assert!((p.fraction(Stage::Generate) - 0.2).abs() < 0.001);
        p.count("eh_gen", 1, 5);
        assert!((p.fraction(Stage::Generate) - 0.2).abs() < 0.001);
        p.generator = GeneratorProgress {
            module: "sdk".into(),
            phase: "analyze".into(),
            modules_completed: 1,
            modules_total: 5,
            ..Default::default()
        };
        assert!((p.fraction(Stage::Generate) - 0.2).abs() < 0.001);
        p.step("eh_gen", "complete");
        assert_eq!(p.fraction(Stage::Generate), 1.0);
    }

    #[test]
    fn compilation_count_is_real_bounded_and_separate_from_generator() {
        let mut progress = BuildProgress::default();
        progress.step("eh_gen", "started");
        progress.count("eh_gen", 2, 4);
        assert_eq!(progress.active, Stage::Generate);
        assert_eq!(progress.stages[Stage::Generate.index()].fraction(), 0.5);
        progress.step("eh_gen", "complete");
        progress.step("clang", "started");
        progress.count("clang", 2368, 2369);
        assert_eq!(progress.stages[Stage::Compile.index()].completed, 2368);
        assert!(progress.stages[Stage::Compile.index()].fraction() < 1.0);
        assert_eq!(progress.stages[Stage::Generate.index()].fraction(), 1.0);
    }

    #[test]
    fn transfer_speed_and_remaining_time_come_from_the_copied_bytes() {
        let start = Instant::now();
        let mb = 1u64 << 20;
        let mut copy = Transfer::default();
        copy.record(start, 0, 1000 * mb);
        assert_eq!(copy.speed(), None); // nothing measured yet
        copy.record(start + Duration::from_secs(1), 20 * mb, 1000 * mb);
        assert_eq!(copy.speed(), None); // too short a span to trust
        copy.record(start + Duration::from_secs(10), 200 * mb, 1000 * mb);
        assert_eq!(copy.speed().map(|s| (s / mb as f64).round()), Some(20.0));
        assert_eq!(copy.remaining(), Some(Duration::from_secs(40)));
        assert_eq!(copy.fraction(), Some(0.2));
    }

    #[test]
    fn an_old_transfer_is_forgotten_when_a_new_copy_starts() {
        let start = Instant::now();
        let mut copy = Transfer::default();
        copy.record(start, 0, 100);
        copy.record(start + Duration::from_secs(10), 100, 100);
        copy.record(start + Duration::from_secs(20), 0, 500); // another copy
        assert_eq!(copy.speed(), None);
        assert_eq!((copy.completed, copy.total), (0, 500));
    }

    #[test]
    fn the_install_stage_follows_bytes_not_files() {
        let start = Instant::now();
        let mut progress = BuildProgress::default();
        progress.step("install", "started");
        progress.count("install", 10, 1000); // 1 % of the files
        progress.transfer("install", 600, 1000, start); // but 60 % of the bytes
        assert!((progress.fraction(Stage::Install) - 0.6).abs() < 1e-6);
        progress.step("install", "complete");
        assert_eq!(progress.fraction(Stage::Install), 1.0);
    }

    fn english(progress: &BuildProgress, now: Instant) -> ActivityText {
        progress.activity_text(Language::English, now).unwrap()
    }

    #[test]
    fn every_stage_names_its_work_from_the_moment_it_starts() {
        let mut progress = BuildProgress::default();
        let now = Instant::now();
        for stage in Stage::ALL {
            let id = [
                "source",
                "prerequisites",
                "firmware",
                "extract",
                "exefs",
                "signing",
                "shaders",
                "eh_gen",
                "clang",
                "images",
                "runtime",
                "package",
                "install",
            ][stage.index()];
            progress.step(id, "started");
            let text = english(&progress, now);
            assert!(!text.headline.is_empty() && text.detail.is_none(), "{id}");
            assert_eq!(progress.activity, Some(Activity::for_stage(stage)));
        }
        progress.step("link", "started"); // Windows links in a step of its own, still part of the runtime stage
        assert_eq!(progress.active, Stage::Runtime);
        assert_eq!(
            english(&progress, now).headline,
            "Linking the game executable"
        );
    }

    #[test]
    fn compilation_and_shader_counters_are_part_of_the_activity() {
        let mut progress = BuildProgress::default();
        let now = Instant::now();
        progress.step("clang", "started");
        progress.count("clang", 3, 10);
        assert_eq!(
            english(&progress, now).headline,
            "Compiling objects: 3 of 10"
        );
        progress.step("shaders", "started");
        progress.note_log("diagnostic", "shaders: translating");
        progress.count("shaders", 120, 0); // translating: written so far, the total is unknown
        assert_eq!(progress.stages[Stage::Shaders.index()].completed, 120);
        assert_eq!(progress.fraction(Stage::Shaders), 0.0);
        assert_eq!(english(&progress, now).headline, "Translating shaders");
        progress.note_log(
            "diagnostic",
            "shaders: compiling the Metal libraries for macosx",
        );
        progress.count("shaders", 5, 2739);
        assert_eq!(
            english(&progress, now).headline,
            "Compiling Metal libraries: 5 of 2739"
        );
    }

    #[test]
    fn a_known_line_replaces_the_activity_and_an_unknown_one_is_shown_below_it() {
        let mut progress = BuildProgress::default();
        let now = Instant::now();
        progress.step("extract", "started");
        progress.note_log("diagnostic", "1/5 unpack the game containers");
        progress.note_log(
            "diagnostic",
            "    prod.keys: master_key_00 to master_key_15",
        );
        let text = english(&progress, now);
        assert_eq!(text.headline, "Unpacking the game container (XCI or NSP)");
        assert!(text.detail.unwrap().starts_with("prod.keys:"));
        progress.note_log("diagnostic", "2/5 classify NCAs (content type, title ID)");
        let text = english(&progress, now);
        assert_eq!(
            text.headline,
            "Identifying the game files (content type, title ID)"
        );
        assert_eq!(text.detail, None);
        assert_eq!(progress.step, Some((2, 5)));
        // Errors are reported elsewhere, and a finished stage ignores late lines.
        progress.note_log("error", "something failed");
        assert_eq!(english(&progress, now).detail, None);
        progress.step("extract", "complete");
        progress.note_log("diagnostic", "3/5 title keys");
        assert_eq!(progress.step, Some((2, 5)));
        assert_eq!(progress.activity_text(Language::English, now), None);
    }

    #[test]
    fn a_quiet_backend_shows_still_working_with_the_last_activity_and_the_time_in_the_stage() {
        let mut progress = BuildProgress::default();
        progress.step("extract", "started");
        let now = Instant::now();
        progress.note_log("diagnostic", "    recording the SHA-256 of the game files");
        progress.touch(now);
        let quiet = SILENCE - Duration::from_secs(1);
        assert_eq!(
            english(&progress, now + quiet).headline,
            "Verifying the game files (SHA-256)"
        );
        let text = english(&progress, now + Duration::from_secs(200));
        assert_eq!(
            text.headline,
            "Still working: Verifying the game files (SHA-256) (3:20 in this step)"
        );
        progress.touch(now + Duration::from_secs(200));
        assert_eq!(
            english(&progress, now + Duration::from_secs(201)).headline,
            "Verifying the game files (SHA-256)"
        );
    }

    #[test]
    fn sizes_speeds_and_times_are_short_and_readable() {
        assert_eq!(format_bytes(5 << 20), "5 MB");
        assert_eq!(format_bytes(5 << 30), "5.0 GB");
        assert_eq!(format_speed(24.4 * (1u64 << 20) as f64), "24 MB/s");
        assert_eq!(format_speed(2.46 * (1u64 << 20) as f64), "2.5 MB/s");
        assert_eq!(format_duration(Duration::from_secs(20)), "<1 min");
        assert_eq!(format_duration(Duration::from_secs(61)), "2 min");
        assert_eq!(format_duration(Duration::from_secs(7 * 60)), "7 min");
        assert_eq!(format_duration(Duration::from_secs(66 * 60 + 5)), "67 min");
        assert_eq!(
            format_duration(Duration::from_secs(95 * 60 + 5)),
            "1 h 36 min"
        );
    }
}
