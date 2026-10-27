//! Discover local development teams without collecting account credentials.
use std::fmt;
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Team {
    pub id: String,
    pub name: String,
}
impl fmt::Display for Team {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let name: String = self.name.chars().take(28).collect();
        write!(
            f,
            "{}{} ({})",
            name,
            if self.name.chars().count() > 28 {
                "…"
            } else {
                ""
            },
            self.id
        )
    }
}
pub fn valid_id(id: &str) -> bool {
    id.len() == 10
        && id
            .bytes()
            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit())
}

fn certificate(subject: &str) -> Option<(Team, String)> {
    let mut id = None;
    let mut name = None;
    let mut fingerprint = None;
    for line in subject.lines().map(str::trim) {
        if let Some(value) = line.strip_prefix("OU=") {
            if valid_id(value) {
                id = Some(value.to_owned());
            }
        }
        if let Some(value) = line.strip_prefix("CN=Apple Development: ") {
            name = Some(value.to_owned());
        }
        if let Some((_, value)) = line.split_once("Fingerprint=") {
            fingerprint = Some(value.replace(':', "").to_uppercase());
        }
    }
    Some((
        Team {
            id: id?,
            name: name?,
        },
        fingerprint?,
    ))
}

#[cfg(target_os = "macos")]
pub async fn scan() -> Result<Vec<Team>, String> {
    use std::{process::Stdio, time::Duration};
    use tokio::{io::AsyncWriteExt, process::Command};
    async fn output(command: &mut Command) -> Result<std::process::Output, String> {
        command.kill_on_drop(true);
        tokio::time::timeout(Duration::from_secs(15), command.output())
            .await
            .map_err(|_| "Signing team discovery timed out.")?
            .map_err(|e| e.to_string())
    }
    let identities = output(Command::new("/usr/bin/security").args([
        "find-identity",
        "-v",
        "-p",
        "codesigning",
    ]))
    .await?;
    if !identities.status.success() {
        return Err(
            "Could not read development identities. Open Xcode Accounts and refresh.".into(),
        );
    }
    let valid: Vec<_> = String::from_utf8_lossy(&identities.stdout)
        .lines()
        .filter(|line| line.contains("\"Apple Development:"))
        .filter_map(|line| {
            line.split_whitespace()
                .find(|part| part.len() == 40 && part.bytes().all(|b| b.is_ascii_hexdigit()))
                .map(str::to_uppercase)
        })
        .collect();
    if valid.is_empty() {
        return Ok(Vec::new());
    }
    let certificates = output(Command::new("/usr/bin/security").args([
        "find-certificate",
        "-a",
        "-c",
        "Apple Development",
        "-p",
    ]))
    .await?;
    if !certificates.status.success() {
        return Err(
            "Could not read development certificates. Open Xcode Accounts and refresh.".into(),
        );
    }
    let pem = String::from_utf8_lossy(&certificates.stdout);
    let mut teams = Vec::<Team>::new();
    for block in pem.split_inclusive("-----END CERTIFICATE-----").take(100) {
        let Some(start) = block.find("-----BEGIN CERTIFICATE-----") else {
            continue;
        };
        let mut child = Command::new("/usr/bin/openssl")
            .args([
                "x509",
                "-noout",
                "-subject",
                "-nameopt",
                "sep_multiline,utf8",
                "-fingerprint",
                "-sha1",
                "-checkend",
                "0",
            ])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .map_err(|e| e.to_string())?;
        if let Some(mut input) = child.stdin.take() {
            input
                .write_all(block[start..].as_bytes())
                .await
                .map_err(|e| e.to_string())?;
        }
        let result = tokio::time::timeout(Duration::from_secs(5), child.wait_with_output())
            .await
            .map_err(|_| "Certificate inspection timed out.")?
            .map_err(|e| e.to_string())?;
        if result.status.success()
            && let Some((team, fingerprint)) = certificate(&String::from_utf8_lossy(&result.stdout))
            && valid.contains(&fingerprint)
            && !teams.iter().any(|previous| previous.id == team.id)
        {
            teams.push(team);
        }
    }
    teams.sort_by(|a, b| a.name.cmp(&b.name).then(a.id.cmp(&b.id)));
    Ok(teams)
}
#[cfg(not(target_os = "macos"))]
pub async fn scan() -> Result<Vec<Team>, String> {
    Err("Direct iPhone/iPad installation requires macOS and Xcode.".into())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    #[ignore = "Reads this Mac's local development identities on explicit request"]
    #[cfg(target_os = "macos")]
    fn local_signing_discovery() {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        let teams = runtime.block_on(scan()).unwrap();
        assert!(teams.iter().all(|team| valid_id(&team.id)));
        println!("Discovered {} local development teams", teams.len());
    }

    #[test]
    fn team_id_comes_from_organizational_unit_not_certificate_common_name() {
        let (team, fingerprint)=certificate("subject=\n    OU=TESTTEAM01\n    CN=Apple Development: Example (PERSON0001)\nsha1 Fingerprint=AB:CD").unwrap();
        assert_eq!(team.id, "TESTTEAM01");
        assert_eq!(fingerprint, "ABCD");
        assert!(
            certificate("OU=bad\nCN=Apple Development: Example\nsha1 Fingerprint=AA").is_none()
        );
        assert!(!valid_id("$(command)"));
        assert!(!valid_id("teamlower0"));
    }
}
