//! Metadata readers for NCAs, tickets, title keys, CNMT and NACP. Only non-critical fields are ever read from hactool output.
use std::{
    collections::HashMap,
    fs,
    path::{Path, PathBuf},
};

pub const ZERO_RIGHTS: &str = "00000000000000000000000000000000";

#[derive(Debug, Clone)]
pub struct Nca {
    pub path: PathBuf,
    pub title_id: String,
    pub content_type: String,
    pub rights_id: Option<String>,
    pub size: u64,
}

pub fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn is_hex32(text: &str) -> bool {
    text.len() == 32
        && text
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
}

/// Reads the `hactool -i` output and keeps only title ID, content type, rights ID and size.
pub fn parse_nca_info(text: &str, path: &Path) -> Result<Nca, String> {
    let (mut title, mut kind, mut rights, mut size) = (None, None, None, None);
    for line in text.lines() {
        let Some((key, value)) = line.split_once(':') else {
            continue;
        };
        let value = value.trim();
        let valid_key = key.starts_with(|c: char| c.is_ascii_alphabetic())
            && key.chars().all(|c| c.is_ascii_alphabetic() || c == ' ');
        if !valid_key || value.is_empty() || !line[key.len() + 1..].starts_with(char::is_whitespace)
        {
            continue;
        }
        let slot = match key {
            "Title ID" => &mut title,
            "Content Type" => &mut kind,
            "Rights ID" => &mut rights,
            "Content Size" => &mut size,
            _ => continue,
        };
        slot.get_or_insert(value.to_string());
    }
    let (Some(title_id), Some(content_type)) = (title, kind) else {
        return Err("no NCA info (keys missing or not an NCA)".into());
    };
    let rights = rights
        .map(|r| r.to_lowercase())
        .filter(|r| r != ZERO_RIGHTS);
    let size = size
        .map(|s| u64::from_str_radix(s.trim_start_matches("0x"), 16).map_err(|e| e.to_string()))
        .transpose()?
        .unwrap_or(0);
    Ok(Nca {
        path: path.to_path_buf(),
        title_id: title_id.to_lowercase(),
        content_type,
        rights_id: rights,
        size,
    })
}

fn family(title_id: &str) -> Option<u64> {
    u64::from_str_radix(title_id, 16).ok().map(|id| id & !0xFFF)
}

/// The largest NCA with this content type (and title ID, if given).
pub fn pick<'a>(items: &'a [Nca], content_type: &str, title_id: Option<&str>) -> Option<&'a Nca> {
    items
        .iter()
        .filter(|n| n.content_type.eq_ignore_ascii_case(content_type))
        .filter(|n| title_id.is_none_or(|id| n.title_id == id.to_lowercase()))
        .max_by_key(|n| n.size)
}

/// Control/Meta content belongs to a Program through its title family; more than one match is ambiguous.
pub fn pick_related<'a>(
    items: &'a [Nca],
    content_type: &str,
    title_id: &str,
) -> Result<Option<&'a Nca>, String> {
    let wanted = family(title_id);
    let found: Vec<_> = items
        .iter()
        .filter(|n| {
            n.content_type.eq_ignore_ascii_case(content_type) && family(&n.title_id) == wanted
        })
        .collect();
    match found.len() {
        0 => Ok(None),
        1 => Ok(Some(found[0])),
        _ => Err(format!(
            "Multiple matching {content_type} NCAs; title association is ambiguous"
        )),
    }
}

/// Rights ID and, for common tickets only, the encrypted title key.
pub fn parse_ticket(data: &[u8]) -> Result<(String, Option<String>), String> {
    let layout = |kind: u32| match kind {
        0x010000 | 0x010003 => Some((0x200, 0x3C)),
        0x010001 | 0x010004 => Some((0x100, 0x3C)),
        0x010002 | 0x010005 => Some((0x3C, 0x40)),
        _ => None,
    };
    let word = data.get(..4).ok_or("ticket too short")?;
    let word = <[u8; 4]>::try_from(word).unwrap();
    let (signature, padding) = layout(u32::from_le_bytes(word))
        .or_else(|| layout(u32::from_be_bytes(word)))
        .ok_or("unknown signature type")?;
    let body = 4 + signature + padding;
    if data.len() < body + 0x170 {
        return Err("ticket truncated".into());
    }
    let key_type = data[body + 0x141];
    let rights = hex(&data[body + 0x160..body + 0x170]);
    let key = (key_type == 0).then(|| hex(&data[body + 0x40..body + 0x50]));
    Ok((rights, key))
}

