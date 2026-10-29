//! Local firmware import. Proprietary resources and key material never leave the host.
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashSet},
    fs,
    io::{Read, Write},
    path::{Component, Path, PathBuf},
    process::{Command, Stdio},
};
type Result<T> = std::result::Result<T, String>;
const KEYBOARD: &str = "0100000000001008";
const STD: &str = "0100000000000811";
const EXT: &str = "0100000000000810";
const WORDS: &str = "0100000000000823";
const TITLES: [&str; 7] = [
    KEYBOARD,
    STD,
    EXT,
    WORDS,
    "0100000000000812",
    "0100000000000813",
    "0100000000000814",
];
const MAX_BYTES: u64 = 4 << 30;
const MAX_FILES: usize = 8192;
fn err(_: impl std::fmt::Display) -> String {
    "Firmware files could not be read or written. Check folder access and free disk space.".into()
}

pub fn inspect_source(path: &Path) -> Result<()> {
    let m = fs::symlink_metadata(path).map_err(err)?;
    if m.file_type().is_symlink() {
        return Err("Choose a firmware ZIP or an actual NCA folder, not a symbolic link.".into());
    }
    if m.is_dir() {
        if ncas(path)?.is_empty() {
            return Err("No firmware NCA files found in this folder.".into());
        }
    } else if !m.is_file()
        || !path
            .extension()
            .is_some_and(|s| s.eq_ignore_ascii_case("zip"))
        || m.len() == 0
        || m.len() > MAX_BYTES
    {
        return Err(
            "Choose a firmware ZIP or a folder containing firmware .nca files (up to 4 GB).".into(),
        );
    }
    Ok(())
}

fn walk(root: &Path, depth: usize, files: &mut Vec<PathBuf>) -> Result<()> {
    if depth > 12 {
        return Err("Firmware folders are nested too deeply.".into());
    }
    for item in fs::read_dir(root).map_err(err)? {
        let item = item.map_err(err)?;
        let kind = item.file_type().map_err(err)?;
        if kind.is_symlink() || (!kind.is_file() && !kind.is_dir()) {
            return Err("Firmware folders may contain only ordinary files and folders.".into());
        }
        if kind.is_dir() {
            walk(&item.path(), depth + 1, files)?;
        } else {
            files.push(item.path());
            if files.len() > MAX_FILES {
                return Err("Too many files in firmware folder.".into());
            }
        }
    }
    Ok(())
}
fn ncas(root: &Path) -> Result<Vec<PathBuf>> {
    let mut files = Vec::new();
    walk(root, 0, &mut files)?;
    let mut out = Vec::new();
    let mut bytes = 0u64;
    for path in files {
        let direct = path
            .extension()
            .is_some_and(|x| x.eq_ignore_ascii_case("nca"));
        let registered = path
            .parent()
            .and_then(Path::extension)
            .is_some_and(|x| x.eq_ignore_ascii_case("nca"));
        if registered && path.file_name().is_none_or(|x| x != "00") {
            return Err(
                "Split firmware NCAs are not supported. Export complete .nca files.".into(),
            );
        }
        if direct || registered {
            let size = fs::metadata(&path).map_err(err)?.len();
            bytes = bytes.checked_add(size).ok_or("Firmware size overflow")?;
            if size == 0 || size > 1 << 30 || bytes > MAX_BYTES {
                return Err(
                    "Firmware NCA size is invalid or exceeds the 4 GB import limit.".into(),
                );
            }
            out.push(path);
        }
    }
    out.sort();
    Ok(out)
}

