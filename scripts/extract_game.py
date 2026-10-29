"""Native, shell-free extraction using shared metadata and content-cache helpers."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

if __package__:
    from . import build_helpers as helpers
    from .container_extract import extract_container
    from .install.filesystem import reject_link
else:
    import build_helpers as helpers
    from container_extract import extract_container
    from install.filesystem import reject_link


class ExtractionTool:
    def __init__(self, executable, keys, commands, home):
        self.executable, self.keys, self.commands = Path(executable), Path(keys), commands
        self.home = Path(home)
        (self.home / ".switch").mkdir(parents=True)
        self.environment = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                                XDG_CONFIG_HOME=str(self.home))

    def run(self, *arguments, discard_output=False):
        try:
            return self.commands.capture(
                [self.executable, "-k", self.keys, "--disablekeywarns", "--suppresskeys", *arguments],
                env=self.environment, cwd=self.home,
                discard_output=discard_output).decode("utf-8", errors="replace")
        except subprocess.CalledProcessError:
            # Neither upstream output nor command arguments are safe error details.
            raise ValueError("Native extraction failed; check the selected dump, update and keys.") from None

    def classify(self, directory):
        result = []
        files = sorted(path for path in Path(directory).iterdir() if path.suffix.lower() == ".nca")
        if not files:
            raise ValueError("The selected container has no NCA files")
        for path in files:
            if not path.is_file() or path.is_symlink():
                raise ValueError("NCA inputs must be regular files")
            try:
                info = helpers.parse_nca_info(self.run("-i", path), str(path))
            except ValueError:
                raise ValueError("NCA metadata is unavailable; check the selected dump and keys.") from None
            if not re.fullmatch(r"[0-9a-f]{16}", info["title_id"]):
                raise ValueError("Invalid NCA title identity")
            result.append(info)
        return result

    def prepare_title_keys(self, selected, title_keys):
        text = Path(title_keys).read_text(encoding="utf-8") if title_keys else None
        keys = {}
        for info, directory in selected:
            rights = info["rights_id"]
            if not rights:
                continue
            if not re.fullmatch(r"[0-9a-f]{32}", rights):
                raise ValueError("Invalid NCA rights identity")
            try:
                keys[rights] = helpers.find_title_key(rights, str(directory), text)[0]
            except KeyError:
                raise ValueError("A required title key is missing from the selected tickets or title.keys.") from None
        path = self.home / ".switch/title.keys"
        path.write_text("".join(rights + " = " + key + "\n" for rights, key in sorted(keys.items())),
                        encoding="ascii")


def pick(rows, content_type, title_id=None):
    path = helpers.pick_nca([helpers.info_row(row) for row in rows], content_type, title_id)
    return next((row for row in rows if row["path"] == path), None)


def related(rows, content_type, title_id):
    path = helpers.pick_related_nca([helpers.info_row(row) for row in rows], content_type, title_id)
    return next((row for row in rows if row["path"] == path), None)


def publish(stage, work):
    """Keep the previous managed extraction intact on any failed publication."""
    names = ("exefs", "romfs", "manifest.json")
    existing = [name for name in names if (work / name).exists()]
    for name in existing:
        reject_link(work / name)
    if existing:
        marker = work / "manifest.json"
        if not marker.is_file():
            raise ValueError("Refusing to replace extracted files without an extraction receipt")
        record = json.loads(marker.read_text(encoding="utf-8"))
        if record.get("schema") != helpers.MANIFEST_SCHEMA or record.get("stage") != "extract":
            raise ValueError("Refusing to replace an unmanaged extraction")
    backup = Path(tempfile.mkdtemp(prefix="extraction-backup-", dir=work))
    moved, installed = [], []
    try:
        for name in existing:
            (work / name).rename(backup / name)
            moved.append(name)
        for name in names:
            (stage / name).rename(work / name)
            installed.append(name)
    except BaseException:
        try:
            for name in reversed(installed):
                (work / name).rename(stage / name)
            for name in reversed(moved):
                (backup / name).rename(work / name)
        except OSError:
            raise OSError("Extraction rollback failed; the prior files remain in " + str(backup)) from None
        backup.rmdir()
        raise
    shutil.rmtree(backup)


def extract_game(base, prod_keys, work, executable, commands, *, update=None,
                 title_keys=None, force=False, progress=None):
    """Read only explicitly selected local inputs; emit stage labels, never tool text."""
    for path in (base, prod_keys, update, title_keys):
        if path:
            reject_link(path)
    base, prod_keys, work = Path(base).resolve(), Path(prod_keys).resolve(), Path(work).resolve()
    update = Path(update).resolve() if update else None
    kind = "nca" if base.is_dir() else base.suffix.lower().lstrip(".")
    if kind not in ("xci", "nsp", "nca") or not base.exists() or not prod_keys.is_file():
        raise ValueError("Choose an XCI, base NSP or NCA directory and an existing prod.keys file")
    if update and (not update.is_file() or update.suffix.lower() != ".nsp"):
        raise ValueError("The selected update must be an NSP file")
    if title_keys and not Path(title_keys).is_file():
        raise ValueError("The selected title.keys file is missing")
    if base.is_symlink():
        raise ValueError("The base input must not be a symbolic link")
    work.mkdir(parents=True, exist_ok=True)
    sizes = (sum(path.stat().st_size for path in base.iterdir() if path.is_file())
             if kind == "nca" else base.stat().st_size, update.stat().st_size if update else 0)
    arguments = dict(base_kind=kind, base_path=str(base), update_path=str(update) if update else None)
    if not force and helpers.manifest_matches(work, *sizes, **arguments):
        return work / "manifest.json"
    if any(base.is_relative_to(work / name) for name in ("exefs", "romfs")):
        raise ValueError("Choose an original input outside the replaceable extracted game directories")
    def report(message):
        if progress:
            progress(message)
    with tempfile.TemporaryDirectory(prefix="extract-", dir=work) as temporary:
        stage = Path(temporary)
        tool = ExtractionTool(executable, prod_keys, commands, stage / "key-home")
        report("Unpacking selected game containers")
        base_dir = base if kind == "nca" else extract_container(base, stage / "base", kind)
        update_dir = extract_container(update, stage / "update", "nsp") if update else None
        report("Identifying Program and Control content")
        base_rows = tool.classify(base_dir)
        base_program = pick(base_rows, "Program")
        if base_program is None:
            raise ValueError("No Program NCA found in the selected base game")
        title_id = base_program["title_id"]
        rows = tool.classify(update_dir) if update else base_rows
        program = pick(rows, "Program", title_id)
        if program is None:
            raise ValueError("No matching Program NCA found in the selected update")
        ctl = related(rows, "Control", title_id)
        meta = related(rows, "Meta", title_id)
        selected = [(base_program, base_dir), (program, update_dir or base_dir)]
        selected += [(row, update_dir or base_dir) for row in (ctl, meta) if row]
        tool.prepare_title_keys(selected, title_keys)
        report("Extracting ExeFS and RomFS" + (" with the selected update" if update else ""))
        tool.run(*(("--basenca=" + base_program["path"],) if update else ()),
                 "--exefsdir=" + str(stage / "exefs"), "--romfsdir=" + str(stage / "romfs"),
                 program["path"], discard_output=True)
        if not (stage / "exefs/main").is_file() or not (stage / "exefs/main").stat().st_size:
            raise ValueError("The native extractor produced no exefs/main")
        if not (stage / "romfs").is_dir() or not helpers.romfs_stats(stage / "romfs")[0]:
            raise ValueError("The native extractor produced an empty RomFS")
        version, display = 0, ""
        if meta:
            tool.run("--section0dir=" + str(stage / "cnmt"), meta["path"], discard_output=True)
            files = sorted((stage / "cnmt").rglob("*.cnmt"))
            if files:
                version = helpers.cnmt_version(files[0].read_bytes())["version"]
        if ctl:
            tool.run("--romfsdir=" + str(stage / "control"), ctl["path"], discard_output=True)
            files = list((stage / "control").rglob("control.nacp"))
            if len(files) == 1:
                display = helpers.nacp_display_version(files[0].read_bytes())
        report("Publishing verified extraction metadata")
        manifest = helpers.build_manifest(stage, title_id, version, display, bool(update), *sizes, **arguments)
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        publish(stage, work)
    return work / "manifest.json"