fn parse_title_keys(text: &str) -> HashMap<String, String> {
    let mut keys = HashMap::new();
    for line in text.lines().map(str::trim) {
        if line.is_empty() || line.starts_with([';', '#']) {
            continue;
        }
        if let Some((rights, key)) = line.split_once('=') {
            let (rights, key) = (rights.trim().to_lowercase(), key.trim().to_lowercase());
            if is_hex32(&rights) && is_hex32(&key) {
                keys.insert(rights, key);
            }
        }
    }
    keys
}

/// First a common ticket next to the NCAs, then title.keys.
pub fn find_title_key(
    rights: &str,
    ticket_dir: &Path,
    title_keys: Option<&str>,
) -> Result<String, String> {
    let rights = rights.to_lowercase();
    let mut personalized = false;
    let mut names: Vec<_> = fs::read_dir(ticket_dir)
        .map(|entries| entries.flatten().map(|e| e.path()).collect())
        .unwrap_or_default();
    names.sort();
    for path in names {
        if path
            .extension()
            .is_none_or(|e| !e.eq_ignore_ascii_case("tik"))
        {
            continue;
        }
        let Ok((id, key)) = fs::read(&path)
            .map_err(|e| e.to_string())
            .and_then(|d| parse_ticket(&d))
        else {
            continue;
        };
        if id == rights {
            match key {
                Some(key) => return Ok(key),
                None => personalized = true,
            }
        }
    }
    if let Some(key) = title_keys.and_then(|text| parse_title_keys(text).remove(&rights)) {
        return Ok(key);
    }
    Err(if personalized {
        "personalized ticket (cannot be decrypted) and no entry in title.keys".into()
    } else {
        "no ticket and no entry in title.keys for the rights ID".into()
    })
}

/// Title version from a PackagedContentMeta (u32 at offset 8).
pub fn cnmt_version(data: &[u8]) -> Result<u32, String> {
    let bytes = data.get(8..12).ok_or("cnmt too short")?;
    Ok(u32::from_le_bytes(bytes.try_into().unwrap()))
}

fn c_string(bytes: &[u8]) -> String {
    let end = bytes.iter().position(|&b| b == 0).unwrap_or(bytes.len());
    String::from_utf8_lossy(&bytes[..end]).trim().to_string()
}

pub fn nacp_display_version(data: &[u8]) -> Result<String, String> {
    Ok(c_string(data.get(0x3060..0x3070).ok_or("nacp too short")?))
}

/// NACP slot order is a binary-format contract.
pub const NACP_LANGUAGES: [&str; 16] = [
    "en-US", "en-GB", "ja", "fr", "de", "es-419", "es-ES", "it", "nl", "fr-CA", "pt-PT", "ru",
    "ko", "zh-Hant", "zh-Hans", "pt-BR",
];

