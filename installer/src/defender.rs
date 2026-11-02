//! Windows Defender's real-time protection scans every newly written file once, which is most of the waiting after the game's data is
//! unpacked and copied. The window explains that while it happens; nothing here changes any setting.

/// `Some(true)` when Windows Defender's real-time protection is on, `Some(false)` when it is off, `None` when it cannot be read
/// (another virus scanner, a policy, not Windows).
pub fn realtime_protection() -> Option<bool> {
    status()
}

#[cfg(windows)]
fn status() -> Option<bool> {
    use crate::process::Hidden;
    let output = std::process::Command::new("powershell")
        .hidden()
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "(Get-MpComputerStatus -ErrorAction Stop).RealTimeProtectionEnabled",
        ])
        .stdin(std::process::Stdio::null())
        .output()
        .ok()?;
    parse(&String::from_utf8_lossy(&output.stdout))
}

#[cfg(not(windows))]
fn status() -> Option<bool> {
    None
}

#[allow(dead_code)] // only called on Windows, but tested everywhere
fn parse(text: &str) -> Option<bool> {
    match text.trim().to_ascii_lowercase().as_str() {
        "true" => Some(true),
        "false" => Some(false),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn the_status_text_of_powershell_is_read_strictly() {
        assert_eq!(super::parse("True\r\n"), Some(true));
        assert_eq!(super::parse(" false "), Some(false));
        assert_eq!(super::parse(""), None);
        assert_eq!(super::parse("Get-MpComputerStatus : not recognized"), None);
    }
}
