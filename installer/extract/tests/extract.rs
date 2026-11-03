//! End-to-end run with a fake hactool shell script: no game data, no keys.
#![cfg(unix)]
use bdsp_extract::{Outcome, Request, extract, up_to_date};
use std::{
    fs,
    path::{Path, PathBuf},
};

fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("bdsp-extract-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    dir
}

fn jpeg() -> Vec<u8> {
    let mut out = std::io::Cursor::new(Vec::new());
    image::DynamicImage::ImageRgb8(image::RgbImage::from_pixel(
        32,
        32,
        image::Rgb([200, 30, 30]),
    ))
    .write_to(&mut out, image::ImageFormat::Jpeg)
    .unwrap();
    out.into_inner()
}

/// Behaves like the parts of hactool the stage uses; the update container holds update-*.nca.
fn fake_hactool(dir: &Path) -> PathBuf {
    let mut nacp = vec![0u8; 0x4000];
    nacp[..7].copy_from_slice(b"Diamond");
    nacp[0x3060..0x3065].copy_from_slice(b"1.3.0");
    fs::write(dir.join("fixture.nacp"), nacp).unwrap();
    fs::write(dir.join("fixture.jpg"), jpeg()).unwrap();
    let mut meta = vec![0u8; 16];
    meta[8..12].copy_from_slice(&0x30000u32.to_le_bytes());
    fs::write(dir.join("fixture.cnmt"), meta).unwrap();
    let script = format!(
        r#"#!/bin/sh
F="{dir}"
case "$1$2$3" in
  -k*) shift 2;;
esac
shift 2
for a in "$@"; do last="$a"; done
case "$1" in
  -i) b=$(basename "$last")
      case "$b" in
        *program*) t=Program; s=0x2000; tid=0100000011d90000;;
        *control*) t=Control; s=0x100;  tid=0100000011d90800;;
        *) t=Meta; s=0x80; tid=0100000011d90800;;
      esac
      printf 'Title ID:    %s\nContent Type:  %s\nContent Size:  %s\nHeader Key: SECRET\n' "$tid" "$t" "$s"; exit 0;;
  -t) for a in "$@"; do case "$a" in --securedir=*|--pfs0dir=*) d="${{a#*=}}";; esac; done
      mkdir -p "$d"; p=base; case "$last" in *update*) p=update;; esac
      echo x > "$d/$p-program.nca"; echo x > "$d/$p-control.nca"; echo x > "$d/$p-meta.nca"; exit 0;;
esac
for a in "$@"; do
  case "$a" in
    --exefsdir=*) mkdir -p "${{a#*=}}"; echo main > "${{a#*=}}/main"; echo npdm > "${{a#*=}}/main.npdm";;
    --section0dir=*) mkdir -p "${{a#*=}}"; cp "$F/fixture.cnmt" "${{a#*=}}/x.cnmt";;
    --romfsdir=*) d="${{a#*=}}"; mkdir -p "$d"
      case "$last" in
        *control*) cp "$F/fixture.nacp" "$d/control.nacp"; cp "$F/fixture.jpg" "$d/icon_AmericanEnglish.dat";;
        *) echo asset > "$d/asset.bin";;
      esac;;
  esac
done
exit 0
"#,
        dir = dir.display()
    );
    let path = dir.join("hactool");
    fs::write(&path, script).unwrap();
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    path
}

fn request(dir: &Path, update: bool) -> Request {
    fs::write(dir.join("game.xci"), b"container").unwrap();
    fs::write(dir.join("game-update.nsp"), b"update").unwrap();
    fs::write(dir.join("prod.keys"), b"synthetic").unwrap();
    Request {
        base: dir.join("game.xci"),
        update: update.then(|| dir.join("game-update.nsp")),
        keys: dir.join("prod.keys"),
        title_keys: None,
        hactool: fake_hactool(dir),
        work: dir.join("work"),
        icons: Some(dir.join("work/icons")),
        force: false,
        keep_nca: false,
    }
}