/// Localized (name, publisher) per locale and the display version of a control.nacp.
/// (locale, name, publisher)
pub type Titles = Vec<(&'static str, String, String)>;

pub fn read_nacp(data: &[u8]) -> Result<(Titles, String), String> {
    if data.len() != 0x4000 {
        return Err("Invalid control.nacp size".into());
    }
    let titles = NACP_LANGUAGES
        .iter()
        .enumerate()
        .filter_map(|(i, locale)| {
            let name = c_string(&data[i * 0x300..i * 0x300 + 0x200]);
            (!name.is_empty()).then(|| {
                (
                    *locale,
                    name,
                    c_string(&data[i * 0x300 + 0x200..i * 0x300 + 0x300]),
                )
            })
        })
        .collect();
    Ok((titles, c_string(&data[0x3060..0x3070])))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn nca(kind: &str, title: &str, size: u64) -> Nca {
        Nca {
            path: PathBuf::from(format!("{kind}-{size}.nca")),
            title_id: title.into(),
            content_type: kind.into(),
            rights_id: None,
            size,
        }
    }

    #[test]
    fn info_keeps_only_the_non_critical_fields() {
        let text = "Magic: NCA3\nTitle ID:          0100000011D90000\nContent Type:  Program\nContent Size:  0x1000\nRights ID: 00000000000000000000000000000000\nHeader Key: should be ignored\n";
        let info = parse_nca_info(text, Path::new("a.nca")).unwrap();
        assert_eq!(
            (
                info.title_id.as_str(),
                info.content_type.as_str(),
                info.size
            ),
            ("0100000011d90000", "Program", 0x1000)
        );
        assert_eq!(info.rights_id, None);
        assert!(parse_nca_info("Content Type: Program\n", Path::new("a.nca")).is_err());
    }

    #[test]
    fn picks_the_largest_program_and_rejects_ambiguous_related_content() {
        let items = [
            nca("Program", "0100000011d90000", 5),
            nca("Program", "0100000011d90000", 9),
            nca("Control", "0100000011d90800", 1),
        ];
        assert_eq!(
            pick(&items, "program", Some("0100000011D90000"))
                .unwrap()
                .size,
            9
        );
        assert!(pick(&items, "Meta", None).is_none());
        assert_eq!(related_size(&items, "Control"), Ok(Some(1)));
        let twice = [
            nca("Control", "0100000011d90800", 1),
            nca("Control", "0100000011d90801", 2),
        ];
        assert!(pick_related(&twice, "Control", "0100000011d90000").is_err());
        assert_eq!(related_size(&items, "Meta"), Ok(None));
    }

    fn related_size(items: &[Nca], kind: &str) -> Result<Option<u64>, String> {
        pick_related(items, kind, "0100000011d90000").map(|n| n.map(|n| n.size))
    }

    #[test]
    fn common_tickets_yield_their_key_and_title_keys_are_the_fallback() {
        let mut ticket = vec![0u8; 4 + 0x100 + 0x3C + 0x170];
        ticket[..4].copy_from_slice(&0x010001u32.to_le_bytes());
        let body = 4 + 0x100 + 0x3C;
        ticket[body + 0x40..body + 0x50].copy_from_slice(&[0xAB; 16]);
        ticket[body + 0x160..body + 0x170].copy_from_slice(&[0x11; 16]);
        let (rights, key) = parse_ticket(&ticket).unwrap();
        assert_eq!(
            (rights.as_str(), key.as_deref()),
            (
                "11111111111111111111111111111111",
                Some("abababababababababababababababab")
            )
        );
        ticket[body + 0x141] = 1;
        assert_eq!(parse_ticket(&ticket).unwrap().1, None);
        assert!(parse_ticket(&ticket[..8]).is_err());
        let directory = std::env::temp_dir().join(format!("bdsp-tik-{}", std::process::id()));
        fs::create_dir_all(&directory).unwrap();
        fs::write(directory.join("a.tik"), &ticket).unwrap();
        let text =
            "# comment\n11111111111111111111111111111111 = 22222222222222222222222222222222\n";
        assert_eq!(
            find_title_key(&"11".repeat(16), &directory, Some(text)).unwrap(),
            "22".repeat(16)
        );
        assert!(
            find_title_key(&"11".repeat(16), &directory, None)
                .unwrap_err()
                .contains("personalized")
        );
        fs::remove_dir_all(&directory).unwrap();
    }

    #[test]
    fn cnmt_and_nacp_fields() {
        let mut meta = vec![0u8; 16];
        meta[8..12].copy_from_slice(&0x30000u32.to_le_bytes());
        assert_eq!(cnmt_version(&meta), Ok(0x30000));
        assert!(cnmt_version(&meta[..8]).is_err());
        let mut nacp = vec![0u8; 0x4000];
        nacp[..7].copy_from_slice(b"Diamond");
        nacp[0x200..0x205].copy_from_slice(b"Maker");
        nacp[0x3060..0x3065].copy_from_slice(b"1.3.0");
        let (titles, version) = read_nacp(&nacp).unwrap();
        assert_eq!(
            titles,
            vec![("en-US", "Diamond".to_string(), "Maker".to_string())]
        );
        assert_eq!(
            (
                version.as_str(),
                nacp_display_version(&nacp).unwrap().as_str()
            ),
            ("1.3.0", "1.3.0")
        );
        assert!(read_nacp(&nacp[..100]).is_err());
    }
}
