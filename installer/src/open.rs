//! Open folders and links with the host's default handler.
use std::path::Path;
use std::process::{Command, Stdio};

/// Try the standard Linux openers in order. `xdg-open` is the preferred
/// command, but minimal desktops such as Lubuntu do not ship `xdg-utils`;
/// `gio open` is available wherever GLib is installed.
#[cfg(target_os = "linux")]
fn linux_open(target: &std::ffi::OsStr) -> Result<(), String> {
    use std::io::ErrorKind;

    let mut failures = Vec::new();
    for (program, prefix) in [("xdg-open", &[][..]), ("gio", &["open"][..])] {
        match Command::new(program)
            .args(prefix)
            .arg(target)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
        {
            Ok(status) if status.success() => return Ok(()),
            Ok(status) => failures.push(format!("{program} exited with {status}")),
            Err(error) if error.kind() == ErrorKind::NotFound => {
                failures.push(format!("{program} was not found"))
            }
            Err(error) => failures.push(format!("{program}: {error}")),
        }
    }
    Err(format!(
        "{}. Install xdg-utils or open it manually.",
        failures.join("; ")
    ))
}

/// Reveal an installed application in the host file manager.
pub fn reveal(path: &Path) -> Result<(), String> {
    if !path.exists() {
        return Err("The installed app is no longer available.".into());
    }
    #[cfg(target_os = "macos")]
    {
        return Command::new("open")
            .arg("-R")
            .arg(path)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map_err(|error| error.to_string())?
            .success()
            .then_some(())
            .ok_or_else(|| "Could not show the installation folder.".into());
    }
    #[cfg(target_os = "linux")]
    {
        let folder = path
            .parent()
            .ok_or("The installation folder is unavailable.")?;
        return linux_open(folder.as_os_str())
            .map_err(|error| format!("Could not show the installation folder: {error}"));
    }
    #[cfg(target_os = "windows")]
    {
        let folder = path
            .parent()
            .ok_or("The installation folder is unavailable.")?;
        return Command::new("explorer.exe")
            .arg(folder)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map_err(|error| error.to_string())?
            .success()
            .then_some(())
            .ok_or_else(|| "Could not show the installation folder.".into());
    }
    #[cfg(not(any(target_os = "macos", target_os = "linux", target_os = "windows")))]
    {
        let _ = path;
        Err("Opening folders is not supported on this host.".into())
    }
}

/// Open a folder in the host file manager.
pub fn folder(path: &Path) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        return Command::new("open")
            .arg(path)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map(|_| ())
            .map_err(|error| format!("Could not open the folder: {error}"));
    }
    #[cfg(target_os = "linux")]
    {
        return linux_open(path.as_os_str())
            .map_err(|error| format!("Could not open the folder: {error}"));
    }
    #[cfg(target_os = "windows")]
    {
        return Command::new("explorer.exe")
            .arg(path)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map(|_| ())
            .map_err(|error| format!("Could not open the folder: {error}"));
    }
    #[cfg(not(any(target_os = "macos", target_os = "linux", target_os = "windows")))]
    {
        let _ = path;
        Err("Opening folders is not supported on this host.".into())
    }
}

/// Open a link in the host browser.
pub fn url(url: &str) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        return Command::new("open")
            .arg(url)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map_err(|error| error.to_string())?
            .success()
            .then_some(())
            .ok_or_else(|| "Could not open the link.".into());
    }
    #[cfg(target_os = "linux")]
    {
        return linux_open(std::ffi::OsStr::new(url))
            .map_err(|error| format!("Could not open the link: {error}"));
    }
    #[cfg(target_os = "windows")]
    {
        return Command::new("rundll32.exe")
            .arg("url.dll,FileProtocolHandler")
            .arg(url)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map_err(|error| error.to_string())?
            .success()
            .then_some(())
            .ok_or_else(|| "Could not open the link.".into());
    }
    #[cfg(not(any(target_os = "macos", target_os = "linux", target_os = "windows")))]
    {
        let _ = url;
        Err("Opening links is not supported on this host.".into())
    }
}
