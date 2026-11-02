//! Programs the installer starts must not open a console window on Windows (the installer itself has none).
//! `CREATE_NO_WINDOW` hides the console a console program would otherwise get; pipes and exit codes work as before.

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

pub trait Hidden {
    /// Starts the program without a console window (nothing on other systems).
    fn hidden(&mut self) -> &mut Self;
}

impl Hidden for std::process::Command {
    fn hidden(&mut self) -> &mut Self {
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            self.creation_flags(CREATE_NO_WINDOW);
        }
        self
    }
}

impl Hidden for tokio::process::Command {
    fn hidden(&mut self) -> &mut Self {
        #[cfg(windows)]
        {
            self.creation_flags(CREATE_NO_WINDOW);
        }
        self
    }
}

/// A GUI program started from a terminal (`--cli`, `--check-runtime` ...) should still print there: it attaches to the console of the
/// process that started it. Without a parent console (double click) this does nothing and no window appears.
pub fn attach_parent_console() {
    #[cfg(windows)]
    {
        unsafe extern "system" {
            fn AttachConsole(process_id: u32) -> i32;
        }
        const ATTACH_PARENT_PROCESS: u32 = u32::MAX;
        unsafe {
            AttachConsole(ATTACH_PARENT_PROCESS);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_hidden_command_still_runs_and_reports_its_output() {
        let program = if cfg!(windows) { "cmd" } else { "sh" };
        let arguments: &[&str] = if cfg!(windows) {
            &["/C", "echo hidden"]
        } else {
            &["-c", "echo hidden"]
        };
        let output = std::process::Command::new(program)
            .args(arguments)
            .hidden()
            .output()
            .unwrap();
        assert!(output.status.success());
        assert!(String::from_utf8_lossy(&output.stdout).contains("hidden"));
    }
}
