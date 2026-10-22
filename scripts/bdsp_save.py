#!/usr/bin/env python3
"""Validator/parser for BDSP SaveData.bin (and Backup.bin, same format).

Standard library only. Structure as in docs/saves.md (own Ghidra analysis).
Usage:
    python3 scripts/bdsp_save.py check <file> [--fields]
    python3 scripts/bdsp_save.py dump-fields
    python3 scripts/bdsp_save.py fix-hash <input> <output>
The input file is never modified.
"""
import argparse
import hashlib
import os
import struct
import sys

HASH_OFFSET = 0xE9818
HASH_LEN = 16
HASH_END = HASH_OFFSET + HASH_LEN  # 0xE9828: smallest buffer size the game accepts

CURRENT_VERSION = 0x34
LAUNCH_VERSION = 0x25  # from this version on the game checks the hash

# Hash/file length per version 0x25 … 0x34 (BINARY_SIZE, spec section 3)
BINARY_SIZE = (
    0xE9828,  # 0x25
    0xE9BE8,  # 0x26
    0xED158,  # 0x27
    0xED188,  # 0x28
    0xED188,  # 0x29
    0xED680,  # 0x2A
    0xEDC20, 0xEDC20, 0xEDC20, 0xEDC20, 0xEDC20, 0xEDC20, 0xEDC20,  # 0x2B–0x31
    0xEED8C,  # 0x32
    0xEED8C,  # 0x33
    0xEF0A4,  # 0x34
)

# (offset, size, name, type) for version 0x34; size = distance to the next field (incl. padding)
TOP_LEVEL_FIELDS = (
    (0x00000, 4, "version", "int"),
    (0x00004, 2000, "intValues", "int[500]"),
    (0x007D4, 16000, "boolValues", "bool[4000] (4 B/Elem)"),
    (0x04654, 4000, "systemFlags", "bool[1000]"),
    (0x055F4, 64, "rivalName", "string (32 UTF-16)"),
    (0x05634, 4, "zoneID", "ZoneID"),
    (0x05638, 4, "timeScale", "float"),
    (0x0563C, 48000, "saveItem", "SaveItem[3000] x 16"),
    (0x111BC, 11988, "saveUgItem", "SaveUgItem[999] x 12"),
    (0x14090, 8, "saveItemShortcut", "ushort[4]"),
    (0x14098, 2066, "playerParty", "SavePokeParty"),
    (0x148AA, 1610, "boxData", "SaveBoxData"),
    (0x14EF4, 412800, "boxTray", "SaveBoxTrayData[40] x 10320 (30 × 344)"),
    (0x79B74, 1972, "playerData", "PLAYER_DATA"),
    (0x7A328, 12472, "zukanData", "ZUKAN_WORK"),
    (0x7D3E0, 5656, "tr_battleData", "TR_BATTLE_DATA[707] x 8"),
    (0x7E9F8, 68, "topMenuData", "TOPMENU_WORK"),
    (0x7EA3C, 68000, "fieldObj_Save", "_FIELDOBJ_SAVE"),
    (0x8F3DC, 1440, "record", "RECORD_ARRAY"),
    (0x8F97C, 392, "enc_sv_data", "ENC_SV_DATA"),
    (0x8FB04, 128, "player_save_data", "PLAYER_SAVE_DATA"),
    (0x8FB84, 17032, "ballDecoData", "SaveBallDecoData"),
    (0x93E0C, 2400, "saveSeal", "SaveSealData[200] x 12"),
    (0x9476C, 1584, "randomGroup", "_RANDOM_GROUP"),
    (0x94D9C, 12, "fieldGimmickSaveData", "FieldGimmickSaveData"),
    (0x94DA8, 2056, "kinomiGrowSaveData", "KinomiGrowSaveData"),
    (0x955B0, 1604, "poffinSaveData", "PoffinSaveData"),
    (0x95BF4, 440, "btlTowerSave", "BTLTOWER_SAVEWORK"),
    (0x95DAC, 308, "systemData", "SYSTEMDATA"),
    (0x95EE0, 416, "poketchData", "POKETCH_DATA"),
    (0x96080, 704, "azukariyaData", "AzukariyaData"),
    (0x96340, 14768, "dendoudata", "_DENDOU_SAVEDATA"),
    (0x99CF0, 8, "badgeSaveData", "BadgeSaveData"),
    (0x99CF8, 24, "boukenNote", "BoukenNote"),
    (0x99D10, 2956, "tvDataOld", "byte[]"),
    (0x9A89C, 10144, "ugSaveData", "UgSaveData"),
    (0x9D03C, 201508, "gmsdata", "GMS_DATA"),
    (0xCE360, 1712, "networkdata", "PLAYER_NETWORK_DATA"),
    (0xCEA10, 12, "unionSaveData", "UnionSaveData"),
    (0xCEA1C, 24, "contstPhotoLangData", "CON_PHOTO_LANG_DATA"),
    (0xCEA34, 100, "zukanPersonalRndData", "ZUKAN_PERSONAL_RND_DATA"),
    (0xCEA98, 160, "contestPhotoExtData", "CON_PHOTO_EXT_DATA[]"),
    (0xCEB38, 104000, "gmsPointExtData", "GMS_POINT_HISTORY_EXT_DATA[]"),
    (0xE8178, 32, "ugCountRecord", "UgCountRecord"),
    (0xE8198, 5760, "reBuffNameData", "ReBuffnameData"),
    (0xE9818, 16, "saveDataHash", "byte[16] (MD5)"),
    (0xE9828, 960, "recodeAddData", "RECORD_ADD_DATA"),
    (0xE9BE8, 13680, "mysteryGiftSaveData", "MysteryGiftSaveData"),
    (0xED158, 48, "poketoreCountArray", "POKETCH_POKETORE_COUNT_ARRAY"),
    (0xED188, 248, "playReportData", "PLAYREPORT_DATA"),
    (0xED280, 1024, "mtData", "MT_DATA"),
    (0xED680, 1440, "dendouSaveAdd", "DENDOU_SAVE_ADD"),
    (0xEDC20, 4460, "tvData", "TV_DATA"),
    (0xEED8C, 792, "ballDecoExtraData", "SaveBallDecoExtraData"),
)


