//! Build progress comes from backend events. An unknown total stays indeterminate.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stage {
    Source,
    Requirements,
    Firmware,
    Extract,
    Exefs,
    Signing,
    Generate,
    Compile,
    Images,
    Runtime,
    Package,
    Install,
}

impl Stage {
    pub const ALL: [Self; 12] = [
        Self::Source,
        Self::Requirements,
        Self::Firmware,
        Self::Extract,
        Self::Exefs,
        Self::Signing,
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
}

impl Default for BuildProgress {
    fn default() -> Self {
        Self {
            stages: [StageProgress::default(); Stage::ALL.len()],
            active: Stage::Source,
            generator: GeneratorProgress::default(),
        }
    }
}

impl BuildProgress {
    pub fn fraction(&self, stage: Stage) -> f32 {
        let state = self.stages[stage.index()];
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

    pub fn step(&mut self, id: &str, status: &str) {
        let Some(stage) = Stage::from_id(id) else {
            return;
        };
        let item = &mut self.stages[stage.index()];
        if status == "started" {
            self.active = stage;
            item.started = true;
        } else if status == "complete" || status == "skipped" {
            item.started = true;
            item.done = true;
            if item.total > 0 {
                item.completed = item.total;
            }
        }
    }

    pub fn count(&mut self, id: &str, completed: u64, total: u64) {
        let Some(stage) = Stage::from_id(id) else {
            return;
        };
        let item = &mut self.stages[stage.index()];
        item.started = true;
        item.total = total;
        item.completed = completed.min(total);
        self.active = stage;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
}
