//! Build progress comes from backend events. An unknown total stays indeterminate.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stage {
    Source,
    Requirements,
    Extract,
    Exefs,
    Generate,
    Compile,
    Images,
    Runtime,
    Package,
    Install,
}

impl Stage {
    pub const ALL: [Self; 10] = [
        Self::Source,
        Self::Requirements,
        Self::Extract,
        Self::Exefs,
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
            "extract" => Self::Extract,
            "exefs" => Self::Exefs,
            "eh_gen" => Self::Generate,
            "clang" => Self::Compile,
            "images" => Self::Images,
            "runtime" => Self::Runtime,
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

#[derive(Debug, Clone)]
pub struct BuildProgress {
    pub stages: [StageProgress; 10],
    pub active: Stage,
}

impl Default for BuildProgress {
    fn default() -> Self {
        Self {
            stages: [StageProgress::default(); 10],
            active: Stage::Source,
        }
    }
}

impl BuildProgress {
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