#[test]
fn extracts_publishes_icons_and_skips_when_nothing_changed() {
    let dir = scratch("flow");
    let request = request(&dir, true);
    let mut lines = Vec::new();
    assert_eq!(
        extract(&request, &mut |l| lines.push(l.to_string())).unwrap(),
        Outcome::Extracted
    );
    let work = &request.work;
    assert!(work.join("exefs/main").is_file() && work.join("romfs/asset.bin").is_file());
    assert!(!work.join(".stage").exists() && !work.join(".previous").exists());
    let record: serde_json::Value =
        serde_json::from_slice(&fs::read(work.join("manifest.json")).unwrap()).unwrap();
    assert_eq!(record["title_id"], "0100000011d90000");
    assert_eq!(
        (
            record["title_version"].as_u64(),
            record["display_version"].as_str()
        ),
        (Some(0x30000), Some("1.3.0"))
    );
    assert_eq!(record["update_applied"], true);
    let icons: serde_json::Value =
        serde_json::from_slice(&fs::read(work.join("icons/icons.json")).unwrap()).unwrap();
    assert_eq!(icons["default"], "en-US");
    let image = icons["variants"][0]["image"].as_str().unwrap();
    assert!(work.join("icons").join(image).is_file());
    assert!(!lines.iter().any(|l| l.contains("SECRET")));
    assert!(up_to_date(&request).unwrap());
    assert_eq!(extract(&request, &mut |_| {}).unwrap(), Outcome::Skipped);
    fs::remove_file(work.join("icons/icons.json")).unwrap();
    assert!(
        !up_to_date(&request).unwrap(),
        "missing icons must defeat the cache"
    );
    fs::write(work.join("exefs/main"), b"tampered").unwrap();
    assert!(
        !up_to_date(&Request {
            icons: None,
            ..request
        })
        .unwrap()
    );
    fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn base_game_only_and_failures_report_stable_exit_codes() {
    let dir = scratch("base");
    let base_only = request(&dir, false);
    assert_eq!(
        extract(&base_only, &mut |_| {}).unwrap(),
        Outcome::Extracted
    );
    let record: serde_json::Value =
        serde_json::from_slice(&fs::read(base_only.work.join("manifest.json")).unwrap()).unwrap();
    assert_eq!(record["update_applied"], false);
    let missing = Request {
        base: dir.join("missing.xci"),
        force: true,
        ..request(&dir, false)
    };
    assert_eq!(extract(&missing, &mut |_| {}).unwrap_err().code, 3);
    fs::write(dir.join("broken"), "#!/bin/sh\nexit 1\n").unwrap();
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(dir.join("broken"), fs::Permissions::from_mode(0o755)).unwrap();
    let broken = Request {
        hactool: dir.join("broken"),
        force: true,
        ..request(&dir, false)
    };
    assert_eq!(extract(&broken, &mut |_| {}).unwrap_err().code, 5);
    assert!(
        base_only.work.join("exefs/main").is_file(),
        "a failed run must keep the previous result"
    );
    fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn a_failed_unpack_names_the_missing_key_but_never_prints_key_values_or_hactool_warnings() {
    let dir = scratch("keys");
    let secret = "34c1a0c48258f8b4fa9e5e6adafc7e4f";
    let script = format!(
        "#!/bin/sh\necho '[WARN]: Failed to match key \"x\", (value \"{secret}\")' >&2\necho 'Error: section 0 is corrupted!' >&2\nexit 1\n"
    );
    fs::write(dir.join("broken"), script).unwrap();
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(dir.join("broken"), fs::Permissions::from_mode(0o755)).unwrap();
    let request = Request {
        hactool: dir.join("broken"),
        ..request(&dir, false)
    };
    fs::write(
        &request.keys,
        format!("master_key_00 = {secret}\r\ntitlekek_source = {secret}\r\n"),
    )
    .unwrap();
    let mut log = Vec::new();
    let failure = extract(&request, &mut |line| log.push(line.to_string())).unwrap_err();
    assert_eq!(failure.code, 5);
    assert!(
        failure
            .message
            .contains("hactool exit code 1; Error: section 0 is corrupted!")
    );
    assert!(
        failure.message.contains("header_key is missing"),
        "{}",
        failure.message
    );
    let everything = format!("{}\n{}", failure.message, log.join("\n"));
    assert!(!everything.contains(secret) && !everything.contains("WARN"));
    assert!(
        log.iter()
            .any(|l| l.contains("prod.keys: master_key_00 to master_key_00"))
    );
    fs::remove_dir_all(&dir).unwrap();
}

fn cnmt(title: u64, version: u32, kind: u8, contents: &[(u8, u8)]) -> Vec<u8> {
    let mut data = vec![0u8; 0x20];
    data[..8].copy_from_slice(&title.to_le_bytes());
    data[8..12].copy_from_slice(&version.to_le_bytes());
    data[0xC] = kind;
    data[0x10..0x12].copy_from_slice(&(contents.len() as u16).to_le_bytes());
    for (id, content) in contents {
        let mut record = vec![0u8; 0x38];
        record[0x20..0x30].fill(*id);
        record[0x36] = *content;
        data.extend(record);
    }
    data
}

/// A combined XCI: the secure partition holds base and update NCAs (content ID file names) of one title family.
fn combined_hactool(dir: &Path) -> PathBuf {
    fs::write(
        dir.join("base.cnmt"),
        cnmt(0x0100000011d90000, 0, 0x80, &[(0xaa, 1), (0xcc, 3)]),
    )
    .unwrap();
    fs::write(
        dir.join("patch.cnmt"),
        cnmt(0x0100000011d90800, 0x30000, 0x81, &[(0xbb, 1), (0xdd, 3)]),
    )
    .unwrap();
    let mut nacp = vec![0u8; 0x4000];
    nacp[..7].copy_from_slice(b"Diamond");
    nacp[0x3060..0x3065].copy_from_slice(b"1.3.0");
    fs::write(dir.join("fixture.nacp"), nacp).unwrap();
    let script = format!(
        r#"#!/bin/sh
F="{dir}"
shift 4
for a in "$@"; do last="$a"; done
b=$(basename "$last")
case "$1" in
  -i) case "$b" in
        aaaa*) t=Program; s=0x2000; tid=0100000011d90000;;
        bbbb*) t=Program; s=0x4000; tid=0100000011d90000;;
        cccc*) t=Control; s=0x100; tid=0100000011d90000;;
        dddd*) t=Control; s=0x100; tid=0100000011d90800;;
        eeee*) t=Meta; s=0x80; tid=0100000011d90000;;
        *) t=Meta; s=0x80; tid=0100000011d90800;;
      esac
      printf 'Title ID: %s\nContent Type: %s\nContent Size: %s\n' "$tid" "$t" "$s"; exit 0;;
  -t) for a in "$@"; do case "$a" in --securedir=*) d="${{a#*=}}";; esac; done
      mkdir -p "$d"
      for n in aaaa cccc bbbb dddd; do echo x > "$d/$(printf "$n%.0s" 1 2 3 4 5 6 7 8).nca"; done
      echo x > "$d/$(printf 'eeee%.0s' 1 2 3 4 5 6 7 8).cnmt.nca"
      echo x > "$d/$(printf 'ffff%.0s' 1 2 3 4 5 6 7 8).cnmt.nca"; exit 0;;