class SaveFormatError(ValueError):
    """The file cannot be classified as a BDSP save."""


def read_header(data):
    """Returns (version, file size); the version is a signed u32 LE value at the start."""
    if len(data) < 4:
        raise SaveFormatError("File shorter than 4 bytes, no version readable")
    (version,) = struct.unpack_from("<i", data, 0)
    return version, len(data)


def expected_size(version):
    """Expected file size/hash length, or None for versions without a table entry."""
    if LAUNCH_VERSION <= version <= CURRENT_VERSION:
        return BINARY_SIZE[version - LAUNCH_VERSION]
    return None


def _hash_length(data, version):
    n = expected_size(version)
    if n is None:
        raise SaveFormatError("Version 0x%X has no hash length (known: 0x%X–0x%X)"
                              % (version & 0xFFFFFFFF, LAUNCH_VERSION, CURRENT_VERSION))
    if len(data) < n:
        raise SaveFormatError("File truncated: %d bytes, expected %d (0x%X)" % (len(data), n, n))
    return n


def compute_hash(data, version=None):
    """MD5 over the first N bytes with the hash field set to 0 (N depends on the version)."""
    if version is None:
        version = read_header(data)[0]
    n = _hash_length(data, version)
    buf = bytearray(data[:n])
    buf[HASH_OFFSET:HASH_END] = bytes(HASH_LEN)
    return hashlib.md5(buf).digest()


def stored_hash(data):
    if len(data) < HASH_END:
        raise SaveFormatError("File too short for the hash field (< 0x%X bytes)" % HASH_END)
    return bytes(data[HASH_OFFSET:HASH_END])


def verify_hash(data):
    """True/False; None if the game does not check the version (< 0x25).
    Raises SaveFormatError for an unknown version or a truncated file."""
    version, _ = read_header(data)
    if version < LAUNCH_VERSION:
        return None
    return compute_hash(data, version) == stored_hash(data)


