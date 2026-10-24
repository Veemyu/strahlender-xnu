#!/usr/bin/env python3
"""Build app icons from user-provided Switch control data; all output stays in work/."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import re
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

# NACP slot order is a binary-format contract, not LANGUAGES' display order.
NACP_LANGUAGES = ("en-US", "en-GB", "ja", "fr", "de", "es-419", "es-ES", "it",
                  "nl", "fr-CA", "pt-PT", "ru", "ko", "zh-Hant", "zh-Hans", "pt-BR")


def read_nacp(directory):
    directory = Path(directory)
    path = (next((entry for entry in directory.iterdir()
                  if entry.name.lower() == "control.nacp" and entry.is_file() and not entry.is_symlink()), None)
            if directory.is_dir() else None)
    if path is None:
        return {}, ""
    with path.open("rb") as file:
        data = file.read(0x4001)
    if len(data) != 0x4000:
        raise ValueError("Invalid control.nacp size")
    def string(start, size):
        return data[start:start + size].split(b"\0", 1)[0].decode("utf-8").strip()
    titles = {}
    for index, locale in enumerate(NACP_LANGUAGES):
        name = string(index * 0x300, 0x200)
        if name:
            titles[locale] = {"name": name, "publisher": string(index * 0x300 + 0x200, 0x100)}
    return titles, string(0x3060, 0x10)


def write_bundle_names(manifest, resources):
    """Write every original title. Host/installer locale never filters the bundle."""
    titles = dict(manifest.get("titles", {}))
    for locale in titles:
        if locale not in NACP_LANGUAGES:
            raise ValueError("Unknown title locale")
    # Existing runtime catalogs include generic language lproj directories. Give
    # those a stable display-name fallback as well, keeping every regional original.
    for language, preferred in (("en", "en-US"), ("es", "es-ES"), ("pt", "pt-PT"), ("zh", "zh-Hans")):
        available = [{"id": locale} for locale in titles if locale.split("-")[0] == language]
        if available:
            titles[language] = titles[recommend(available, [preferred])]
    for locale, title in titles.items():
        path = output_path(Path(resources) / (locale + ".lproj") / "InfoPlist.strings")
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        existing = re.sub(r'(?m)^[ \t]*"CFBundleDisplayName"[ \t]*=[ \t]*"(?:\\.|[^"\\])*";[ \t]*$', '', existing)
        # CFBundleName stays stable for executable/build identity. Display name is localized.
        path.write_text(existing.rstrip() + '\n"CFBundleDisplayName" = ' + json.dumps(title["name"], ensure_ascii=False) + ';\n',
                        encoding="utf-8")


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


def mod_logo_bundles(romfs, title_id=""):
    """Only inspect the game's known title-logo bundles, never the whole RomFS."""
    movie = Path(romfs) / "Data/StreamingAssets/AssetAssistant/Dpr/movie"
    game = "pea" if str(title_id).lower() == "010018e011d92000" else "dia"
    directory = movie / game / "logo"
    if not directory.is_dir() or directory.is_symlink():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file() and not path.is_symlink()
                  and re.fullmatch(r"logo_" + game + r"_(en|fr|ge|it|jp|ko|si|sp|tr)", path.name))