esac
for a in "$@"; do
  case "$a" in
    --exefsdir=*) mkdir -p "${{a#*=}}"; echo "$*" > "${{a#*=}}/main"; echo npdm > "${{a#*=}}/main.npdm";;
    --section0dir=*) mkdir -p "${{a#*=}}"
      case "$b" in eeee*) cp "$F/base.cnmt" "${{a#*=}}/x.cnmt";; *) cp "$F/patch.cnmt" "${{a#*=}}/x.cnmt";; esac;;
    --romfsdir=*) d="${{a#*=}}"; mkdir -p "$d"
      case "$b" in
        cccc*|dddd*) cp "$F/fixture.nacp" "$d/control.nacp";;
        *) echo asset > "$d/asset.bin";;
      esac;;
  esac
done
exit 0
"#,
        dir = dir.display()
    );
    let path = dir.join("hactool");
    fs::write(&path, script).unwrap();
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    path
}

#[test]
fn a_combined_xci_applies_the_update_it_proves_by_content_id() {
    let dir = scratch("combined");
    let mut request = request(&dir, false);
    request.hactool = combined_hactool(&dir);
    let mut lines = Vec::new();
    assert_eq!(
        extract(&request, &mut |l| lines.push(l.to_string())).unwrap(),
        Outcome::Extracted
    );
    assert!(
        lines.iter().any(|l| l.contains("base game and its update")),
        "{lines:#?}"
    );
    let arguments = fs::read_to_string(request.work.join("exefs/main")).unwrap();
    let (base, update) = ("a".repeat(32) + ".nca", "b".repeat(32) + ".nca");
    let basenca = arguments.split("--basenca=").nth(1).unwrap();
    assert!(basenca.split_whitespace().next().unwrap().ends_with(&base));
    assert!(arguments.trim_end().ends_with(&update), "{arguments}");
    let record: serde_json::Value =
        serde_json::from_slice(&fs::read(request.work.join("manifest.json")).unwrap()).unwrap();
    assert_eq!(
        (
            record["update_applied"].as_bool(),
            record["title_version"].as_u64()
        ),
        (Some(true), Some(0x30000))
    );
    assert_eq!(record["display_version"], "1.3.0");
}
