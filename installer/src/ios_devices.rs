//! Session-only Apple device discovery. Never persist names or identifiers in the repo.
use serde_json::Value;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Device {
    pub id: String,
    pub name: String,
    pub model: String,
    pub connected: bool,
    pub wifi: bool,
}

#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn parse(value: &Value) -> Result<Vec<Device>, String> {
    let entries = value
        .pointer("/result/devices")
        .and_then(Value::as_array)
        .ok_or("Apple device discovery returned no device list.")?;
    let mut devices = Vec::new();
    for entry in entries {
        let hardware = &entry["hardwareProperties"];
        if hardware["platform"] != "iOS" || hardware["reality"] != "physical" {
            continue;
        }
        let Some(id) = hardware["udid"].as_str().filter(|id| !id.is_empty()) else {
            continue;
        };
        let connection = &entry["connectionProperties"];
        let connected = connection["tunnelState"] == "connected";
        if !connected && connection["pairingState"] != "paired" {
            continue;
        }
        let device = Device {
            id: id.into(),
            name: entry["deviceProperties"]["name"]
                .as_str()
                .unwrap_or("iPhone / iPad")
                .into(),
            model: hardware["marketingName"]
                .as_str()
                .unwrap_or("iPhone / iPad")
                .into(),
            connected,
            wifi: connection["transportType"] == "localNetwork",
        };
        if !devices
            .iter()
            .any(|previous: &Device| previous.id == device.id)
        {
            devices.push(device);
        }
    }
    devices.sort_by(|a, b| {
        b.connected
            .cmp(&a.connected)
            .then(a.name.to_lowercase().cmp(&b.name.to_lowercase()))
            .then(a.id.cmp(&b.id))
    });
    Ok(devices)
}

pub fn choose(devices: &[Device], previous: Option<&str>) -> Option<String> {
    // Never silently switch to another phone when the selected one disappears.
    if let Some(id) = previous {
        return Some(id.into());
    }
    let mut connected = devices.iter().filter(|device| device.connected);
    let first = connected.next()?;
    connected.next().is_none().then(|| first.id.clone())
}

#[cfg(target_os = "macos")]
pub async fn scan(selected: Option<String>) -> Result<Vec<Device>, String> {
    use std::{process::Stdio, time::Duration};
    use tokio::process::Command;
    let directory = std::env::temp_dir().join(format!(
        "installer-devices-{}",
        crate::ios_profile::new_id()
    ));
    std::fs::create_dir(&directory).map_err(|e| e.to_string())?;
    let output = directory.join("devices.json");
    async fn list(output: &std::path::Path) -> Result<Vec<Device>, String> {
        if output.exists() {
            std::fs::remove_file(output).map_err(|e| e.to_string())?;
        }
        let status = tokio::time::timeout(
            Duration::from_secs(20),
            Command::new("/usr/bin/xcrun")
                .args([
                    "devicectl",
                    "list",
                    "devices",
                    "--timeout",
                    "15",
                    "--json-output",
                ])
                .arg(output)
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .kill_on_drop(true)
                .status(),
        )
        .await
        .map_err(|_| "Apple device discovery timed out.")?
        .map_err(|e| e.to_string())?;
        if !status.success() {
            return Err(
                "Apple device discovery failed. Check Xcode pairing and reconnect the device."
                    .into(),
            );
        }
        parse(
            &serde_json::from_slice::<Value>(&std::fs::read(output).map_err(|e| e.to_string())?)
                .map_err(|e| e.to_string())?,
        )
    }
    let result = async {
        let devices = list(&output).await?;
        if let Some(id) = selected
            && !devices.iter().any(|d| d.id == id && d.connected)
        {
            // An explicit selection can wake a paired USB/Wi-Fi device's tunnel.
            let _ = tokio::time::timeout(
                Duration::from_secs(12),
                Command::new("/usr/bin/xcrun")
                    .args([
                        "devicectl",
                        "device",
                        "info",
                        "details",
                        "--device",
                        &id,
                        "--timeout",
                        "10",
                    ])
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .kill_on_drop(true)
                    .status(),
            )
            .await;
            return list(&output).await;
        }
        Ok(devices)
    }
    .await;
    let _ = std::fs::remove_dir_all(directory);
    result
}

#[cfg(not(target_os = "macos"))]
pub async fn scan(_selected: Option<String>) -> Result<Vec<Device>, String> {
    Err("Apple device installation requires macOS.".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture(id: &str, name: &str, state: &str, transport: &str) -> Value {
        serde_json::json!({"hardwareProperties":{"udid":id,"platform":"iOS","reality":"physical","marketingName":"Test device"},"deviceProperties":{"name":name},"connectionProperties":{"pairingState":"paired","tunnelState":state,"transportType":transport}})
    }
    #[test]
    fn multiple_usb_and_wifi_devices_require_selection_and_preserve_it_on_refresh() {
        let devices = parse(&serde_json::json!({"result":{"devices":[fixture("one","iPad","connected","wired"),fixture("two","iPhone","connected","localNetwork"),fixture("three","Other iPad","connected","wired")]}})).unwrap();
        assert_eq!(devices.len(), 3);
        assert!(devices.iter().any(|d| d.id == "two" && d.wifi));
        assert_eq!(choose(&devices, None), None);
        assert_eq!(choose(&[], Some("two")), Some("two".into()));
        assert_eq!(choose(&devices, Some("two")), Some("two".into()));
        let offline = parse(&serde_json::json!({"result":{"devices":[fixture("two","iPhone","disconnected","localNetwork"),fixture("one","iPad","connected","wired")]}})).unwrap();
        assert_eq!(choose(&offline, Some("two")), Some("two".into()));
        assert_eq!(choose(&offline, None), Some("one".into()));
    }
    #[test]
    fn ignores_simulators_and_rejects_malformed_discovery() {
        let mut simulator = fixture("sim", "Simulator", "connected", "sameMachine");
        simulator["hardwareProperties"]["reality"] = "simulated".into();
        assert!(
            parse(&serde_json::json!({"result":{"devices":[simulator]}}))
                .unwrap()
                .is_empty()
        );
        assert!(parse(&serde_json::json!({})).is_err());
    }
}
