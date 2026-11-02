//! Explains a failed extraction from the NAMES in prod.keys. Key values are never put into a message or a log, and hactool's
//! warnings (which print key values) are never shown: only its `Error:` lines, with long hex strings masked.
use std::collections::BTreeMap;

struct Entry {
    length: usize,
    hex: bool,
}

pub struct Keys {
    entries: BTreeMap<String, Entry>,
}

/// Names that hactool needs for every game and the length of their value in hex digits.
const FIXED: [(&str, usize); 5] = [
    ("header_key", 64),
    ("aes_kek_generation_source", 32),
    ("aes_key_generation_source", 32),
    ("key_area_key_application_source", 32),
    ("titlekek_source", 32),
];

impl Keys {
    pub fn parse(text: &str) -> Self {
        let mut entries = BTreeMap::new();
        for line in text.trim_start_matches('\u{feff}').lines() {
            let Some((name, value)) = line.split_once('=') else {
                continue;
            };
            let (name, value) = (name.trim().to_ascii_lowercase(), value.trim());
            if name.is_empty() || name.starts_with(['#', ';']) {
                continue;
            }
            entries.insert(
                name,
                Entry {
                    length: value.len(),
                    hex: value.bytes().all(|b| b.is_ascii_hexdigit()),
                },
            );
        }
        Self { entries }
    }

    fn has(&self, name: &str, length: usize) -> bool {
        self.entries
            .get(name)
            .is_some_and(|e| e.hex && e.length == length)
    }

    fn masters(&self) -> Vec<u32> {
        self.entries
            .keys()
            .filter_map(|name| name.strip_prefix("master_key_"))
            .filter(|n| n.len() == 2)
            .filter_map(|n| u32::from_str_radix(n, 16).ok())
            .collect()
    }

    /// One line for the log, also on success: which master keys the file has.
    pub fn summary(&self) -> String {
        let masters = self.masters();
        let (Some(first), Some(last)) = (masters.iter().min(), masters.iter().max()) else {
            return "no master_key entries found".into();
        };
        format!(
            "master_key_{first:02x} to master_key_{last:02x} ({} entries), header_key {}",
            masters.len(),
            if self.has("header_key", 64) {
                "ok"
            } else {
                "missing or malformed"
            }
        )
    }

    /// What is wrong with the file for a game that needs master key revision `needed` (hactool's number), most important first.
    pub fn problems(&self, needed: Option<u32>) -> Vec<String> {
        let masters = self.masters();
        let mut found = Vec::new();
        if masters.is_empty() {
            found.push(
                "prod.keys has no master_key_XX entries: this is not a full prod.keys (dump it with Lockpick_RCM)"
                    .to_string(),
            );
        }
        for (name, length) in FIXED {
            match self.entries.get(name) {
                None => found.push(format!("{name} is missing")),
                Some(e) if !e.hex || e.length != length => found.push(format!(
                    "{name} is malformed ({} characters, {length} hex digits expected)",
                    e.length
                )),
                Some(_) => {}
            }
        }
        // hactool counts revisions 0 and 1 both as master_key_00 and then one lower than its number.
        let index = needed.map(|n| n.saturating_sub(1));
        if let (Some(index), Some(&highest)) = (index, masters.iter().max()) {
            if !masters.contains(&index) {
                found.insert(
                    0,
                    format!(
                        "the game needs master_key_{index:02x} (revision 0x{:X}), prod.keys only has master keys up to master_key_{highest:02x}: dump prod.keys again from a console with up-to-date firmware",
                        needed.unwrap_or(0)
                    ),
                );
            } else {
                for (derived, source) in [
                    (
                        "key_area_key_application",
                        "key_area_key_application_source",
                    ),
                    ("titlekek", "titlekek_source"),
                ] {
                    let name = format!("{derived}_{index:02x}");
                    if !self.has(&name, 32) && !self.has(source, 32) {
                        found.push(format!("{name} is missing and cannot be derived"));
                    }
                }
            }
        } else if index.is_none() {
            let gaps: Vec<String> = masters
                .iter()
                .max()
                .map(|&top| {
                    (0..top)
                        .filter(|i| !masters.contains(i))
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default()
                .iter()
                .map(|i| format!("master_key_{i:02x}"))
                .collect();
            if !gaps.is_empty() {
                found.push(format!("missing master keys: {}", gaps.join(", ")));
            }
        }
        found
    }
}

/// The `Error:` lines of hactool's stderr, long hex strings masked (a few lines at most).
pub fn safe_error_lines(stderr: &[u8]) -> Vec<String> {
    String::from_utf8_lossy(stderr)
        .lines()
        .map(str::trim)
        .filter(|line| line.starts_with("Error:"))
        .take(3)
        .map(|line| {
            let mut out = String::new();
            let mut run = String::new();
            for c in line.chars().chain(std::iter::once(' ')) {
                if c.is_ascii_hexdigit() {
                    run.push(c);
                    continue;
                }
                out.push_str(if run.len() >= 16 { "<hex>" } else { &run });
                run.clear();
                out.push(c);
            }
            out.pop();
            out.chars().take(160).collect()
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn keys(masters: u32) -> String {
        let mut text = format!("header_key = {}\r\n", "a".repeat(64));
        for name in FIXED.iter().skip(1) {
            text += &format!("{} = {}\r\n", name.0, "b".repeat(32));
        }
        for i in 0..masters {
            text += &format!("master_key_{i:02x} = {}\r\n", "c".repeat(32));
        }
        text
    }

    #[test]
    fn a_complete_file_has_no_problems_and_names_its_master_range() {
        let parsed = Keys::parse(&keys(16));
        assert!(parsed.problems(Some(0xC)).is_empty());
        assert!(
            parsed
                .summary()
                .starts_with("master_key_00 to master_key_0f (16 entries)")
        );
    }

    #[test]
    fn a_file_older_than_the_game_says_which_master_key_is_missing() {
        let problems = Keys::parse(&keys(10)).problems(Some(0xC));
        assert!(
            problems[0].contains("master_key_0b (revision 0xC)"),
            "{problems:?}"
        );
        assert!(problems[0].contains("up to master_key_09"));
    }

    #[test]
    fn missing_or_malformed_names_are_reported_without_their_values() {
        let text = keys(16)
            .replace(&"a".repeat(64), "abc123")
            .replace("titlekek_source", "x");
        let problems = Keys::parse(&text).problems(Some(0xC));
        assert!(
            problems
                .iter()
                .any(|p| p.starts_with("header_key is malformed (6 characters"))
        );
        assert!(
            problems
                .iter()
                .any(|p| p.starts_with("titlekek_source is missing"))
        );
        assert!(problems.iter().all(|p| !p.contains("abc123")));
        assert!(Keys::parse("hello").problems(None)[0].starts_with("prod.keys has no master_key"));
    }

    #[test]
    fn only_error_lines_survive_and_hex_is_masked() {
        let stderr = b"[WARN]: Failed to match key \"x\", (value \"34c1a0c48258f8b4fa9e5e6adafc7e4f\")\nError: section 0 is corrupted!\nError: bad 34c1a0c48258f8b4fa9e5e6adafc7e4f end\n";
        assert_eq!(
            safe_error_lines(stderr),
            ["Error: section 0 is corrupted!", "Error: bad <hex> end"]
        );
    }
}
