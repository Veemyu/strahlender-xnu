//! Validate and apply IPS/IPS32 to NSO segments before ahead-of-time recompilation.
use std::{collections::BTreeSet, env, fs, path::Path};

const NSO_HEADER_SIZE: usize = 0x100;
const MAX_PATCH_BYTES: usize = 64 * 1024 * 1024;
const MAX_RECORDS: usize = 100_000;
const MAX_NSO_BYTES: usize = 512 * 1024 * 1024;

struct Segment {
    memory_offset: usize,
    data: Vec<u8>,
}

fn u32_at(data: &[u8], offset: usize) -> Result<usize, String> {
    Ok(u32::from_le_bytes(
        data.get(offset..offset + 4)
            .ok_or("Truncated NSO header")?
            .try_into()
            .unwrap(),
    ) as usize)
}

fn put_u32(data: &mut [u8], offset: usize, value: usize) -> Result<(), String> {
    let value: u32 = value.try_into().map_err(|_| "NSO offset exceeds 32 bits")?;
    data[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    Ok(())
}

fn decode_nso(raw: &[u8]) -> Result<([u8; NSO_HEADER_SIZE], Vec<Segment>), String> {
    if raw.len() < NSO_HEADER_SIZE || &raw[..4] != b"NSO0" {
        return Err("Selected file has no complete NSO0 header".into());
    }
    if raw.len() > MAX_NSO_BYTES {
        return Err("NSO exceeds the supported 512 MiB limit".into());
    }
    let header: [u8; NSO_HEADER_SIZE] = raw[..NSO_HEADER_SIZE].try_into().unwrap();
    let flags = u32_at(&header, 0xc)?;
    let mut segments = Vec::new();
    let mut previous_end = 0;
    for i in 0..3 {
        let file_offset = u32_at(&header, 0x10 + i * 0x10)?;
        let memory_offset = u32_at(&header, 0x14 + i * 0x10)?;
        let decoded_size = u32_at(&header, 0x18 + i * 0x10)?;
        let encoded_size = u32_at(&header, 0x60 + i * 4)?;
        let memory_end = memory_offset
            .checked_add(decoded_size)
            .ok_or("NSO segment range overflow")?;
        if decoded_size > MAX_NSO_BYTES
            || memory_end > MAX_NSO_BYTES
            || memory_offset < previous_end
        {
            return Err("NSO segments overlap or exceed the supported image size".into());
        }
        previous_end = memory_end;
        let encoded = raw
            .get(
                file_offset
                    ..file_offset
                        .checked_add(encoded_size)
                        .ok_or("NSO file range overflow")?,
            )
            .ok_or("NSO segment extends beyond the file")?;
        let data = if flags & (1 << i) != 0 {
            let mut data = vec![0; decoded_size];
            let written = lz4_flex::block::decompress_into(encoded, &mut data)
                .map_err(|error| format!("Cannot decompress NSO segment {i}: {error}"))?;
            if written != decoded_size {
                return Err(format!(
                    "NSO segment {i} decoded to {written} bytes, expected {decoded_size}"
                ));
            }
            data
        } else {
            if encoded_size != decoded_size {
                return Err(format!(
                    "Uncompressed NSO segment {i} has inconsistent lengths"
                ));
            }
            encoded.to_vec()
        };
        segments.push(Segment {
            memory_offset,
            data,
        });
    }
    Ok((header, segments))
}

fn encode_uncompressed_nso(
    mut header: [u8; NSO_HEADER_SIZE],
    segments: &[Segment],
) -> Result<Vec<u8>, String> {
    let mut output = header.to_vec();
    for (i, segment) in segments.iter().enumerate() {
        put_u32(&mut header, 0x10 + i * 0x10, output.len())?;
        put_u32(&mut header, 0x60 + i * 4, segment.data.len())?;
        output.extend_from_slice(&segment.data);
    }
    // Bits 0..2 mark compressed segments; bits 3..5 request original segment hashes.
    let flags = u32_at(&header, 0xc)? & !0x3f;
    put_u32(&mut header, 0xc, flags as usize)?;
    output[..NSO_HEADER_SIZE].copy_from_slice(&header);
    Ok(output)
}

fn apply_to_segments(patch: &Patch, segments: &mut [Segment]) -> Result<(), String> {
    // Validate every byte before mutating any segment, including records crossing gaps.
    for record in &patch.records {
        let mut cursor = record.offset - NSO_HEADER_SIZE;
        let end = cursor
            .checked_add(record.payload.len())
            .ok_or("IPS range overflow")?;
        while cursor < end {
            let segment = segments
                .iter()
                .find(|segment| {
                    cursor >= segment.memory_offset
                        && cursor < segment.memory_offset + segment.data.len()
                })
                .ok_or_else(|| {
                    format!(
                        "IPS record at 0x{:x} targets an NSO gap or BSS",
                        record.offset
                    )
                })?;
            cursor = end.min(segment.memory_offset + segment.data.len());
        }
    }
    for record in &patch.records {
        let mut cursor = record.offset - NSO_HEADER_SIZE;
        let end = cursor + record.payload.len();
        while cursor < end {
            let segment = segments
                .iter_mut()
                .find(|segment| {
                    cursor >= segment.memory_offset
                        && cursor < segment.memory_offset + segment.data.len()
                })
                .unwrap();
            let in_segment = cursor - segment.memory_offset;
            let count = (end - cursor).min(segment.data.len() - in_segment);
            let source_offset = cursor - (record.offset - NSO_HEADER_SIZE);
            let destination = &mut segment.data[in_segment..in_segment + count];
            match &record.payload {
                Payload::Bytes(bytes) => {
                    destination.copy_from_slice(&bytes[source_offset..source_offset + count])
                }
                Payload::Repeat { value, .. } => destination.fill(*value),
            }
            cursor += count;
        }
    }
    Ok(())
}

fn apply(nso: &Path, patch_paths: &[&Path], output: &Path) -> Result<(), String> {
    if patch_paths.is_empty() {
        return Err("At least one IPS patch is required".into());
    }
    let raw = fs::read(nso).map_err(|error| format!("Cannot read NSO: {error}"))?;
    let (header, mut segments) = decode_nso(&raw)?;
    let build_id: [u8; 32] = header[0x40..0x60].try_into().unwrap();
    for path in patch_paths {
        if !matches_build_id(path, &build_id)? {
            return Err(format!(
                "{} does not match NSO build ID {}",
                path.display(),
                hex_id(&build_id)
            ));
        }
        let patch = read_patch(path)?;
        apply_to_segments(&patch, &mut segments)
            .map_err(|error| format!("{}: {error}", path.display()))?;
        println!(
            "Applied {}: {} records",
            path.display(),
            patch.records.len()
        );
    }
    let bytes = encode_uncompressed_nso(header, &segments)?;
    if let Some(parent) = output.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("Cannot create output folder: {error}"))?;
    }
    let temporary = output.with_extension(format!("nso.{}.tmp", std::process::id()));
    fs::write(&temporary, bytes).map_err(|error| format!("Cannot write staged NSO: {error}"))?;
    if let Err(error) = fs::rename(&temporary, output) {
        if error.kind() != std::io::ErrorKind::AlreadyExists {
            return Err(format!("Cannot publish staged NSO: {error}"));
        }
        fs::remove_file(output).map_err(|error| format!("Cannot replace staged NSO: {error}"))?;
        fs::rename(&temporary, output)
            .map_err(|error| format!("Cannot publish staged NSO: {error}"))?;
    }
    Ok(())
}

