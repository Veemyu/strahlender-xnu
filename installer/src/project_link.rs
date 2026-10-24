//! The destination is fixed, independent of game metadata and user input.
pub const REPOSITORY: &str = "https://github.com/Veemyu/strahlender-xnu";

pub fn open() -> Result<(), ()> {
    #[cfg(target_os = "macos")]
    let mut command = std::process::Command::new("open");
    #[cfg(target_os = "linux")]
    let mut command = std::process::Command::new("xdg-open");
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut command = std::process::Command::new("rundll32.exe");
        command.arg("url.dll,FileProtocolHandler");
        command
    };
    command
        .arg(REPOSITORY)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map_err(|_| ())?
        .success()
        .then_some(())
        .ok_or(())
}