def square_mod_logo(artwork):
    Image, ImageOps = image_module()
    artwork = artwork.convert("RGBA")
    bounds = artwork.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("Mod logo has no visible artwork")
    artwork = ImageOps.contain(artwork.crop(bounds), (896, 896), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (1024, 1024), (20, 23, 28, 255))
    canvas.alpha_composite(artwork, ((1024 - artwork.width) // 2, (1024 - artwork.height) // 2))
    stream = io.BytesIO()
    canvas.convert("RGB").save(stream, "PNG")
    return stream.getvalue()


def unity_module():
    if os.environ.get("BDSP_INSTALLER_PRIVATE_RUNTIME") != "1":
        sys.path.insert(0, str(ROOT / "tools/pydeps"))
    try:
        import UnityPy
    except ImportError as error:
        raise ValueError("Mod logos need the existing UnityPy shader profile in the build runtime; prepare it before packaging.") from error
    return UnityPy


def check_mod_artwork(mod_root):
    root = Path(mod_root)
    romfs = next((path for path in root.iterdir() if path.is_dir() and path.name.lower() == "romfs"), root / "romfs")
    if any((directory / ("icon" + extension)).is_file() for directory in (root, root / "control", romfs, romfs / "control")
           for extension in (".png", ".jpg", ".jpeg", ".webp")):
        return
    if mod_logo_bundles(romfs) or mod_logo_bundles(romfs, "010018e011d92000"):
        unity_module()
        print("Mod title-logo reader available (existing UnityPy profile).")


def extract_mod_logos(romfs, title_id=""):
    bundles = mod_logo_bundles(romfs, title_id)
    if not bundles:
        return {}, {}
    UnityPy = unity_module()
    locales = {"en": ("en-US", "en-GB"), "fr": ("fr", "fr-CA"), "ge": ("de",), "it": ("it",),
               "jp": ("ja",), "ko": ("ko",), "si": ("zh-Hans",), "sp": ("es-ES", "es-419"), "tr": ("zh-Hant",)}
    result, provenance = {}, {}
    for path in bundles:
        try:
            if path.stat().st_size > 64 * 1024 * 1024:
                raise ValueError("Mod logo bundle exceeds 64 MiB")
            environment = UnityPy.load(str(path))
            textures = [obj.read() for obj in environment.objects if obj.type.name == "Texture2D"]
            matches = [texture for texture in textures if texture.m_Name == path.name]
            if len(matches) != 1:
                raise ValueError("No unique matching logo texture")
            if any(not 16 <= getattr(matches[0], field, 16) <= 4096 for field in ("m_Width", "m_Height")):
                raise ValueError("Mod logo texture dimensions exceed the supported range")
            data = square_mod_logo(matches[0].image)
        except (OSError, ValueError, RuntimeError, EOFError, struct.error, IndexError, KeyError) as error:
            print("Notice: mod logo %s skipped (%s)" % (path.name, type(error).__name__), file=sys.stderr)
            continue
        for locale in locales[path.name.rsplit("_", 1)[1]]:
            result[locale] = data
            provenance[locale] = {"bundle": str(path.relative_to(romfs)), "texture": matches[0].m_Name,
                                  "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    print("Mod artwork: %d language variants extracted from RomFS title-logo bundles" % len(result))
    return result, provenance


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
    titles = {}
    version = ""
    for directory in (base, update):
        if not directory:
            continue
        localized_titles, display_version = read_nacp(directory)
        titles.update(localized_titles)
        version = display_version or version
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
    manifest = {"schema": 1, "title_id": title_id, "default": default_variant(entries), "variants": entries,
                "titles": titles, "display_version": version}
    write_json(destination / "icons.json", manifest)
    print("Original icons: %d language variants" % len(entries))
    return manifest


def overlay_mod(source, mod_root, destination, mod_name):
    """Keep every base language variant, replacing only icons supplied by a mod."""
    source, mod_root, destination = Path(source), Path(mod_root), output_path(destination)
    if not mod_root.is_dir():
        raise ValueError("The selected mod folder is missing")
    manifest = load_source(source)
    destination.mkdir(parents=True, exist_ok=True)
    for variant in manifest.get("variants", []):
        filename = variant["image"]
        if Path(filename).name != filename:
            raise ValueError("Invalid base icon path")
        shutil.copy2(source / filename, destination / filename)
    # A separate mod app keeps the mod's name in every locale unless its control
    # metadata supplies a translated title for that language.
    manifest["titles"] = {locale: {"name": mod_name, "publisher": ""} for locale in NACP_LANGUAGES}
    found = {}
    generic = None
    control = None
    def child(directory, name):
        if not directory.is_dir():
            return directory / name
        return next((path for path in directory.iterdir()
                     if path.name.lower() == name and path.is_dir() and not path.is_symlink()), directory / name)
    romfs = child(mod_root, "romfs")
    candidates = [mod_root, child(mod_root, "control"), romfs, child(romfs, "control")]
    for directory in candidates:
        if not directory.is_dir() or directory.is_symlink():
            continue
        for item in sorted(directory.iterdir()):
            if not item.is_file() or item.is_symlink():
                continue
            lower = item.name.lower()
            if lower == "control.nacp":
                control = item
            elif lower in ("icon.png", "icon.jpg", "icon.jpeg", "icon.webp"):
                generic = item
            elif lower.startswith("icon_") and item.suffix.lower() in (".dat", ".png", ".jpg", ".jpeg", ".webp"):
                label = item.stem[5:]
                locale = next((code for name, (code, _) in LANGUAGES.items() if name.lower() == label.lower()), None)
                if locale is None:
                    locale = next((code for code in NACP_LANGUAGES if code.lower() == label.lower()), None)
                if locale:
                    found[locale] = item
    if control:
        titles, version = read_nacp(control.parent)
        manifest["titles"].update(titles)
        manifest["display_version"] = version or manifest.get("display_version", "")
    variants = {entry["id"]: entry for entry in manifest.get("variants", [])}
    supplied_icons = set()
    if generic:
        for locale in NACP_LANGUAGES:
            found.setdefault(locale, generic)
    embedded, provenance = extract_mod_logos(romfs, manifest.get("title_id", "")) if len(found) < len(NACP_LANGUAGES) else ({}, {})
    if embedded:
        default = embedded.get("en-US") or embedded[sorted(embedded)[0]]
        for locale in NACP_LANGUAGES:
            data = embedded.get(locale, default)
            digest = hashlib.sha256(data).hexdigest()
            image = digest + ".png"
            (destination / image).write_bytes(data)
            label = next(label for code, label in LANGUAGES.values() if code == locale)
            variants[locale] = {"id": locale, "label": label, "image": image,
                                "sha256": digest, "icon": "BDSP_" + digest[:24]}
            supplied_icons.add(locale)
        manifest["mod_artwork"] = provenance
    for locale, path in found.items():
        try:
            data = normalize(path.read_bytes())
        except (OSError, ValueError, SyntaxError) as error:
            print("Notice: invalid mod icon %s (%s)" % (path.name, type(error).__name__), file=sys.stderr)
            continue
        digest = hashlib.sha256(data).hexdigest()
        image = digest + ".png"
        (destination / image).write_bytes(data)
        label = LANGUAGES[next((name for name, (code, _) in LANGUAGES.items() if code == locale))][1]
        variants[locale] = {"id": locale, "label": label, "image": image,
                            "sha256": digest, "icon": "BDSP_" + digest[:24]}
        supplied_icons.add(locale)
    # A mod without its own artwork must remain distinguishable beside vanilla.
    for locale, variant in variants.items():
        if locale in supplied_icons:
            continue
        data = mod_fallback_icon((destination / variant["image"]).read_bytes())
        digest = hashlib.sha256(data).hexdigest()
        image = digest + ".png"
        (destination / image).write_bytes(data)
        variant.update(image=image, sha256=digest, icon="BDSP_" + digest[:24])
    manifest["mod_icon_fallback"] = any(locale not in supplied_icons for locale in variants)
    manifest["variants"] = sorted(variants.values(), key=lambda entry: entry["id"])
    manifest["default"] = default_variant(manifest["variants"])
    write_json(destination / "icons.json", manifest)
    print("Mod icons: %d supplied variants, %d base variants marked MOD" %
          (len(supplied_icons), len(variants) - len(supplied_icons)))
    return manifest


def mod_fallback_icon(data):
    """Badge original artwork without a host font or a network asset."""
    Image = image_module()[0]
    from PIL import ImageDraw, ImageFont
    image = Image.open(io.BytesIO(data)).convert("RGB").resize((512, 512), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((284, 360, 480, 456), radius=24, fill=(24, 24, 24), outline=(240, 240, 240), width=3)
    font = ImageFont.load_default(size=48)
    draw.text((382, 408), "MOD", font=font, fill=(255, 255, 255), anchor="mm")
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


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


def prepared(source, output, mod_root=None, mod_name=None):
    output = output_path(output)
    output.mkdir(parents=True, exist_ok=True)
    if mod_root:
        with tempfile.TemporaryDirectory(prefix="mod-override-", dir=output.parent) as temporary:
            overlay_mod(source, mod_root, temporary, mod_name or Path(mod_root).name)
            return prepared(temporary, output)
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


def build_mac(source, output, mod_root=None, mod_name=None):
    image_module()
    from icon_composer import write_documents, compile_icons, STYLE
    output = output_path(output)
    manifest = prepared(source, output / "AppIcons", mod_root, mod_name)
    write_bundle_names(manifest, output)
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


def build_linux(source, output, executable, mod_root=None, mod_name=None):
    output = output_path(output)
    manifest = prepared(source, output, mod_root, mod_name)
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


def build_ios(source, output, bundle, settings, mod_root=None, mod_name=None):
    image_module()
    from icon_composer import write_documents, compile_icons, STYLE
    output = output_path(output)
    bundle = output_path(bundle)
    manifest = prepared(source, bundle / "AppIcons", mod_root, mod_name)
    write_bundle_names(manifest, bundle)
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
        ("es", "Icono de la app", "Variante", "Predeterminado (inglés)", "Variantes originales de tu volcado; se recomienda la del idioma del sistema. Se aplica al activar la app; iPadOS puede mostrar un aviso del cambio. Si una variante deja de estar disponible, se usa la predeterminada. El idioma del juego no cambia."),
        ("pt", "Ícone do app", "Variante", "Padrão (inglês)", "Variantes originais do seu dump; recomenda-se a do idioma do sistema. Vale ao ativar o app; o iPadOS pode mostrar um aviso da mudança. Se uma variante deixar de existir, volta o padrão. O idioma do jogo não muda."),
    )
    default_word = {"de": "Standard", "es": "Predeterminado", "pt": "Padrão"}
    recommended_word = {"de": " (empfohlen)", "es": " (recomendado)", "pt": " (recomendado)"}
    translations = {row[0]: row[1:] for row in texts}
    for locale in sorted({"de", "en", "es", "pt"} | {v["id"] for v in manifest["variants"] if v["id"] != "placeholder"}):
        lang = locale.split("-")[0]   # pt-BR -> pt, es-419 -> es; English variants -> en
        group, title, default, footer = translations.get(lang, translations["en"])
        if not manifest["default"].startswith("en-"):
            default_name = next(v["label"] for v in manifest["variants"] if v["id"] == manifest["default"])
            default = default_word.get(lang, "Default") + " (" + default_name + ")"
        recommended = recommend(manifest["variants"], [locale])
        path = settings_out / (locale + ".lproj") / "Root.strings"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            for key, text in (("ICON_GROUP", group), ("ICON_TITLE", title), ("ICON_DEFAULT", default), ("ICON_FOOTER", footer)):
                file.write("\n%s = %s;\n" % (json.dumps(key), json.dumps(text, ensure_ascii=False)))
            for variant in manifest["variants"]:
                label = variant["label"]
                if variant["id"] == recommended:
                    label += recommended_word.get(lang, " (recommended)")
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
    mod_icons = sub.add_parser("overlay-mod")
    mod_icons.add_argument("--source", required=True)
    mod_icons.add_argument("--mod-root", required=True)
    mod_icons.add_argument("--mod-name", required=True)
    mod_icons.add_argument("--output", required=True)
    mod_check = sub.add_parser("check-mod-artwork")
    mod_check.add_argument("--mod-root", required=True)
    for name in ("mac", "ios", "linux"):
        p = sub.add_parser(name)
        p.add_argument("--source", default="work/recomp/icons/source")
        p.add_argument("--output", required=True)
        p.add_argument("--mod-root")
        p.add_argument("--mod-name")
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
        elif args.command == "overlay-mod":
            overlay_mod(args.source, args.mod_root, args.output, args.mod_name)
        elif args.command == "check-mod-artwork":
            check_mod_artwork(args.mod_root)
        elif args.command == "mac":
            build_mac(args.source, args.output, args.mod_root, args.mod_name)
        elif args.command == "ios":
            build_ios(args.source, args.output, args.bundle, args.settings, args.mod_root, args.mod_name)
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
            build_linux(args.source, args.output, args.executable, args.mod_root, args.mod_name)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