def fix_hash(src_path, dst_path):
    """Writes a copy of src to dst with the correct hash; src stays untouched."""
    if os.path.exists(dst_path) and os.path.samefile(src_path, dst_path):
        raise SaveFormatError("Output must not be the input file")
    if os.path.exists(dst_path):
        raise SaveFormatError("Output file already exists: %s" % dst_path)
    with open(src_path, "rb") as f:
        data = bytearray(f.read())
    version, _ = read_header(data)
    if version < LAUNCH_VERSION:
        raise SaveFormatError("Versions below 0x%X have no hash" % LAUNCH_VERSION)
    data[HASH_OFFSET:HASH_END] = compute_hash(data, version)
    with open(dst_path, "xb") as f:
        f.write(data)
    return bytes(data[HASH_OFFSET:HASH_END])


def check(data):
    """Collects all findings as a dict (version, sizes, hash status, problems)."""
    version, size = read_header(data)
    exp = expected_size(version)
    res = {"version": version, "size": size, "expected_size": exp,
           "size_ok": None if exp is None else size == exp,
           "hash_valid": None, "problems": []}
    if version < LAUNCH_VERSION:
        res["problems"].append("Version < 0x%X: the game does not check a hash" % LAUNCH_VERSION)
    elif exp is None:
        res["problems"].append("unknown version 0x%X (> 0x%X)" % (version & 0xFFFFFFFF, CURRENT_VERSION))
    else:
        if size != exp:
            res["problems"].append("size %d differs from the expected %d" % (size, exp))
        try:
            res["hash_valid"] = verify_hash(data)
        except SaveFormatError as e:
            res["problems"].append(str(e))
        else:
            if res["hash_valid"] is False:
                res["problems"].append("MD5 does not match")
    return res


def format_fields():
    lines = ["%-9s %-8s %-22s %s" % ("Offset", "Size", "Field", "Type")]
    for off, size, name, typ in TOP_LEVEL_FIELDS:
        lines.append("0x%06X  %-8d %-22s %s" % (off, size, name, typ))
    return "\n".join(lines)


def _yn(v):
    return {True: "yes", False: "no", None: "not checkable"}[v]


def cmd_check(args):
    with open(args.file, "rb") as f:
        data = f.read()
    try:
        r = check(data)
    except SaveFormatError as e:
        print("Error: %s" % e)
        return 2
    print("Version:  %d (0x%X)" % (r["version"], r["version"] & 0xFFFFFFFF))
    print("Size:     %d (0x%X)" % (r["size"], r["size"]))
    if r["expected_size"] is not None:
        print("Expected: %d (0x%X), matches: %s" % (r["expected_size"], r["expected_size"], _yn(r["size_ok"])))
    print("Hash valid: %s" % _yn(r["hash_valid"]))
    for p in r["problems"]:
        print("Note: %s" % p)
    if args.fields:
        print()
        print(format_fields())
    if r["hash_valid"] is True and r["size_ok"]:
        return 0
    return 1 if r["hash_valid"] is False or r["size_ok"] is False else 2


def cmd_dump_fields(_args):
    print(format_fields())
    return 0


def cmd_fix_hash(args):
    try:
        h = fix_hash(args.input, args.output)
    except (SaveFormatError, OSError) as e:
        print("Error: %s" % e)
        return 2
    print("New hash written to %s: %s" % (args.output, h.hex()))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Check a BDSP save")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check version, size and hash")
    c.add_argument("file")
    c.add_argument("--fields", action="store_true", help="also print the field table")
    c.set_defaults(func=cmd_check)
    d = sub.add_parser("dump-fields", help="print the top-level field table")
    d.set_defaults(func=cmd_dump_fields)
    x = sub.add_parser("fix-hash", help="write a copy with the correct hash")
    x.add_argument("input")
    x.add_argument("output")
    x.set_defaults(func=cmd_fix_hash)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