struct Scratch(PathBuf);
impl Scratch {
    fn new(cache: &Path) -> Result<Self> {
        fs::create_dir_all(cache).map_err(err)?;
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(err)?
            .as_nanos();
        static SEQUENCE: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let sequence = SEQUENCE.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let p = cache.join(format!(
            ".firmware-import-{}-{stamp}-{sequence}",
            std::process::id()
        ));
        fs::create_dir(&p).map_err(err)?;
        Ok(Self(p))
    }
}
impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn zip_path(name: &str) -> Result<PathBuf> {
    if name.contains('\\') || name.contains(':') || name.contains('\0') {
        return Err("Unsafe path in firmware ZIP.".into());
    }
    let path = Path::new(name);
    if path.is_absolute()
        || path
            .components()
            .any(|c| !matches!(c, Component::Normal(_)))
    {
        return Err("Unsafe path in firmware ZIP.".into());
    }
    Ok(path.to_owned())
}
fn unpack(source: &Path, dest: &Path) -> Result<()> {
    let mut zip = zip::ZipArchive::new(fs::File::open(source).map_err(err)?)
        .map_err(|_| "Firmware ZIP is invalid or unsupported.")?;
    if zip.len() > MAX_FILES {
        return Err("Too many entries in firmware ZIP.".into());
    }
    let mut seen = HashSet::new();
    let mut bytes = 0u64;
    // Validate every entry before writing any of them, including ignored files.
    for i in 0..zip.len() {
        let entry = zip
            .by_index(i)
            .map_err(|_| "Encrypted or unsupported firmware ZIP entry.")?;
        let path = zip_path(entry.name().trim_end_matches('/'))?;
        if !seen.insert(path.to_string_lossy().to_lowercase()) {
            return Err("Duplicate filenames in firmware ZIP.".into());
        }
        let mode = entry.unix_mode().unwrap_or(0) & 0o170000;
        if mode != 0 && mode != 0o100000 && mode != 0o040000 {
            return Err("Links and special files are not allowed in firmware ZIPs.".into());
        }
        bytes = bytes
            .checked_add(entry.size())
            .ok_or("Firmware ZIP size overflow")?;
        if bytes > MAX_BYTES || entry.size() > 1 << 30 {
            return Err("Firmware ZIP expands beyond the import size limit.".into());
        }
    }
    fs::create_dir(dest).map_err(err)?;
    for i in 0..zip.len() {
        let mut entry = zip.by_index(i).map_err(err)?;
        let path = dest.join(zip_path(entry.name().trim_end_matches('/'))?);
        if entry.is_dir() {
            fs::create_dir_all(path).map_err(err)?;
            continue;
        }
        fs::create_dir_all(path.parent().ok_or("Invalid ZIP path")?).map_err(err)?;
        let expected = entry.size();
        let mut output = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .map_err(err)?;
        let copied = std::io::copy(&mut (&mut entry).take(expected + 1), &mut output)
            .map_err(|_| "Firmware ZIP could not be decoded or failed its CRC check.")?;
        if copied != expected {
            return Err("Firmware ZIP entry size does not match its header.".into());
        }
    }
    Ok(())
}
fn hash_file(path: &Path) -> Result<String> {
    let mut f = fs::File::open(path).map_err(err)?;
    let mut h = Sha256::new();
    let mut buf = [0u8; 65536];
    loop {
        let n = f.read(&mut buf).map_err(err)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(format!("{:x}", h.finalize()))
}
fn tool(tool: &Path, keys: &Path, args: &[String]) -> Result<String> {
    let out = Command::new(tool)
        .arg("-k")
        .arg(keys)
        .args(args)
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
        .map_err(|_| "The firmware extraction tool could not start.")?;
    // Never relay tool diagnostics: hactool can print key material.
    if !out.status.success() {
        return Err(
            "Firmware could not be decrypted. Check that prod.keys matches your firmware dump."
                .into(),
        );
    }
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}
fn validate_font(path: &Path) -> Result<()> {
    let mut raw = fs::read(path).map_err(err)?;
    if raw.len() < 32 || raw.len() > 32 << 20 || raw.len() % 4 != 0 {
        return Err("Firmware contains an invalid font.".into());
    }
    let key = u32::from_le_bytes(raw[..4].try_into().unwrap()) ^ 0x18029a7f;
    for word in raw[8..].chunks_exact_mut(4) {
        let v = u32::from_le_bytes(word.try_into().unwrap()) ^ key;
        word.copy_from_slice(&v.to_le_bytes());
    }
    let data = &raw[8..];
    if !matches!(&data[..4], b"\0\x01\0\0" | b"true" | b"OTTO") {
        return Err("Firmware font could not be decoded.".into());
    }
    let n = u16::from_be_bytes(data[4..6].try_into().unwrap()) as usize;
    if n == 0 || 12 + n * 16 > data.len() {
        return Err("Firmware font table is invalid.".into());
    }
    let mut tables = HashSet::new();
    for t in data[12..12 + n * 16].chunks_exact(16) {
        let off = u32::from_be_bytes(t[8..12].try_into().unwrap()) as usize;
        let len = u32::from_be_bytes(t[12..16].try_into().unwrap()) as usize;
        if off.checked_add(len).is_none_or(|end| end > data.len()) {
            return Err("Firmware font table is truncated.".into());
        }
        tables.insert(&t[..4]);
    }
    for tag in [b"cmap", b"head", b"hhea", b"hmtx", b"maxp"] {
        if !tables.contains(tag.as_slice()) {
            return Err("Firmware font is missing required tables.".into());
        }
    }
    let face = ttf_parser::Face::parse(data, 0)
        .map_err(|_| "Firmware font tables could not be decoded.")?;
    if face.number_of_glyphs() == 0 {
        return Err("Firmware font contains no glyphs.".into());
    }
    Ok(())
}
fn validate_layout(path: &Path) -> Result<HashSet<String>> {
    let bytes = fs::read(path).map_err(err)?;
    let data = if bytes.starts_with(b"Yaz0") {
        if bytes.len() < 16 {
            return Err("Firmware keyboard layout is truncated.".into());
        }
        let size = u32::from_be_bytes(bytes[4..8].try_into().unwrap()) as usize;
        if size > 32 << 20 {
            return Err("Firmware keyboard layout is too large.".into());
        }
        let mut out = Vec::with_capacity(size);
        let mut pos = 16;
        let mut code = 0u8;
        let mut bits = 0;
        while out.len() < size {
            if bits == 0 {
                code = *bytes.get(pos).ok_or("Truncated keyboard layout")?;
                pos += 1;
                bits = 8;
            }
            if code & 0x80 != 0 {
                out.push(*bytes.get(pos).ok_or("Truncated keyboard layout")?);
                pos += 1;
            } else {
                let a = *bytes.get(pos).ok_or("Truncated keyboard layout")? as usize;
                let b = *bytes.get(pos + 1).ok_or("Truncated keyboard layout")? as usize;
                pos += 2;
                let distance = ((a & 15) << 8 | b) + 1;
                let len = if a >> 4 == 0 {
                    let c = *bytes.get(pos).ok_or("Truncated keyboard layout")? as usize;
                    pos += 1;
                    c + 0x12
                } else {
                    (a >> 4) + 2
                };
                if distance > out.len() || out.len() + len > size {
                    return Err("Invalid compressed keyboard layout.".into());
                }
                for _ in 0..len {
                    out.push(out[out.len() - distance]);
                }
            }
            code <<= 1;
            bits -= 1;
        }
        out
    } else {
        bytes
    };
    let invalid = "Firmware keyboard layout archive is unreadable.";
    let le16 = |offset: usize| -> Result<usize> {
        Ok(u16::from_le_bytes(
            data.get(offset..offset + 2)
                .ok_or(invalid)?
                .try_into()
                .unwrap(),
        ) as usize)
    };
    let le32 = |offset: usize| -> Result<usize> {
        Ok(u32::from_le_bytes(
            data.get(offset..offset + 4)
                .ok_or(invalid)?
                .try_into()
                .unwrap(),
        ) as usize)
    };
    if data.len() < 40
        || !data.starts_with(b"SARC")
        || data[6..8] != [0xff, 0xfe]
        || &data[20..24] != b"SFAT"
        || le16(4)? != 20
        || le32(8)? != data.len()
    {
        return Err(invalid.into());
    }
    let count = le16(26)?;
    let names = 32 + count * 16;
    let start = le32(12)?;
    if data.get(names..names + 4) != Some(b"SFNT".as_slice())
        || names + 8 > start
        || start > data.len()
    {
        return Err(invalid.into());
    }
    let mut layouts = HashSet::new();
    for index in 0..count {
        let node = 32 + index * 16;
        let name_offset = names + 8 + (le32(node + 4)? & 0xffffff) * 4;
        let name = data
            .get(name_offset..start)
            .and_then(|s| s.split(|c| *c == 0).next())
            .ok_or(invalid)?;
        let from = start.checked_add(le32(node + 8)?).ok_or(invalid)?;
        let to = start.checked_add(le32(node + 12)?).ok_or(invalid)?;
        let file = data.get(from..to).ok_or(invalid)?;
        if name.ends_with(b".bflyt") {
            if file.len() < 20 || !file.starts_with(b"FLYT") || file[4..6] != [0xff, 0xfe] {
                return Err(invalid.into());
            }
            layouts.insert(String::from_utf8(name.to_vec()).map_err(|_| invalid)?);
        }
    }
    Ok(layouts)
}
fn copy_files(source: &Path, dest: &Path) -> Result<()> {
    let mut files = Vec::new();
    walk(source, 0, &mut files)?;
    let mut total = 0u64;
    for file in files {
        total += fs::metadata(&file).map_err(err)?.len();
        if total > 256 << 20 {
            return Err("Extracted firmware resources exceed the size limit.".into());
        }
        let target = dest.join(file.strip_prefix(source).map_err(err)?);
        fs::create_dir_all(target.parent().ok_or("Invalid resource path")?).map_err(err)?;
        fs::copy(file, target).map_err(err)?;
    }
    Ok(())
}
fn validate(root: &Path) -> Result<()> {
    let mut layouts = HashSet::new();
    for name in ["Qwerty", "Swkbd", "common"] {
        let path = root.join(format!("swkbd/lyt/{name}.szs"));
        if name == "Qwerty" || path.exists() {
            layouts.extend(validate_layout(&path)?);
        }
    }
    for name in [
        "SwkbdBaseKeytopQwerty",
        "SwkbdBgKeytop",
        "SwkbdBaseTextAreaLine",
        "SwkbdCaret",
        "BgMask",
    ] {
        if !layouts.contains(&format!("blyt/{name}.bflyt")) {
            return Err(format!(
                "Firmware keyboard resources are incomplete: {name} layout is missing."
            ));
        }
    }
    validate_font(&root.join("fonts/nintendo_udsg-r_std_003.bfttf"))?;
    validate_font(&root.join("fonts/nintendo_ext_003.bfttf"))
}
fn inventory(root: &Path) -> Result<BTreeMap<String, String>> {
    let mut files = Vec::new();
    walk(root, 0, &mut files)?;
    let mut map = BTreeMap::new();
    let mut total = 0u64;
    for file in files {
        total += fs::metadata(&file).map_err(err)?.len();
        if total > 256 << 20 {
            return Err("Extracted firmware exceeds the resource size limit.".into());
        }
        if file
            .file_name()
            .is_some_and(|s| s == "firmware-manifest.json")
        {
            continue;
        }
        map.insert(
            file.strip_prefix(root)
                .map_err(err)?
                .to_string_lossy()
                .replace('\\', "/"),
            hash_file(&file)?,
        );
    }
    Ok(map)
}

pub fn import(source: &Path, keys: &Path, tool_path: &Path, cache: &Path) -> Result<PathBuf> {
    inspect_source(source)?;
    let scratch = Scratch::new(cache)?;
    let input = if source.is_dir() {
        source.to_owned()
    } else {
        let dest = scratch.0.join("input");
        unpack(source, &dest)?;
        dest
    };
    let files = ncas(&input)?;
    if files.is_empty() {
        return Err("No firmware NCA files found in the ZIP.".into());
    }
    println!(
        "Checking {} firmware NCAs before game compilation.",
        files.len()
    );
    let mut selected: BTreeMap<String, (PathBuf, u64, String)> = BTreeMap::new();
    for (i, path) in files.iter().enumerate() {
        let info = tool(
            tool_path,
            keys,
            &["-i".into(), path.to_string_lossy().into_owned()],
        )?;
        let field = |name: &str| {
            info.lines().find_map(|l| {
                l.strip_prefix(name)
                    .and_then(|s| s.strip_prefix(':'))
                    .map(str::trim)
            })
        };
        if let Some(id) = field("Title ID") {
            let id = id.to_ascii_lowercase();
            if TITLES.contains(&id.as_str())
                && matches!(
                    field("Content Type"),
                    Some("Program" | "Data" | "PublicData")
                )
            {
                let size = field("Content Size")
                    .and_then(|s| u64::from_str_radix(s.trim_start_matches("0x"), 16).ok())
                    .unwrap_or(0);
                let hash = hash_file(path)?;
                if let Some((_, old, oldhash)) = selected.get(&id) {
                    if *old == size && *oldhash != hash {
                        return Err(
                            "Firmware dump contains ambiguous versions of a required title.".into(),
                        );
                    }
                    if *old >= size {
                        continue;
                    }
                }
                selected.insert(id, (path.clone(), size, hash));
            }
        }
        if (i + 1) % 100 == 0 || i + 1 == files.len() {
            println!("Firmware NCA scan: {}/{}", i + 1, files.len());
        }
    }
    for id in [KEYBOARD, STD, EXT] {
        if !selected.contains_key(id) {
            return Err(format!(
                "Firmware dump is incomplete: required title {id} is missing. Choose a complete dump or skip firmware."
            ));
        }
    }
    let mut digest = Sha256::new();
    digest.update(b"firmware-import-v1");
    for (id, (_, _, hash)) in &selected {
        digest.update(id);
        digest.update(hash);
    }
    digest.update(hash_file(tool_path)?);
    let fingerprint = format!("{:x}", digest.finalize());
    let target = cache.join(&fingerprint);
    if target.is_dir() {
        let manifest: BTreeMap<String, String> =
            serde_json::from_slice(&fs::read(target.join("firmware-manifest.json")).map_err(err)?)
                .map_err(err)?;
        if inventory(&target)? != manifest {
            return Err(
                "Cached firmware changed. Remove that firmware cache entry and retry.".into(),
            );
        }
        validate(&target)?;
        println!("Verified firmware resources reused.");
        return Ok(target);
    }
    let output = scratch.0.join("resources");
    fs::create_dir(&output).map_err(err)?;
    for (id, (nca, _, expected_hash)) in selected {
        println!("Extracting firmware title {id}.");
        if id == WORDS {
            tool(
                tool_path,
                keys,
                &[
                    format!(
                        "--romfs={}",
                        output.join(format!("{WORDS}.romfs")).display()
                    ),
                    nca.to_string_lossy().into_owned(),
                ],
            )?;
            if hash_file(&nca)? != expected_hash {
                return Err("Firmware changed during extraction. Retry the import.".into());
            }
            continue;
        }
        let extracted = scratch.0.join(&id);
        tool(
            tool_path,
            keys,
            &[
                format!("--romfsdir={}", extracted.display()),
                nca.to_string_lossy().into_owned(),
            ],
        )?;
        if hash_file(&nca)? != expected_hash {
            return Err("Firmware changed during extraction. Retry the import.".into());
        }
        if id == KEYBOARD {
            copy_files(&extracted, &output.join("swkbd"))?;
        } else {
            for file in fs::read_dir(&extracted).map_err(err)? {
                let file = file.map_err(err)?;
                if file
                    .path()
                    .extension()
                    .is_some_and(|s| s.eq_ignore_ascii_case("bfttf"))
                    && file.file_type().map_err(err)?.is_file()
                {
                    fs::create_dir_all(output.join("fonts")).map_err(err)?;
                    fs::copy(file.path(), output.join("fonts").join(file.file_name()))
                        .map_err(err)?;
                }
            }
        }
    }
    validate(&output)?;
    let manifest = inventory(&output)?;
    fs::File::create(output.join("firmware-manifest.json"))
        .map_err(err)?
        .write_all(&serde_json::to_vec_pretty(&manifest).map_err(err)?)
        .map_err(err)?;
    fs::rename(&output, &target).map_err(err)?;
    println!("Firmware keyboard layouts and fonts verified. Original dump kept unchanged.");
    Ok(target)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unsafe_archive_paths() {
        for p in ["../escape", "/absolute", "a/../../bad", "C:/bad", "a\\bad"] {
            assert!(zip_path(p).is_err(), "{p}");
        }
        assert!(zip_path("Firmware/a.nca").is_ok());
    }
    #[test]
    fn corrupt_resources() {
        let tmp = Scratch::new(&std::env::temp_dir()).unwrap();
        let p = tmp.0.join("bad");
        fs::write(&p, [0u8; 64]).unwrap();
        assert!(validate_font(&p).is_err());
        assert!(validate_layout(&p).is_err());
    }
    #[test]
    fn archive_rejection() {
        for names in [vec!["../bad.nca"], vec!["a.nca", "A.nca"]] {
            let tmp = Scratch::new(&std::env::temp_dir()).unwrap();
            let p = tmp.0.join("bad.zip");
            let mut z = zip::ZipWriter::new(fs::File::create(&p).unwrap());
            for n in names {
                z.start_file(n, zip::write::SimpleFileOptions::default())
                    .unwrap();
                z.write_all(b"fake").unwrap();
            }
            z.finish().unwrap();
            assert!(unpack(&p, &tmp.0.join("out")).is_err());
            assert!(!tmp.0.join("out").exists());
        }
    }
    // Self-authored tiny SFNT and SARC fixtures; no Nintendo resources or keys.
    fn font_fixture() -> Vec<u8> {
        let mut head = vec![0u8; 54];
        head[18..20].copy_from_slice(&1024u16.to_be_bytes());
        let mut hhea = vec![0u8; 36];
        hhea[34..36].copy_from_slice(&1u16.to_be_bytes());
        let mut maxp = vec![0u8; 6];
        maxp[..4].copy_from_slice(&0x5000u32.to_be_bytes());
        maxp[4..6].copy_from_slice(&1u16.to_be_bytes());
        let tables = [
            (b"cmap", vec![0u8; 4]),
            (b"head", head),
            (b"hhea", hhea),
            (b"hmtx", vec![0u8; 4]),
            (b"maxp", maxp),
        ];
        let mut sfnt = vec![0u8; 12 + tables.len() * 16];
        sfnt[..4].copy_from_slice(&0x10000u32.to_be_bytes());
        sfnt[4..6].copy_from_slice(&(tables.len() as u16).to_be_bytes());
        for (i, (tag, bytes)) in tables.iter().enumerate() {
            let off = sfnt.len();
            let node = 12 + i * 16;
            sfnt[node..node + 4].copy_from_slice(*tag);
            sfnt[node + 8..node + 12].copy_from_slice(&(off as u32).to_be_bytes());
            sfnt[node + 12..node + 16].copy_from_slice(&(bytes.len() as u32).to_be_bytes());
            sfnt.extend(bytes);
        }
        while sfnt.len() % 4 != 0 {
            sfnt.push(0);
        }
        let mut raw = 0x18029a7fu32.to_le_bytes().to_vec();
        raw.extend([0u8; 4]);
        raw.extend(sfnt);
        raw
    }
    fn layout_fixture(names: &[&str]) -> Vec<u8> {
        let nodes_end = 32 + names.len() * 16;
        let mut strings = Vec::new();
        let mut offsets = Vec::new();
        for name in names {
            offsets.push(strings.len() / 4);
            strings.extend(format!("blyt/{name}.bflyt\0").as_bytes());
            while strings.len() % 4 != 0 {
                strings.push(0);
            }
        }
        let dataoff = nodes_end + 8 + strings.len();
        let mut data = vec![0u8; dataoff + names.len() * 20];
        let len = data.len() as u32;
        data[..4].copy_from_slice(b"SARC");
        data[4..6].copy_from_slice(&20u16.to_le_bytes());
        data[6..8].copy_from_slice(&[0xff, 0xfe]);
        data[8..12].copy_from_slice(&len.to_le_bytes());
        data[12..16].copy_from_slice(&(dataoff as u32).to_le_bytes());
        data[20..24].copy_from_slice(b"SFAT");
        data[26..28].copy_from_slice(&(names.len() as u16).to_le_bytes());
        data[nodes_end..nodes_end + 4].copy_from_slice(b"SFNT");
        data[nodes_end + 8..dataoff].copy_from_slice(&strings);
        for (i, off) in offsets.iter().enumerate() {
            let node = 32 + i * 16;
            let file = dataoff + i * 20;
            data[node + 4..node + 8].copy_from_slice(&(*off as u32).to_le_bytes());
            data[node + 8..node + 12].copy_from_slice(&(i as u32 * 20).to_le_bytes());
            data[node + 12..node + 16].copy_from_slice(&((i as u32 + 1) * 20).to_le_bytes());
            data[file..file + 4].copy_from_slice(b"FLYT");
            data[file + 4..file + 6].copy_from_slice(&[0xff, 0xfe]);
        }
        data
    }
    #[cfg(unix)]
    #[test]
    fn complete_folder_zip_reuse_and_failure_keep_existing_cache() {
        use std::os::unix::fs::PermissionsExt;
        let tmp = Scratch::new(&std::env::temp_dir()).unwrap();
        let root = &tmp.0;
        let source = root.join("dump");
        fs::create_dir(&source).unwrap();
        let keys = root.join("prod.keys");
        fs::write(&keys, b"synthetic keys").unwrap();
        for id in [KEYBOARD, STD, EXT] {
            fs::write(source.join(format!("{id}.nca")), id).unwrap();
        }
        for (id, name) in [
            (STD, "nintendo_udsg-r_std_003.bfttf"),
            (EXT, "nintendo_ext_003.bfttf"),
        ] {
            let p = root.join("templates").join(id);
            fs::create_dir_all(&p).unwrap();
            fs::write(p.join(name), font_fixture()).unwrap();
        }
        let lyt = root.join("templates").join(KEYBOARD).join("lyt");
        fs::create_dir_all(&lyt).unwrap();
        fs::write(
            lyt.join("Qwerty.szs"),
            layout_fixture(&["SwkbdBaseKeytopQwerty"]),
        )
        .unwrap();
        fs::write(
            lyt.join("Swkbd.szs"),
            layout_fixture(&[
                "SwkbdBgKeytop",
                "SwkbdBaseTextAreaLine",
                "SwkbdCaret",
                "BgMask",
            ]),
        )
        .unwrap();
        fs::write(lyt.join("common.szs"), layout_fixture(&[])).unwrap();
        let tool_path = root.join("fake-hactool");
        fs::write(
            &tool_path,
            r#"#!/bin/sh
set -eu
base=$(dirname "$0")
out=''
while [ "$#" -gt 1 ]; do
 case "$1" in --romfsdir=*) out=${1#--romfsdir=};; esac
 shift
done
id=$(cat "$1")
if [ -n "$out" ]; then mkdir -p "$out"; cp -R "$base/templates/$id/." "$out/";
else printf 'Title ID: %s\nContent Type: Data\nContent Size: 0x1000\n' "$id"; fi
"#,
        )
        .unwrap();
        fs::set_permissions(&tool_path, fs::Permissions::from_mode(0o700)).unwrap();
        let cache = root.join("cache");
        let first = import(&source, &keys, &tool_path, &cache).unwrap();
        assert!(first.join("firmware-manifest.json").is_file());
        let archive = root.join("firmware.zip");
        let mut z = zip::ZipWriter::new(fs::File::create(&archive).unwrap());
        for id in [KEYBOARD, STD, EXT] {
            z.start_file(
                format!("Firmware/{id}.nca"),
                zip::write::SimpleFileOptions::default()
                    .compression_method(zip::CompressionMethod::Deflated),
            )
            .unwrap();
            z.write_all(id.as_bytes()).unwrap();
        }
        z.finish().unwrap();
        assert_eq!(import(&archive, &keys, &tool_path, &cache).unwrap(), first);
        fs::remove_file(source.join(format!("{STD}.nca"))).unwrap();
        assert!(import(&source, &keys, &tool_path, &cache).is_err());
        assert!(first.join("fonts/nintendo_ext_003.bfttf").is_file());
        assert_eq!(fs::read_dir(&cache).unwrap().count(), 1);
        fs::write(first.join("fonts/nintendo_ext_003.bfttf"), b"tampered").unwrap();
        assert!(import(&archive, &keys, &tool_path, &cache).is_err());
    }
}