fn hex_id(id: &[u8; 32]) -> String {
    id.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn read_patch(path: &Path) -> Result<Patch, String> {
    let size = fs::metadata(path)
        .map_err(|error| format!("Cannot stat {}: {error}", path.display()))?
        .len();
    if size > MAX_PATCH_BYTES as u64 {
        return Err(format!(
            "{} exceeds the supported 64 MiB patch limit",
            path.display()
        ));
    }
    let bytes =
        fs::read(path).map_err(|error| format!("Cannot read {}: {error}", path.display()))?;
    parse(&bytes).map_err(|error| format!("{}: {error}", path.display()))
}

fn stage(base: &Path, mod_exefs: &Path, output: &Path) -> Result<(), String> {
    if output.exists() {
        return Err(format!(
            "Staging folder already exists: {}",
            output.display()
        ));
    }
    let mut patches = Vec::new();
    let mut extra_module = None;
    for item in fs::read_dir(mod_exefs)
        .map_err(|error| format!("Cannot read mod ExeFS {}: {error}", mod_exefs.display()))?
    {
        let item = item.map_err(|error| format!("Cannot read mod ExeFS entry: {error}"))?;
        let path = item.path();
        if matches!(
            item.file_name()
                .to_string_lossy()
                .to_ascii_lowercase()
                .as_str(),
            "license" | "notice" | ".ds_store"
        ) {
            continue;
        }
        if !item
            .file_type()
            .map_err(|error| error.to_string())?
            .is_file()
        {
            return Err(format!("Unsupported ExeFS entry: {}", path.display()));
        }
        if item
            .file_name()
            .to_string_lossy()
            .eq_ignore_ascii_case("subsdk1")
        {
            if extra_module.replace(path).is_some() {
                return Err("Duplicate subsdk1 module".into());
            }
            continue;
        }
        let extension = path.extension().and_then(|s| s.to_str()).unwrap_or("");
        if !extension.eq_ignore_ascii_case("ips") && !extension.eq_ignore_ascii_case("ips32") {
            return Err(format!(
                "Unsupported ExeFS file: {} (supported: IPS/IPS32 and subsdk1)",
                path.display()
            ));
        }
        read_patch(&path)?;
        patches.push(path);
    }
    if patches.is_empty() && extra_module.is_none() {
        return Err("No IPS/IPS32 files or subsdk1 found in the selected ExeFS folder".into());
    }
    patches.sort();
    let mut modules = vec!["rtld", "main", "sdk", "subsdk0"];
    if let Some(path) = &extra_module {
        // Lumi's hooks use this fixed main-relative address on both Apple layouts.
        validate_module_slot(&base.join("main"), 0x5708000)?;
        validate_module_slot(path, 0x6000000 - 0x5708000)?;
        modules.push("subsdk1");
    }
    let source_for = |name: &str| {
        if name == "subsdk1" {
            extra_module.as_ref().unwrap().clone()
        } else {
            base.join(name)
        }
    };
    let ids = modules
        .iter()
        .map(|name| nso_build_id(&source_for(name)))
        .collect::<Result<Vec<_>, _>>()?;
    let mut assigned = vec![Vec::<&Path>::new(); modules.len()];
    for patch in &patches {
        let mut candidates = Vec::new();
        for (index, id) in ids.iter().enumerate() {
            if matches_build_id(patch, id)? {
                candidates.push(index);
            }
        }
        if candidates.len() != 1 {
            let available = modules
                .iter()
                .zip(ids.iter())
                .map(|(name, id)| format!("{name}={}", hex_id(id)))
                .collect::<Vec<_>>()
                .join(", ");
            return Err(format!(
                "{} matches {} base NSO build IDs; check the game update version (available: {})",
                patch.display(),
                candidates.len(),
                available
            ));
        }
        if candidates[0] == 0 {
            return Err(format!(
                "{} targets rtld, whose code is replaced by this runtime; rtld IPS is not supported",
                patch.display()
            ));
        }
        assigned[candidates[0]].push(patch);
    }
    if let Some(parent) = output.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("Cannot create staging parent: {error}"))?;
    }
    let temporary = output.with_extension(format!("stage.{}.tmp", std::process::id()));
    if temporary.exists() {
        return Err(format!(
            "Staging work folder already exists: {}",
            temporary.display()
        ));
    }
    fs::create_dir_all(&temporary)
        .map_err(|error| format!("Cannot create staging folder: {error}"))?;
    let result = (|| {
        for (index, name) in modules.iter().enumerate() {
            let source = source_for(name);
            let destination = temporary.join(name);
            if assigned[index].is_empty() {
                fs::copy(&source, &destination)
                    .map_err(|error| format!("Cannot stage {name}: {error}"))?;
            } else {
                apply(&source, &assigned[index], &destination)?;
            }
        }
        fs::copy(base.join("main.npdm"), temporary.join("main.npdm"))
            .map_err(|error| format!("Cannot stage main.npdm: {error}"))?;
        if extra_module.is_some() {
            stage_cross_entries(&temporary, &modules)?;
        }
        fs::rename(&temporary, output)
            .map_err(|error| format!("Cannot publish staging folder: {error}"))?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_dir_all(&temporary);
    }
    result
}

