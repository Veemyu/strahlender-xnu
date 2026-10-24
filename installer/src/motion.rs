//! A damped spring for display only. It never invents completed backend work.
#[derive(Default)]
pub struct ProgressMotion {
    pub value: f32,
    velocity: f32,
}

impl ProgressMotion {
    pub fn snap(&mut self, value: f32) {
        self.value = value;
        self.velocity = 0.0;
    }

    pub fn advance(&mut self, target: f32, dt: f32) {
        // Small fixed substeps keep the spring stable across dropped frames.
        let dt = dt.clamp(0.0, 0.05);
        let steps = (dt / 0.004).ceil().max(1.0) as usize;
        let step = dt / steps as f32;
        for _ in 0..steps {
            self.velocity += (400.0 * (target - self.value) - 36.0 * self.velocity) * step;
            self.value += self.velocity * step;
            if self.value > target {
                self.value = target;
                self.velocity = 0.0;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn spring_is_smooth_bounded_and_independent_of_frame_rate() {
        for fps in [30, 60, 120] {
            let mut motion = ProgressMotion::default();
            motion.advance(0.5, 1.0 / fps as f32);
            assert!(motion.value > 0.0 && motion.value < 0.5);
            for _ in 0..fps {
                let previous = motion.value;
                motion.advance(0.5, 1.0 / fps as f32);
                assert!(motion.value >= previous && motion.value <= 0.5);
            }
            assert!((motion.value - 0.5).abs() < 0.001);
        }
    }
}
