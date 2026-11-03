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

/// A standard handle that points nowhere: a window program started from a terminal has none unless the caller redirected it.
#[cfg_attr(not(windows), allow(dead_code))]
fn handle_is_missing(handle: isize) -> bool {
    handle == 0 || handle == -1
}

/// A GUI program started from a terminal (`--cli`, `--check-runtime` ...) should still print there: it attaches to the console of the
/// process that started it. Without a parent console (double click) this does nothing and no window appears.
/// Attaching alone does not give the process stdout and stderr, so a missing handle is bound to the console; a handle the caller
/// redirected to a file or pipe is left alone (JSON lines on stdout keep working when captured).
pub fn attach_parent_console() {
    #[cfg(windows)]
    {
        use std::ffi::c_void;
        unsafe extern "system" {
            fn AttachConsole(process_id: u32) -> i32;
            fn GetStdHandle(kind: u32) -> isize;
            fn SetStdHandle(kind: u32, handle: isize) -> i32;
            fn CreateFileW(
                name: *const u16,
                access: u32,
                share: u32,
                security: *const c_void,
                disposition: u32,
                flags: u32,
                template: isize,
            ) -> isize;
        }
        const ATTACH_PARENT_PROCESS: u32 = u32::MAX;
        const STD_OUTPUT_HANDLE: u32 = -11i32 as u32;
        const STD_ERROR_HANDLE: u32 = -12i32 as u32;
        const GENERIC_READ_WRITE: u32 = 0xC000_0000;
        const FILE_SHARE_READ_WRITE: u32 = 3;
        const OPEN_EXISTING: u32 = 3;
        unsafe {
            if AttachConsole(ATTACH_PARENT_PROCESS) == 0 {
                return;
            }
            let console: Vec<u16> = "CONOUT$\0".encode_utf16().collect();
            for kind in [STD_OUTPUT_HANDLE, STD_ERROR_HANDLE] {
                if !handle_is_missing(GetStdHandle(kind)) {
                    continue;
                }
                let handle = CreateFileW(
                    console.as_ptr(),
                    GENERIC_READ_WRITE,
                    FILE_SHARE_READ_WRITE,
                    std::ptr::null(),
                    OPEN_EXISTING,
                    0,
                    0,
                );
                if !handle_is_missing(handle) {
                    SetStdHandle(kind, handle);
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_null_and_invalid_handles_are_rebound_to_the_console() {
        assert!(handle_is_missing(0));
        assert!(handle_is_missing(-1));
        assert!(!handle_is_missing(0x1a4));
    }

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