fn validate_module_slot(path: &Path, slot_size: usize) -> Result<(), String> {
    let raw = fs::read(path).map_err(|error| format!("Cannot read {}: {error}", path.display()))?;
    let (header, segments) =
        decode_nso(&raw).map_err(|error| format!("{}: {error}", path.display()))?;
    let data = &segments[2];
    let end = data
        .memory_offset
        .checked_add(data.data.len())
        .and_then(|size| size.checked_add(u32_at(&header, 0x3c).ok()?))
        .and_then(|size| size.checked_add(0xfff))
        .map(|size| size & !0xfff)
        .ok_or("NSO image size overflow")?;
    if end > slot_size {
        return Err(format!(
            "{} image {end:#x} overlaps the next module (slot {slot_size:#x})",
            path.display()
        ));
    }
    Ok(())
}

fn branch_target(word: u32, pc: i64) -> Option<i64> {
    let (immediate, bits) = if word & 0x7c000000 == 0x14000000 {
        (word & 0x03ffffff, 26)
    } else if word & 0xff000010 == 0x54000000 || word & 0x7e000000 == 0x34000000 {
        ((word >> 5) & 0x7ffff, 19)
    } else if word & 0x7e000000 == 0x36000000 {
        ((word >> 5) & 0x3fff, 14)
    } else {
        return None;
    };
    let signed = ((immediate as i64) << (64 - bits)) >> (64 - bits);
    Some(pc + signed * 4)
}

