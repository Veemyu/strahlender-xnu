#!/usr/bin/env python3
"""Build app icons from user-provided Switch control data; all output stays in work/."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

LANGUAGES = {
    "AmericanEnglish": ("en-US", "English (US)"), "BritishEnglish": ("en-GB", "English (UK)"),
    "Japanese": ("ja", "日本語"), "French": ("fr", "Français"), "German": ("de", "Deutsch"),
    "LatinAmericanSpanish": ("es-419", "Español (Latinoamérica)"), "Spanish": ("es-ES", "Español"),
    "Italian": ("it", "Italiano"), "Dutch": ("nl", "Nederlands"), "CanadianFrench": ("fr-CA", "Français (Canada)"),
    "Portuguese": ("pt-PT", "Português"), "BrazilianPortuguese": ("pt-BR", "Português (Brasil)"),
    "Russian": ("ru", "Русский"), "Korean": ("ko", "한국어"),
    "TraditionalChinese": ("zh-Hant", "繁體中文"), "SimplifiedChinese": ("zh-Hans", "简体中文"),
}


def image_module():
    try:
        from PIL import Image, ImageOps
        return Image, ImageOps
    except ImportError:
        raise ValueError("Pillow is missing: python3 -m pip install Pillow (never installed automatically)") from None


def output_path(path):
    path = Path(path).resolve()
    if not path.is_relative_to((ROOT / "work").resolve()):
        raise ValueError("Icon output must remain under work/")
    return path


def write_json(path, value):
    path = output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def normalize(data):
    Image, ImageOps = image_module()
    with Image.open(io.BytesIO(data)) as image:
        if image.width != image.height or not 16 <= image.width <= 4096:
            raise ValueError("Icon must be square and between 16 and 4096 pixels")
        image = ImageOps.exif_transpose(image).convert("RGB")
        target = io.BytesIO()
        image.save(target, "PNG")
        return target.getvalue()


def default_variant(variants):
    ids = {v["id"] for v in variants}
    return next((x for x in ("en-US", "en-GB", "de") if x in ids), min(ids) if ids else "placeholder")


def recommend(variants, preferred):
    ids = {v["id"] for v in variants}
    for locale in preferred:
        locale = locale.replace("_", "-").split(".")[0]
        exact = next((x for x in ids if x.lower() == locale.lower()), None)
        if exact:
            return exact
        # Preserve Chinese script and Portuguese/Spanish regional distinctions where possible.
        if locale.lower().startswith("zh-"):
            script = "zh-Hant" if any(x.lower() in ("hant", "tw", "hk", "mo") for x in locale.split("-")) else "zh-Hans"
            if script in ids:
                return script
        language = locale.split("-")[0].lower()
        matches = sorted(x for x in ids if x.split("-")[0].lower() == language)
        if matches:
            preferred_id = default_variant([v for v in variants if v["id"] in matches])
            return preferred_id
    return default_variant(variants)


def ingest(base, update, destination, title_id=""):
    destination = output_path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    variants = {}
    for directory in (base, update):
        if not directory:
            continue
        for name, (locale, label) in LANGUAGES.items():
            path = Path(directory) / ("icon_" + name + ".dat")
            if not path.is_file():
                continue
            try:
                data = normalize(path.read_bytes())
            except (OSError, ValueError, SyntaxError) as error:
                print("Notice: invalid icon variant %s (%s)" % (locale, type(error).__name__), file=sys.stderr)
                continue
            digest = hashlib.sha256(data).hexdigest()
            image = digest + ".png"
            (destination / image).write_bytes(data)
            variants[locale] = {"id": locale, "label": label, "image": image,
                                "sha256": digest, "icon": "BDSP_" + digest[:24]}
    entries = sorted(variants.values(), key=lambda v: v["id"])
    manifest = {"schema": 1, "title_id": title_id, "default": default_variant(entries), "variants": entries}
    write_json(destination / "icons.json", manifest)
    print("Original icons: %d language variants" % len(entries))
    return manifest


def title_from_npdm(path):
    data = Path(path).read_bytes()
    if len(data) < 0x80 or data[:4] != b"META":
        raise ValueError("Invalid main.npdm")
    aci = struct.unpack_from("<I", data, 0x70)[0]
    if data[aci:aci + 4] != b"ACI0" or len(data) < aci + 0x18:
        raise ValueError("ACI0 is missing from main.npdm")
    return "%016x" % struct.unpack_from("<Q", data, aci + 0x10)[0]


def pick_control(tsv, title_id):
    matches = []
    for line in Path(tsv).read_text().splitlines():
        fields = line.split("\t")
        if len(fields) >= 7 and fields[2].lower() == "control" and (int(fields[1], 16) & ~0xFFF) == (int(title_id, 16) & ~0xFFF):
            matches.append(fields[0])
    if len(matches) > 1:
        raise ValueError("Multiple matching Control NCAs; title association is ambiguous")
    return matches[0] if matches else ""


def silent_hactool(tool, keys, *args, titlekey=None):
    command = [str(tool), "-k", str(keys)]
    if titlekey:
        command.append("--titlekey=" + titlekey)
    result = subprocess.run(command + list(map(str, args)), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return result.returncode, result.stdout.decode("utf-8", errors="replace")


def extract(args):
    """Read only explicitly selected containers/NCA directories; never expose hactool output."""
    import build_helpers as helpers
    if not args.prod_keys or not Path(args.prod_keys).is_file():
        raise ValueError("Provide --prod-keys as a local file path, never key values")
    title_id = args.title_id or (title_from_npdm(args.npdm) if Path(args.npdm).is_file() else None)
    output = output_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="icon-extract-", dir=output.parent) as temporary:
        temporary = Path(temporary)
        groups = []
        for index, (container, kind, directory) in enumerate(((args.xci or args.nsp, "xci" if args.xci else "pfs0", args.base_dir),
                                                            (args.update_nsp, "pfs0", args.update_dir))):
            if container:
                directory = temporary / ("nca-" + str(index))
                flag = "--securedir=" if kind == "xci" else "--pfs0dir="
                rc, _ = silent_hactool(args.hactool, args.prod_keys, "-t", kind, flag + str(directory), container)
                if rc:
                    raise ValueError("Could not unpack the supplied container for icon extraction")
            if not directory or not Path(directory).is_dir():
                groups.append(None)
                continue
            infos = []
            for path in sorted(Path(directory).glob("*.nca")):
                rc, text = silent_hactool(args.hactool, args.prod_keys, "-i", path)
                if rc:
                    continue
                try:
                    info = helpers.parse_nca_info(text, str(path))
                except ValueError:
                    continue
                infos.append(info)
            if title_id is None:
                families = {int(info["title_id"], 16) & ~0xFFF for info in infos
                            if info["content_type"].lower() == "program"}
                if index != 0 or len(families) != 1:
                    raise ValueError("Cannot identify one base application; provide --title-id")
                title_id = "%016X" % families.pop()
            candidates = [info for info in infos if info["content_type"].lower() == "control"
                          and (int(info["title_id"], 16) & ~0xFFF) == (int(title_id, 16) & ~0xFFF)]
            if not candidates:
                groups.append(None)
                continue
            # Multiple matching Control NCAs are ambiguous; do not pick another title/version by size.
            if len(candidates) != 1:
                raise ValueError("Multiple matching Control NCAs; provide a distinct base/update directory")
            info = candidates[0]
            titlekey = None
            if info["rights_id"]:
                try:
                    text = Path(args.title_keys).read_text() if args.title_keys else None
                    titlekey, _ = helpers.find_title_key(info["rights_id"], str(directory), text)
                except KeyError:
                    raise ValueError("Title key for the Control NCA is missing") from None
            control = temporary / ("control-" + str(index))
            rc, _ = silent_hactool(args.hactool, args.prod_keys, "--romfsdir=" + str(control), info["path"], titlekey=titlekey)
            if rc:
                raise ValueError("Could not decrypt the Control NCA")
            groups.append(control)
        if title_id is None:
            raise ValueError("No base application found; provide a base NSP/XCI or --title-id")
        return ingest(groups[0], groups[1], output, title_id)


def load_source(source):
    source = Path(source)
    try:
        data = json.loads((source / "icons.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": 1, "default": "placeholder", "variants": []}
    if data.get("schema") != 1:
        raise ValueError("Unknown icon metadata")
    valid = []
    for entry in data.get("variants", []):
        path = source / entry["image"]
        if path.parent.resolve() != source.resolve():
            raise ValueError("Invalid icon file path")
        try:
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                raise ValueError("Checksum")
            normalize(content)
        except (OSError, ValueError, SyntaxError):
            print("Notice: damaged icon variant %s skipped" % entry["id"], file=sys.stderr)
            continue
        valid.append(entry)
    data["variants"] = valid
    data["default"] = default_variant(valid)
    return data


def resized(data, size):
    Image, _ = image_module()
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)


def prepared(source, output):
    output = output_path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = load_source(source)
    if not manifest["variants"]:
        print("Notice: no original icon available; using a neutral placeholder (run game_icons.py extract to extract it)", file=sys.stderr)
        from make_icon import png, pixel
        data = png(256, pixel)
        digest = hashlib.sha256(data).hexdigest()
        manifest["variants"] = [{"id": "placeholder", "label": "Placeholder", "image": digest + ".png",
                                  "sha256": digest, "icon": "BDSP_" + digest[:24]}]
        (output / (digest + ".png")).write_bytes(data)
    for entry in manifest["variants"]:
        if entry["id"] != "placeholder":
            shutil.copyfile(Path(source) / entry["image"], output / entry["image"])
    write_json(output / "icons.json", manifest)
    return manifest


def build_mac(source, output):
    image_module()
    from icon_composer import write_documents, compile_icons, STYLE
    output = output_path(output)
    manifest = prepared(source, output / "AppIcons")
    scratch = output_path(ROOT / "work/recomp/icons/native-build")
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mac-", dir=scratch) as temporary:
        temporary = Path(temporary)
        documents = write_documents(manifest, output / "AppIcons", temporary / "sources")
        primary = next(v["icon"] for v in manifest["variants"] if v["id"] == manifest["default"])
        compiled = {}
        for name, document_path in documents.items():
            destination = temporary / name
            partial = compile_icons({name: document_path}, name, destination, "macosx")
            filename = name + ".icns"
            shutil.copyfile(destination / filename, output / "AppIcons" / filename)
            compiled[name] = filename
            if name == primary:
                shutil.copyfile(destination / filename, output / "BDSP.icns")
                shutil.copyfile(destination / "Assets.car", output / "Assets.car")
                partial["CFBundleIconFile"] = "BDSP"
                info_path = output.parent / "Info.plist"
                if info_path.is_file():
                    info = plistlib.loads(info_path.read_bytes())
                    info.update(partial)
                    info_path.write_bytes(plistlib.dumps(info))
        for variant in manifest["variants"]:
            variant["mac_image"] = compiled[variant["icon"]]
    manifest["mac_style"] = STYLE
    manifest["primary_icon"] = primary
    write_json(output / "AppIcons/icons.json", manifest)


def build_linux(source, output, executable):
    output = output_path(output)
    manifest = prepared(source, output)
    for entry in manifest["variants"]:
        data = (output / entry["image"]).read_bytes()
        for size in (16, 32, 48, 64, 128, 256, 512):
            path = output / "hicolor" / ("%dx%d" % (size, size)) / "apps"
            path.mkdir(parents=True, exist_ok=True)
            resized(data, size).save(path / (entry["icon"] + ".png"))
    default = next(v for v in manifest["variants"] if v["id"] == manifest["default"])
    executable = str(Path(executable).resolve())
    if any(c in executable for c in '\n\r%'):
        raise ValueError("Invalid desktop launcher path")
    quoted = executable.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    desktop = "[Desktop Entry]\nType=Application\nName=BDSP\nExec=\"%s\"\nIcon=%s\nTerminal=false\nCategories=Game;\nStartupWMClass=dev.local.xnubdsp\n" % (quoted, output / default["image"])
    (output / "dev.local.xnubdsp.desktop").write_text(desktop, encoding="utf-8")


def build_ios(source, output, bundle, settings):
    image_module()
    from icon_composer import write_documents, compile_icons, STYLE
    output = output_path(output)
    bundle = output_path(bundle)
    manifest = prepared(source, bundle / "AppIcons")
    documents = write_documents(manifest, bundle / "AppIcons", output / "Documents")
    primary = next(v["icon"] for v in manifest["variants"] if v["id"] == manifest["default"])
    partial_info = compile_icons(documents, primary, output / "Compiled", "iphoneos")
    for file in (output / "Compiled").iterdir():
        if file.suffix in (".car", ".png"):
            shutil.copyfile(file, bundle / file.name)
    manifest["ios_style"] = STYLE
    info_path = bundle / "Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    for key in ("CFBundleIcons", "CFBundleIcons~ipad"):
        info.pop(key, None)
    info.update(partial_info)
    # AppIcons retains the variant names; nil always means the compiled primary icon.
    manifest["primary_icon"] = primary
    write_json(bundle / "AppIcons/icons.json", manifest)
    info_path.write_bytes(plistlib.dumps(info))
    settings_out = bundle / "Settings.bundle"
    shutil.copytree(settings, settings_out, dirs_exist_ok=True)
    root = plistlib.loads((settings_out / "Root.plist").read_bytes())
    root["PreferenceSpecifiers"] = [v for v in root["PreferenceSpecifiers"] if v.get("Key") != "bdsp_app_icon" and v.get("Title") != "ICON_GROUP"]
    root["PreferenceSpecifiers"] += [
        {"Type": "PSGroupSpecifier", "Title": "ICON_GROUP", "FooterText": "ICON_FOOTER"},
        {"Type": "PSMultiValueSpecifier", "Title": "ICON_TITLE", "Key": "bdsp_app_icon", "DefaultValue": "default",
         "Titles": ["ICON_DEFAULT"] + ["ICON_VARIANT_" + v["id"] for v in manifest["variants"]],
         "Values": ["default"] + [v["id"] for v in manifest["variants"]]},
    ]
    (settings_out / "Root.plist").write_bytes(plistlib.dumps(root))
    # Different help text by system language, generated alongside the copied settings.
    texts = (
        ("de", "App-Symbol", "Variante", "Standard (Englisch)", "Verfügbare Originalvarianten aus deinem Dump; die passende Systemsprache ist empfohlen. Die Auswahl gilt beim nächsten Aktivieren; iPadOS zeigt beim Wechsel einen Hinweis. Entfällt eine Variante, gilt wieder der Standard. Die Spielsprache bleibt unverändert."),
        ("en", "App icon", "Variant", "Default (English)", "Original variants from your dump; your system language is recommended. Applied when the app becomes active; iPadOS may display a change notice. Unavailable selections revert to the default. Game language is unchanged."),
    )
    translations = {row[0]: row[1:] for row in texts}
    for locale in sorted({"de", "en"} | {v["id"] for v in manifest["variants"] if v["id"] != "placeholder"}):
        group, title, default, footer = translations.get(locale, translations["en"])
        if not manifest["default"].startswith("en-"):
            default_name = next(v["label"] for v in manifest["variants"] if v["id"] == manifest["default"])
            default = ("Standard" if locale == "de" else "Default") + " (" + default_name + ")"
        recommended = recommend(manifest["variants"], [locale])
        path = settings_out / (locale + ".lproj") / "Root.strings"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            for key, text in (("ICON_GROUP", group), ("ICON_TITLE", title), ("ICON_DEFAULT", default), ("ICON_FOOTER", footer)):
                file.write("\n%s = %s;\n" % (json.dumps(key), json.dumps(text, ensure_ascii=False)))
            for variant in manifest["variants"]:
                label = variant["label"]
                if variant["id"] == recommended:
                    label += " (empfohlen)" if locale == "de" else " (recommended)"
                file.write("\n%s = %s;\n" % (json.dumps("ICON_VARIANT_" + variant["id"]), json.dumps(label, ensure_ascii=False)))


def sign_ios(bundle):
    bundle = output_path(bundle)
    temporary_root = output_path(ROOT / "work/ios/icon-signing")
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
        prefix = str(Path(directory) / "certificate")
        result = subprocess.run(["codesign", "-d", "--extract-certificates=" + prefix, str(bundle)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if result.returncode or not Path(prefix + "0").is_file():
            raise ValueError("Could not read the Xcode build signing certificate")
        identity = hashlib.sha1(Path(prefix + "0").read_bytes()).hexdigest()
        result = subprocess.run(["codesign", "--force", "--sign", identity, "--timestamp=none",
                                 "--preserve-metadata=entitlements,requirements,flags,runtime", "--generate-entitlement-der", str(bundle)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if result.returncode:
            raise ValueError("Final signing failed; check the Xcode build signing configuration")
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)
    print("App bundle, including icons, signed and verified.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    ingest_parser = sub.add_parser("ingest")
    ingest_parser.add_argument("--base-control")
    ingest_parser.add_argument("--update-control")
    ingest_parser.add_argument("--title-id", default="")
    ingest_parser.add_argument("--output", default="work/recomp/icons/source")
    extraction = sub.add_parser("extract")
    containers = extraction.add_mutually_exclusive_group()
    containers.add_argument("--xci")
    containers.add_argument("--nsp")
    extraction.add_argument("--update-nsp")
    extraction.add_argument("--base-dir", default="work/base")
    extraction.add_argument("--update-dir", default="work/update")
    extraction.add_argument("--prod-keys", default=os.environ.get("BDSP_PROD_KEYS"))
    extraction.add_argument("--title-keys")
    extraction.add_argument("--title-id")
    extraction.add_argument("--npdm", default="work/exefs/main.npdm")
    extraction.add_argument("--hactool", default="tools/hactool/hactool")
    extraction.add_argument("--output", default="work/recomp/icons/source")
    for name in ("mac", "ios", "linux"):
        p = sub.add_parser(name)
        p.add_argument("--source", default="work/recomp/icons/source")
        p.add_argument("--output", required=True)
        if name == "ios":
            p.add_argument("--bundle", required=True)
            p.add_argument("--settings", default="scripts/recomp/ios/app/Settings.bundle")
        if name == "linux":
            p.add_argument("--executable", default="work/recomp/bdsp_boot_vk_qt")
    signing = sub.add_parser("sign-ios")
    signing.add_argument("--bundle", required=True)
    picking = sub.add_parser("pick-control")
    picking.add_argument("--tsv", required=True)
    picking.add_argument("--title-id", required=True)
    previewing = sub.add_parser("preview")
    previewing.add_argument("--source", default="work/recomp/icons/source")
    previewing.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "extract":
            extract(args)
        elif args.command == "ingest":
            ingest(args.base_control, args.update_control, args.output, args.title_id)
        elif args.command == "mac":
            build_mac(args.source, args.output)
        elif args.command == "ios":
            build_ios(args.source, args.output, args.bundle, args.settings)
        elif args.command == "sign-ios":
            sign_ios(args.bundle)
        elif args.command == "pick-control":
            print(pick_control(args.tsv, args.title_id))
        elif args.command == "preview":
            image_module()
            from icon_artwork import preview
            manifest = load_source(args.source)
            entry = next(v for v in manifest["variants"] if v["id"] == manifest["default"])
            output = output_path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            preview((Path(args.source) / entry["image"]).read_bytes(), output)
        else:
            build_linux(args.source, args.output, args.executable)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
