"""Bounded PFS0/HFS0 container copying shared by native extraction front ends."""
import hashlib
from pathlib import Path
import re
import shutil
import struct
import tempfile


def container_entries(stream, offset=0, size=None, expected_magic=None):
    """Return validated flat entries relative to one bounded container."""
    stream.seek(0, 2)
    total = stream.tell()
    size = total - offset if size is None else size
    if offset < 0 or size < 16 or offset > total - size:
        raise ValueError("Container range is outside the input")
    stream.seek(offset)
    magic, count, string_size, reserved = struct.unpack("<4sIII", stream.read(16))
    if (magic not in (b"PFS0", b"HFS0") or (expected_magic and magic != expected_magic)
            or reserved or count > 100000):
        raise ValueError("Invalid container header")
    width = 24 if magic == b"PFS0" else 64
    header_size = 16 + count * width + string_size
    if string_size > 16 * 1024 * 1024 or header_size > size:
        raise ValueError("Container header exceeds its bounds")
    table = stream.read(count * width)
    strings = stream.read(string_size)
    entries, seen, ranges = [], set(), []
    for index in range(count):
        record = table[index * width:(index + 1) * width]
        start, length, name_offset, hashed_size = struct.unpack_from("<QQII", record)
        if name_offset >= len(strings):
            raise ValueError("Container name offset is outside its table")
        end = strings.find(b"\0", name_offset)
        if end < 0:
            raise ValueError("Unterminated container filename")
        name = strings[name_offset:end].decode("utf-8")
        if (not name or name in (".", "..") or len(name.encode("utf-8")) > 240 or
                re.search(r'[\\/:<>"|?*\x00-\x1f]', name) or name.endswith((".", " ")) or
                name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL",
                                              *(f"COM{i}" for i in range(1, 10)),
                                              *(f"LPT{i}" for i in range(1, 10))} or
                name.casefold() in seen):
            raise ValueError("Unsafe or duplicate container filename")
        seen.add(name.casefold())
        if start > size - header_size or length > size - header_size - start:
            raise ValueError("Container file exceeds its bounds")
        if magic == b"PFS0" and hashed_size:
            raise ValueError("Invalid PFS0 reserved field")
        digest = record[32:64] if magic == b"HFS0" else None
        if magic == b"HFS0" and struct.unpack_from("<Q", record, 24)[0]:
            raise ValueError("Invalid HFS0 reserved field")
        if hashed_size > length:
            raise ValueError("HFS0 hash region exceeds file bounds")
        absolute = offset + header_size + start
        entries.append({"name": name, "offset": absolute, "size": length,
                        "hash_size": hashed_size, "sha256": digest})
        if length:
            ranges.append((start, start + length))
    ranges.sort()
    if any(first[1] > second[0] for first, second in zip(ranges, ranges[1:])):
        raise ValueError("Container files overlap")
    return entries


def verify_hash(stream, offset, length, expected, *, compatibility_suffix=False):
    stream.seek(offset)
    digest = hashlib.sha256()
    while length:
        chunk = stream.read(min(1024 * 1024, length))
        if not chunk:
            raise ValueError("Truncated HFS0 hash region")
        digest.update(chunk)
        length -= len(chunk)
    if digest.digest() != expected:
        if compatibility_suffix:
            digest.update(b"\x01")
        if not compatibility_suffix or digest.digest() != expected:
            raise ValueError("HFS0 content hash mismatch")


def extract_container(source, destination, kind):
    """Publish a new directory only after every bounded copy/hash succeeds."""
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError("Refusing to replace an existing extracted container")
    with source.open("rb") as stream:
        if kind == "xci":
            stream.seek(0x100)
            if stream.read(4) != b"HEAD":
                raise ValueError("Invalid XCI header")
            stream.seek(0x130)
            raw = stream.read(16)
            if len(raw) != 16:
                raise ValueError("Truncated XCI header")
            root_offset, root_header_size = struct.unpack("<QQ", raw)
            expected_hash = stream.read(32)
            entries = container_entries(stream, root_offset, expected_magic=b"HFS0")
            stream.seek(root_offset + 4)
            count, strings = struct.unpack("<II", stream.read(8))
            if root_header_size != 16 + 64 * count + strings:
                raise ValueError("Invalid XCI root header size")
            verify_hash(stream, root_offset, root_header_size, expected_hash, compatibility_suffix=True)
            secure = [entry for entry in entries if entry["name"] == "secure"]
            if len(secure) != 1:
                raise ValueError("XCI secure partition is missing")
            verify_hash(stream, secure[0]["offset"], secure[0]["hash_size"], secure[0]["sha256"])
            entries = container_entries(stream, secure[0]["offset"], secure[0]["size"], b"HFS0")
        elif kind == "nsp":
            entries = container_entries(stream, expected_magic=b"PFS0")
        else:
            raise ValueError("Expected an XCI or NSP container")
        destination.parent.mkdir(parents=True, exist_ok=True)
        required = sum(entry["size"] for entry in entries)
        if shutil.disk_usage(destination.parent).free < required:
            raise ValueError("Not enough disk space for container extraction")
        with tempfile.TemporaryDirectory(prefix="container-", dir=destination.parent) as temporary:
            stage = Path(temporary) / "files"
            stage.mkdir()
            for entry in entries:
                if entry["sha256"] is not None:
                    verify_hash(stream, entry["offset"], entry["hash_size"], entry["sha256"])
                stream.seek(entry["offset"])
                remaining = entry["size"]
                with (stage / entry["name"]).open("xb") as output:
                    while remaining:
                        chunk = stream.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError("Container changed or truncated during extraction")
                        output.write(chunk)
                        remaining -= len(chunk)
            stage.rename(destination)
    return destination