fn stage_cross_entries(folder: &Path, names: &[&str]) -> Result<(), String> {
    let mut texts = Vec::new();
    for name in names {
        let base = match *name {
            "main" => 0,
            "sdk" => 0x6000000,
            "subsdk0" => 0x7000000,
            "rtld" => 0x8000000,
            "subsdk1" => 0x5708000,
            _ => unreachable!(),
        };
        let raw = fs::read(folder.join(name)).map_err(|error| error.to_string())?;
        let (_, segments) = decode_nso(&raw)?;
        let text = segments.into_iter().next().unwrap();
        texts.push((base, text));
    }
    let mut entries = vec![BTreeSet::new(); names.len()];
    for (source, (base, text)) in texts.iter().enumerate() {
        for (index, bytes) in text.data.chunks_exact(4).enumerate() {
            let pc = base + text.memory_offset as i64 + (index * 4) as i64;
            let Some(target) = branch_target(u32::from_le_bytes(bytes.try_into().unwrap()), pc)
            else {
                continue;
            };
            for (destination, (other_base, other)) in texts.iter().enumerate() {
                let lo = other_base + other.memory_offset as i64;
                if source != destination && target >= lo && target < lo + other.data.len() as i64 {
                    entries[destination].insert(target - other_base);
                }
            }
        }
    }
    for (name, offsets) in names.iter().zip(entries) {
        let text = offsets
            .iter()
            .map(|offset| format!("{offset:x}\n"))
            .collect::<String>();
        fs::write(folder.join(format!("{name}.entries")), text)
            .map_err(|error| error.to_string())?;
        println!("{name}: {} cross-module entry points", offsets.len());
    }
    Ok(())
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum Payload {
    Bytes(Vec<u8>),
    Repeat { count: usize, value: u8 },
}

impl Payload {
    fn len(&self) -> usize {
        match self {
            Self::Bytes(bytes) => bytes.len(),
            Self::Repeat { count, .. } => *count,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct Record {
    offset: usize,
    payload: Payload,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct Patch {
    format: &'static str,
    records: Vec<Record>,
}

fn take<'a>(data: &'a [u8], position: &mut usize, count: usize) -> Result<&'a [u8], String> {
    let end = position.checked_add(count).ok_or("Patch length overflow")?;
    let bytes = data.get(*position..end).ok_or("Truncated IPS record")?;
    *position = end;
    Ok(bytes)
}

fn be(bytes: &[u8]) -> usize {
    bytes
        .iter()
        .fold(0usize, |value, byte| (value << 8) | usize::from(*byte))
}

fn parse(data: &[u8]) -> Result<Patch, String> {
    if data.len() > MAX_PATCH_BYTES {
        return Err("IPS patch is larger than the supported 64 MiB limit".into());
    }
    let (format, offset_width, eof, mut position) = if data.starts_with(b"PATCH") {
        ("IPS", 3, b"EOF".as_slice(), 5)
    } else if data.starts_with(b"IPS32") {
        ("IPS32", 4, b"EEOF".as_slice(), 5)
    } else {
        return Err("Expected an IPS or IPS32 header".into());
    };
    let mut records = Vec::new();
    loop {
        if data.get(position..position + eof.len()) == Some(eof) {
            position += eof.len();
            if position != data.len() {
                return Err(
                    "IPS truncate-size trailers are not supported for fixed-size NSO images".into(),
                );
            }
            break;
        }
        if records.len() >= MAX_RECORDS {
            return Err("IPS patch has too many records".into());
        }
        let offset = be(take(data, &mut position, offset_width)?);
        let size = be(take(data, &mut position, 2)?);
        let payload = if size == 0 {
            let count = be(take(data, &mut position, 2)?);
            let value = take(data, &mut position, 1)?[0];
            if count == 0 {
                return Err("Zero-length IPS RLE record".into());
            }
            Payload::Repeat { count, value }
        } else {
            Payload::Bytes(take(data, &mut position, size)?.to_vec())
        };
        if offset < NSO_HEADER_SIZE {
            return Err(format!(
                "IPS record at 0x{offset:x} targets the protected NSO header"
            ));
        }
        offset
            .checked_add(payload.len())
            .ok_or("IPS record range overflow")?;
        records.push(Record { offset, payload });
    }
    Ok(Patch { format, records })
}

#[allow(dead_code)]
fn apply_to_mapped_nso(patch: &Patch, mapped: &mut [u8]) -> Result<(), String> {
    // Atmosphere protects the 0x100-byte NSO header and subtracts that offset
    // before writing into the uncompressed, mapped module image.
    for record in &patch.records {
        let start = record.offset - NSO_HEADER_SIZE;
        let end = start
            .checked_add(record.payload.len())
            .ok_or("IPS record range overflow")?;
        if end > mapped.len() {
            return Err(format!(
                "IPS record at 0x{:x} exceeds the mapped NSO",
                record.offset
            ));
        }
    }
    for record in &patch.records {
        let start = record.offset - NSO_HEADER_SIZE;
        let end = start + record.payload.len();
        let destination = &mut mapped[start..end];
        match &record.payload {
            Payload::Bytes(bytes) => destination.copy_from_slice(bytes),
            Payload::Repeat { value, .. } => destination.fill(*value),
        }
    }
    Ok(())
}

fn inspect(path: &Path) -> Result<(), String> {
    let patch = read_patch(path)?;
    let changed = patch
        .records
        .iter()
        .map(|record| record.payload.len())
        .sum::<usize>();
    println!(
        "{}: {} records, {} patch bytes",
        patch.format,
        patch.records.len(),
        changed
    );
    Ok(())
}

fn nso_build_id(path: &Path) -> Result<[u8; 32], String> {
    use std::io::Read;
    let mut file = fs::File::open(path).map_err(|error| format!("Cannot open NSO: {error}"))?;
    let mut header = [0u8; NSO_HEADER_SIZE];
    file.read_exact(&mut header)
        .map_err(|error| format!("Cannot read NSO header: {error}"))?;
    if &header[..4] != b"NSO0" {
        return Err("Selected file has no NSO0 header".into());
    }
    Ok(header[0x40..0x60].try_into().unwrap())
}

fn matches_build_id(patch: &Path, build_id: &[u8; 32]) -> Result<bool, String> {
    let stem = patch
        .file_stem()
        .and_then(|stem| stem.to_str())
        .ok_or("Patch filename is not valid UTF-8")?;
    if stem.is_empty() || stem.len() > 64 || stem.len() % 2 != 0 {
        return Err("Patch filename must be an even-length hexadecimal NSO build ID".into());
    }
    let expected = stem
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            let text = std::str::from_utf8(pair).unwrap();
            u8::from_str_radix(text, 16)
                .map_err(|_| "Patch filename is not a hexadecimal build ID".to_owned())
        })
        .collect::<Result<Vec<_>, _>>()?;
    let significant = build_id
        .iter()
        .rposition(|byte| *byte != 0)
        .map_or(0, |index| index + 1);
    Ok(expected.len() >= significant && build_id.starts_with(&expected))
}

fn main() {
    let mut arguments = env::args_os().skip(1);
    let Some(command) = arguments.next() else {
        eprintln!(
            "Usage: ips_patch inspect <patch.ips> [--nso <main>] | apply <main> <output> <patch.ips>... | stage <base-exefs> <mod-exefs> <output>"
        );
        std::process::exit(2);
    };
    if command == "stage" {
        let values: Vec<_> = arguments.collect();
        if values.len() != 3 {
            eprintln!("Usage: ips_patch stage <base-exefs> <mod-exefs> <output>");
            std::process::exit(2);
        }
        if let Err(error) = stage(
            Path::new(&values[0]),
            Path::new(&values[1]),
            Path::new(&values[2]),
        ) {
            eprintln!("IPS: {error}");
            std::process::exit(1);
        }
        return;
    }
    if command == "apply" {
        let Some(nso) = arguments.next() else {
            eprintln!("Usage: ips_patch apply <main> <output> <patch.ips>...");
            std::process::exit(2);
        };
        let Some(output) = arguments.next() else {
            eprintln!("Usage: ips_patch apply <main> <output> <patch.ips>...");
            std::process::exit(2);
        };
        let patches: Vec<_> = arguments.collect();
        let paths: Vec<_> = patches.iter().map(Path::new).collect();
        if let Err(error) = apply(Path::new(&nso), &paths, Path::new(&output)) {
            eprintln!("IPS: {error}");
            std::process::exit(1);
        }
        return;
    }
    let Some(path) = arguments.next() else {
        eprintln!("Usage: ips_patch inspect <patch.ips>");
        std::process::exit(2);
    };
    let nso = match (arguments.next(), arguments.next(), arguments.next()) {
        (None, None, None) => None,
        (Some(flag), Some(path), None) if flag == "--nso" => Some(path),
        _ => {
            eprintln!("Usage: ips_patch inspect <patch.ips> [--nso <original.nso>]");
            std::process::exit(2);
        }
    };
    if command != "inspect" {
        eprintln!("Usage: ips_patch inspect <patch.ips>");
        std::process::exit(2);
    }
    let result = inspect(Path::new(&path)).and_then(|_| {
        if let Some(nso) = nso {
            let id = nso_build_id(Path::new(&nso))?;
            if !matches_build_id(Path::new(&path), &id)? {
                return Err("IPS filename does not match the selected NSO build ID".into());
            }
            println!("NSO build ID matches the IPS filename");
        }
        Ok(())
    });
    if let Err(error) = result {
        eprintln!("IPS: {error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ips_and_ips32_apply_with_header_adjustment() {
        let ips = parse(b"PATCH\x00\x01\x01\x00\x02\x11\x22EOF").unwrap();
        let ips32 = parse(b"IPS32\x00\x00\x01\x03\x00\x00\x00\x03\x7fEEOF").unwrap();
        let mut mapped = vec![0; 8];
        apply_to_mapped_nso(&ips, &mut mapped).unwrap();
        apply_to_mapped_nso(&ips32, &mut mapped).unwrap();
        assert_eq!(mapped, [0, 0x11, 0x22, 0x7f, 0x7f, 0x7f, 0, 0]);
    }

    #[test]
    fn malformed_and_header_records_are_rejected() {
        for bytes in [
            b"PATCH".as_slice(),
            b"PATCH\x00\x00\x00\x00\x01\xffEOF",
            b"PATCH\x00\x01\x00\x00\x02\xffEOF",
            b"PATCH\x00\x01\x00\x00\x01\xffEOF\x00",
        ] {
            assert!(parse(bytes).is_err());
        }
    }

    #[test]
    fn range_failure_leaves_mapped_image_unchanged() {
        let patch = parse(b"PATCH\x00\x01\x00\x00\x01\xaa\x00\x01\x08\x00\x01\xbbEOF").unwrap();
        let mut mapped = [0u8; 4];
        assert!(apply_to_mapped_nso(&patch, &mut mapped).is_err());
        assert_eq!(mapped, [0; 4]);
    }

    #[test]
    fn compressed_nso_patch_round_trips_and_preserves_build_id() {
        let mut header = [0u8; NSO_HEADER_SIZE];
        header[..4].copy_from_slice(b"NSO0");
        header[0x40..0x42].copy_from_slice(&[0xaa, 0xbb]);
        put_u32(&mut header, 0xc, 0x3f).unwrap();
        let originals = [b"TEXT".as_slice(), b"RODATA".as_slice(), b"DATA".as_slice()];
        let offsets = [0, 8, 16];
        let mut raw = header.to_vec();
        for (i, original) in originals.iter().enumerate() {
            let compressed = lz4_flex::block::compress(original);
            let file_offset = raw.len();
            put_u32(&mut raw, 0x10 + i * 0x10, file_offset).unwrap();
            put_u32(&mut raw, 0x14 + i * 0x10, offsets[i]).unwrap();
            put_u32(&mut raw, 0x18 + i * 0x10, original.len()).unwrap();
            put_u32(&mut raw, 0x60 + i * 4, compressed.len()).unwrap();
            raw.extend(compressed);
        }
        let (header, mut segments) = decode_nso(&raw).unwrap();
        let patch = parse(b"IPS32\x00\x00\x01\x08\x00\x02\x99\x88EEOF").unwrap();
        apply_to_segments(&patch, &mut segments).unwrap();
        let encoded = encode_uncompressed_nso(header, &segments).unwrap();
        let (new_header, new_segments) = decode_nso(&encoded).unwrap();
        assert_eq!(&new_header[0x40..0x42], &[0xaa, 0xbb]);
        assert_eq!(u32_at(&new_header, 0xc).unwrap() & 0x3f, 0);
        assert_eq!(new_segments[0].data, b"TEXT");
        assert_eq!(new_segments[1].data, b"\x99\x88DATA");
        assert_eq!(new_segments[2].data, b"DATA");
    }

    #[test]
    fn patch_in_unbacked_gap_is_rejected_without_changes() {
        let mut segments = vec![
            Segment {
                memory_offset: 0,
                data: b"TEXT".to_vec(),
            },
            Segment {
                memory_offset: 8,
                data: b"DATA".to_vec(),
            },
        ];
        let patch = parse(b"PATCH\x00\x01\x05\x00\x01\xffEOF").unwrap();
        assert!(apply_to_segments(&patch, &mut segments).is_err());
        assert_eq!(segments[0].data, b"TEXT");
        assert_eq!(segments[1].data, b"DATA");
    }

    #[test]
    fn truncated_subsdk1_is_rejected_before_staging() {
        let folder = std::env::temp_dir().join(format!("ips-stage-test-{}", std::process::id()));
        let mod_exefs = folder.join("exefs");
        let output = folder.join("staged");
        fs::create_dir_all(folder.join("base")).unwrap();
        fs::write(folder.join("base/main"), synthetic_nso(1, 0xd65f03c0, 0)).unwrap();
        fs::create_dir_all(&mod_exefs).unwrap();
        fs::write(mod_exefs.join("subsdk1"), b"NSO0").unwrap();
        let error = stage(&folder.join("base"), &mod_exefs, &output).unwrap_err();
        assert!(error.contains("complete NSO0 header"));
        assert!(!output.exists());
        fs::remove_dir_all(folder).unwrap();
    }

    fn synthetic_nso(id: u8, word: u32, bss: usize) -> Vec<u8> {
        let mut header = [0; NSO_HEADER_SIZE];
        header[..4].copy_from_slice(b"NSO0");
        header[0x40] = id;
        put_u32(&mut header, 0x3c, bss).unwrap();
        let segments = (0..3)
            .map(|i| {
                put_u32(&mut header, 0x14 + i * 0x10, i * 0x1000).unwrap();
                put_u32(&mut header, 0x18 + i * 0x10, 4).unwrap();
                Segment {
                    memory_offset: i * 0x1000,
                    data: if i == 0 {
                        word.to_le_bytes().to_vec()
                    } else {
                        vec![0; 4]
                    },
                }
            })
            .collect::<Vec<_>>();
        encode_uncompressed_nso(header, &segments).unwrap()
    }

    #[test]
    fn stages_extra_module_patches_and_cross_module_return_entries_atomically() {
        let folder = std::env::temp_dir().join(format!("ips-stage-extra-{}", std::process::id()));
        let base = folder.join("base");
        let mods = folder.join("mods");
        fs::create_dir_all(&base).unwrap();
        fs::create_dir_all(&mods).unwrap();
        for (i, name) in ["main", "sdk", "subsdk0", "rtld"].iter().enumerate() {
            let word = if i == 0 {
                0x14000000 | (0x5708000 / 4)
            } else {
                0xd65f03c0
            };
            fs::write(base.join(name), synthetic_nso(i as u8 + 1, word, 0)).unwrap();
        }
        fs::write(base.join("main.npdm"), b"synthetic").unwrap();
        let branch_back = 0x14000000 | (((-0x5708000i64 / 4) as u32) & 0x03ffffff);
        fs::write(mods.join("subsdk1"), synthetic_nso(5, branch_back, 0)).unwrap();
        fs::write(mods.join("05.ips"), b"PATCH\x00\x21\x00\x00\x01\x99EOF").unwrap();
        let output = folder.join("staged");
        stage(&base, &mods, &output).unwrap();
        assert_eq!(
            fs::read_to_string(output.join("main.entries")).unwrap(),
            "0\n"
        );
        assert_eq!(
            fs::read_to_string(output.join("subsdk1.entries")).unwrap(),
            "0\n"
        );
        let (_, extra) = decode_nso(&fs::read(output.join("subsdk1")).unwrap()).unwrap();
        assert_eq!(extra[2].data[0], 0x99);
        let (_, original) = decode_nso(&fs::read(mods.join("subsdk1")).unwrap()).unwrap();
        assert_eq!(original[2].data[0], 0);
        fs::remove_dir_all(folder).unwrap();
    }

    #[test]
    fn extra_module_image_includes_bss_and_cannot_overlap_sdk() {
        let path = std::env::temp_dir().join(format!("ips-module-slot-{}", std::process::id()));
        fs::write(&path, synthetic_nso(1, 0xd65f03c0, 0x900000)).unwrap();
        assert!(
            validate_module_slot(&path, 0x8f8000)
                .unwrap_err()
                .contains("overlaps")
        );
        fs::remove_file(path).unwrap();
        assert_eq!(branch_target(0x17ffffff, 8), Some(4));
        assert_eq!(branch_target(0x94000004, 8), Some(24));
        assert_eq!(branch_target(0x54000040, 8), Some(16));
        assert_eq!(branch_target(0xd65f03c0, 8), None);
    }

    #[test]
    fn build_id_match_accepts_only_trailing_zero_bytes_omitted() {
        let mut id = [0u8; 32];
        id[..4].copy_from_slice(&[0xab, 0xcd, 0xef, 0x12]);
        assert!(matches_build_id(Path::new("ABCDEF12.ips"), &id).unwrap());
        assert!(matches_build_id(Path::new("ABCDEF1200.ips"), &id).unwrap());
        assert!(!matches_build_id(Path::new("ABCDEF.ips"), &id).unwrap());
        assert!(!matches_build_id(Path::new("ABCDEF13.ips"), &id).unwrap());
    }

    #[test]
    fn reads_build_id_from_nso_header() {
        let path = std::env::temp_dir().join(format!("ips-patch-nso-{}", std::process::id()));
        let mut header = [0u8; NSO_HEADER_SIZE];
        header[..4].copy_from_slice(b"NSO0");
        header[0x40..0x44].copy_from_slice(&[0xab, 0xcd, 0xef, 0x12]);
        fs::write(&path, header).unwrap();
        let id = nso_build_id(&path).unwrap();
        fs::remove_file(path).unwrap();
        assert_eq!(&id[..4], &[0xab, 0xcd, 0xef, 0x12]);
    }
}
