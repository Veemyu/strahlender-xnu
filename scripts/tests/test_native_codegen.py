"""Native image parity, malformed containers and path tests; no game data."""
import importlib.util
import json
import os
import platform
import random
import shutil
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "scripts/recomp/native-generator"
SPEC = importlib.util.spec_from_file_location("native_codegen_build", HERE / "build.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def synthetic_nso(path, compressed=False):
    """ELF dynamic symbols and every relocation binding branch, built by hand."""
    text = bytearray(0x100)
    struct.pack_into("<II", text, 0, 0xd65f03c0, 0x1000)
    ro = bytearray(0x1000)
    ro[:4] = b"MOD0"
    struct.pack_into("<6i", ro, 4, 0x100, 0x1800, 0x1900, 0x30, 0x30, 0)
    names = ["", "local", "linked", "missing", "weak", "_Znwm", "forced", "日本語🧩"]
    strings = b""
    symbols = b""
    for i, name in enumerate(names):
        offset = len(strings)
        strings += name.encode() + b"\0"
        info = 0x22 if name == "weak" else 0x12
        defined = name in ("local", "_Znwm", "forced", "日本語🧩")
        symbols += struct.pack("<IBBHQQ", offset, info, 0, int(defined), 0x80 + i * 4 if defined else 0, 4 if defined else 0)
    ro[0x300:0x308] = struct.pack("<II", 1, len(names))
    ro[0x400:0x400 + len(symbols)] = symbols
    ro[0x600:0x600 + len(strings)] = strings
    # Relative, defined, linked ABS64, weak, unresolved ABS64, interposed,
    # forced, unsupported relocation, signed relative, PLT linked.
    relocations = [(0x2000, 1027, 0, 0x20), (0x2008, 257, 1, 3),
                   (0x2010, 257, 2, -4), (0x2018, 257, 4, 9),
                   (0x2020, 257, 3, 17), (0x2028, 1026, 5, 11),
                   (0x2030, 257, 6, -2), (0x2038, 999, 0, 0),
                   (0x2040, 1027, 0, -8)]
    rela = b"".join(struct.pack("<QQq", off, sym << 32 | typ, add) for off, typ, sym, add in relocations)
    ro[0x700:0x700 + len(rela)] = rela
    ro[0x900:0x918] = struct.pack("<QQq", 0x2048, 2 << 32 | 1025, 55)
    dyn = [(4, 0x1300), (6, 0x1400), (5, 0x1600), (10, len(strings)),
           (7, 0x1700), (8, len(rela)), (23, 0x1900), (2, 24),
           (12, 0x88), (25, 0x2080), (27, 16), (0, 0)]
    for i, entry in enumerate(dyn):
        struct.pack_into("<QQ", ro, 0x100 + i * 16, *entry)
    header = bytearray(0x100)
    header[:4] = b"NSO0"
    struct.pack_into("<I", header, 0x3c, 0x100)
    header[0x40:0x60] = bytes(range(32))
    segments = []
    if compressed:
        import lz4.block
        struct.pack_into("<I", header, 0xc, 7)
    offset = 0x100
    for i, (memory, raw) in enumerate(((0, text), (0x1000, ro), (0x2000, bytearray(0x100)))):
        data = lz4.block.compress(bytes(raw), store_size=False) if compressed else bytes(raw)
        struct.pack_into("<III", header, 0x10 + i * 16, offset, memory, len(raw))
        struct.pack_into("<I", header, 0x60 + i * 4, len(data))
        segments.append(data)
        offset += len(data)
    path.write_bytes(header + b"".join(segments))
    return path


def synthetic_eh_nso(path):
    synthetic_nso(path)
    raw = bytearray(path.read_bytes())
    ro = 0x200
    struct.pack_into("<ii", raw, ro + 16, 0xa00, 0xa14)
    hdr, cie, fde, lsda = 0x1a00, 0x1b00, 0x1b40, 0x1c00
    struct.pack_into("<4B i I ii", raw, ro + 0xa00, 1, 0x1b, 3, 0x3b,
                     cie - (hdr + 4), 1, 0x80 - hdr, fde - hdr)
    cie_body = struct.pack("<I", 0) + b"\x01zLR\0\x01\x78\x1e\x02\x1b\x1b"
    raw[ro + 0xb00:ro + 0xb00 + len(cie_body) + 4] = struct.pack("<I", len(cie_body)) + cie_body
    fde_body = struct.pack("<IiiB", fde + 4 - cie, 0x80 - (fde + 8), 0x20, 4)
    fde_body += struct.pack("<i", lsda - (fde + 8 + 4 + 4 + 1))
    raw[ro + 0xb40:ro + 0xb40 + len(fde_body) + 4] = struct.pack("<I", len(fde_body)) + fde_body
    raw[ro + 0xc00:ro + 0xc08] = bytes((0xff, 0xff, 1, 4, 0, 0x10, 8, 0))
    path.write_bytes(raw)
    return path


class NativeCodegenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temporary.name) / "Library/Application Support/O'Brien 日本語"
        cls.folder.mkdir(parents=True)
        spec = importlib.util.spec_from_file_location("native_frozen_reference", HERE / "compare.py")
        compare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compare)
        cls.reference = compare.snapshot(cls.folder)
        cls.binary = Path(os.environ["BDSP_CODEGEN_TEST_BINARY"]).resolve() if os.environ.get("BDSP_CODEGEN_TEST_BINARY") else builder.build(cls.folder / "bdsp_codegen")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_native(self, *arguments, check=True):
        result = subprocess.run([str(self.binary), *map(str, arguments)], capture_output=True, text=True, timeout=30)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_version_and_cached_compiler_output(self):
        version = json.loads(self.run_native("--version", "--json").stdout)
        self.assertEqual(version["capabilities"], ["image", "inspect", "decode-basic", "emit-function", "analyze", "gen"])
        self.assertEqual(version["lz4"], "1.9.4")
        cached = builder.build(self.folder / "cached_codegen")
        before = cached.stat().st_mtime_ns
        self.assertEqual(builder.build(cached), cached)
        self.assertEqual(cached.stat().st_mtime_ns, before)
        self.assertEqual(len(version["source"]), 64)

    def test_image_matches_python_for_all_binding_branches_and_lz4(self):
        for compressed in (False, True):
            with self.subTest(compressed=compressed), tempfile.TemporaryDirectory(dir=self.folder) as tmp:
                folder = Path(tmp)
                nso = synthetic_nso(folder / "input.nso", compressed)
                links = folder / "links.json"
                links.write_text(json.dumps({"linked": 0x123456789, "日本語🧩": 0x987654321}))
                override = folder / "override.json"
                override.write_text(json.dumps({"_Znwm": 0x66666666, "local": 99}))
                forced = folder / "hle-list.txt"
                forced.write_text("# comment\n  forced  \n\n")
                for module in ("sdk", "main"):
                    native, reference = folder / (module + " native"), folder / (module + " reference")
                    for out in (native, reference):
                        out.mkdir()
                        (out / "hle.txt").write_text("previous\nmissing\n")
                    common = [str(nso), module, "--base", "0x807000000", "--hle-base", "0x80a000000",
                              "--link", str(links), "--interpose-from", str(override), "--hle-list", str(forced)]
                    self.run_native("image", *common, "--out", native)
                    old = subprocess.run([sys.executable, str(self.reference / "scripts/recomp/mkimg.py"),
                                          *common, "--out", str(reference)], capture_output=True, text=True, timeout=30)
                    self.assertEqual(old.returncode, 0, old.stderr)
                    actual = {p.name: p.read_bytes() for p in native.iterdir()}
                    expected = {p.name: p.read_bytes() for p in reference.iterdir()}
                    self.assertEqual(actual, expected)
                    original = {p.name: p.stat().st_mtime_ns for p in native.iterdir()}
                    self.run_native("image", *common, "--out", native)
                    self.assertEqual(original, {p.name: p.stat().st_mtime_ns for p in native.iterdir()})

    def test_invalid_utf8_symbol_replacement_matches_python_binding(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            folder = Path(temporary)
            nso = synthetic_nso(folder / "source")
            payload = nso.read_bytes().replace(b"linked\x00", b"l\x80nked\x00")
            nso.write_bytes(payload)
            symbols = folder / "symbols.json"
            symbols.write_text(json.dumps({"l\ufffdnked": 0x12345}))
            common = [str(nso), "main", "--base", "0x801000000", "--link", str(symbols)]
            out, reference = folder / "native", folder / "reference"
            self.run_native("image", *common, "--out", out)
            result = subprocess.run([sys.executable, str(self.reference / "scripts/recomp/mkimg.py"),
                                     *common, "--out", str(reference)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual({p.name: p.read_bytes() for p in out.iterdir()},
                             {p.name: p.read_bytes() for p in reference.iterdir()})

    def test_native_initial_analysis_matches_frozen_eh_and_setjmp_reference(self):
        compare_spec = importlib.util.spec_from_file_location("native_codegen_compare", HERE / "compare.py")
        compare = importlib.util.module_from_spec(compare_spec)
        compare_spec.loader.exec_module(compare)
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            folder = Path(temporary)
            reference = compare.snapshot(folder)
            nso = synthetic_eh_nso(folder / "eh.nso")
            for base in ("0x7000000000", "0x801000000"):
                # BL at entry 0 targets the extra setjmp symbol at offset 0x80.
                data = bytearray(nso.read_bytes())
                struct.pack_into("<I", data, 0x100, 0x94000020)
                nso.write_bytes(data)
                common = [str(nso), "test", "--base", base, "--setjmp-at", "0x80"]
                actual = json.loads(self.run_native("inspect", *common).stdout)
                result = subprocess.run([sys.executable, str(HERE / "reference_analysis.py"),
                                         "--reference", str(reference), *common],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(actual, json.loads(result.stdout))
                self.assertEqual(actual["landing_pads"], [int(base, 0) + 0x88])
                self.assertEqual(actual["setjmp_returns"], [int(base, 0) + 4])
            broken = bytearray(nso.read_bytes())
            broken[0x200 + 0xc03] = 0x7f
            nso.write_bytes(broken)
            result = self.run_native("inspect", nso, "test", "--base", "0x801000000", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exception", result.stderr)

    def test_rejects_bad_inputs_without_publishing_files_or_private_paths(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            folder = Path(temporary)
            valid = synthetic_nso(folder / "source")
            data = valid.read_bytes()
            cases = [b"", b"NSO0", b"BAD!" + data[4:]]
            for offset, value in ((0x10, 0xffffffff), (0x14, 0xffffffff), (0x60, 0xffffffff)):
                changed = bytearray(data)
                struct.pack_into("<I", changed, offset, value)
                cases.append(changed)
            # Invalid symbol table reference in a relocation.
            changed = bytearray(data)
            struct.pack_into("<Q", changed, 0x200 + 0x700 + 24 + 8, 999 << 32 | 257)
            cases.append(changed)
            for i, payload in enumerate(cases):
                source = folder / ("bad-" + str(i))
                source.write_bytes(payload)
                out = folder / ("out-" + str(i))
                result = self.run_native("image", source, "main", "--base", "0x10000", "--out", out,
                                         "--events=jsonl", check=False)
                self.assertNotEqual(result.returncode, 0)
                event = json.loads(result.stdout)
                self.assertEqual(event["event"], "error")
                self.assertNotIn(str(folder), result.stdout + result.stderr)
                self.assertFalse(out.exists())

    def test_scalar_ir_matches_frozen_lifter(self):
        compare_spec = importlib.util.spec_from_file_location("native_codegen_compare", HERE / "compare.py")
        compare = importlib.util.module_from_spec(compare_spec)
        compare_spec.loader.exec_module(compare)
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            reference = compare.snapshot(Path(temporary))
            rng = random.Random(48219)
            words = [0, 0xd503201f, 0xd5033f5f, 0xd5033f9f, 0xd4000001,
                     0xd4200000, 0xd65f03c0, 0xd65f0000, 0xd65f03e0, 0xd61f03e0,
                     0xd53b4400, 0xd53b4420, 0xd51b4400, 0xd51b4420]
            words += [(rng.getrandbits(32) & ~(15 << 25)) | rng.choice((8, 9, 10, 11)) << 25
                      for _ in range(3000)]
            # Scalar load/store families: addressing, writeback, signed loads and exclusive pairs.
            words += [(rng.getrandbits(32) & ~((15 << 25) | (1 << 26))) | rng.choice((4, 12)) << 25
                      for _ in range(6000)]
            words += [0xf9400020, 0xa9bf7bfd, 0xa8c17bfd, 0xc87f0440, 0xc8200440,
                      0x887f0440, 0x88200440, 0xf85f8c00, 0x98000000, 0x18ffffe0]
            # Register arithmetic; CRC pass-through assembly is still a pending IR family.
            reg_words = [(rng.getrandbits(32) & ~(15 << 25)) | rng.choice((5, 13)) << 25
                         for _ in range(6000)]
            words += [w for w in reg_words if not (w >> 28 & 1 and w >> 24 & 15 != 11
                       and w >> 21 & 15 == 6 and not w >> 30 & 1 and 16 <= (w >> 10 & 63) <= 23)]
            # Exhaust every immediate bit-mask encoding, including reserved forms.
            words += [0xd2000000 | n << 22 | r << 16 | s << 10 | 31 << 5 | 3
                      for n in range(2) for r in range(64) for s in range(64)]
            stream = "".join(f"{word:08x}\n" for word in words)
            for pc, mode in ((0, "asm"), (0x801001000, "c"), (0x7000001000, "asm")):
                common = ["--pc", hex(pc), "--simd", mode]
                expected = subprocess.run([sys.executable, str(HERE / "reference_decode.py"),
                                           "--reference", str(reference), *common], input=stream,
                                          capture_output=True, text=True, timeout=60)
                actual = subprocess.run([str(self.binary), "decode", *common], input=stream,
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(expected.returncode, 0, expected.stderr)
                self.assertEqual(actual.returncode, 0, actual.stderr)
                left = [json.loads(line) for line in expected.stdout.splitlines()]
                right = [json.loads(line) for line in actual.stdout.splitlines()]
                self.assertEqual(len(left), len(words))
                self.assertEqual(len(right), len(words))
                for word, old, new in zip(words, left, right):
                    self.assertEqual(new, old, f"instruction {word:08x}, PC={pc:x}, SIMD={mode}")
            for previous in (0x910003bf, 0xd503201f):
                arguments = ["--pc", "0x801001000", "--previous-word", hex(previous)]
                old = subprocess.run([sys.executable, str(HERE / "reference_decode.py"),
                                      "--reference", str(reference), *arguments], input="d65f03c0\n",
                                     capture_output=True, text=True, check=True)
                new = subprocess.run([str(self.binary), "decode", *arguments], input="d65f03c0\n",
                                     capture_output=True, text=True, check=True)
                self.assertEqual(json.loads(old.stdout), json.loads(new.stdout))
            # CRC is C code in portable SIMD mode; native ASM metadata is a later checkpoint.
            crc_words = [0x1ac00000 | sf << 31 | opc << 10 | rm << 16 | rn << 5 | rd
                         for sf in range(2) for opc in range(16, 24)
                         for rm, rn, rd in ((3, 4, 5), (31, 31, 31))]
            crc_stream = "".join(f"{w:08x}\n" for w in crc_words)
            arguments = ["--pc", "0x801001000", "--simd", "c"]
            old = subprocess.run([sys.executable, str(HERE / "reference_decode.py"),
                                  "--reference", str(reference), *arguments], input=crc_stream,
                                 capture_output=True, text=True, check=True)
            new = subprocess.run([str(self.binary), "decode", *arguments], input=crc_stream,
                                 capture_output=True, text=True, check=True)
            self.assertEqual([json.loads(x) for x in old.stdout.splitlines()],
                             [json.loads(x) for x in new.stdout.splitlines()])
            pending = subprocess.run([str(self.binary), "decode", "--pc", "0x801001000", "--simd", "c"],
                                     input="4e208400\n", capture_output=True, text=True, check=True)
            self.assertTrue(json.loads(pending.stdout)["handled"])

    def test_aarch64_assembly_ir_matches_frozen_lifter(self):
        spec = importlib.util.spec_from_file_location("asm_compare", HERE / "compare.py")
        compare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compare)
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            reference = compare.snapshot(Path(temporary))
            rng = random.Random(71047)
            words = [(rng.getrandbits(32) & ~(15 << 25)) | rng.choice((6, 7, 14, 15)) << 25
                     for _ in range(5000)]
            # Reserved SIMD literal opc=3 raises KeyError in the frozen Python decoder.
            words = [w for w in words if not (w >> 27 & 7 == 3 and w >> 24 & 3 == 0 and w >> 30 == 3)]
            words += [0x9cffffe0, 0x1e202000, 0x1e200400, 0x3dc003e0, 0x4c4073ff,
                      0x1ac04000, 0x9ac04c00, 0x1e26001f, 0x1e2703e0]
            stream = "".join(f"{w:08x}\n" for w in words)
            for pc in (0, 0x801001000):
                arguments = ["--pc", hex(pc), "--simd", "asm"]
                old = subprocess.run([sys.executable, str(HERE / "reference_decode.py"),
                                      "--reference", str(reference), *arguments], input=stream,
                                     capture_output=True, text=True)
                self.assertEqual(old.returncode, 0, old.stderr)
                new = subprocess.run(
                    [str(self.binary), "decode", *arguments], input=stream, capture_output=True, text=True, check=True)
                left, right = ([json.loads(line) for line in result.stdout.splitlines()] for result in (old, new))
                self.assertEqual(len(left), len(words))
                self.assertEqual(len(right), len(words))
                for w, a, b in zip(words, left, right):
                    self.assertEqual(a, b, f"assembly IR {w:08x}, PC={pc:x}")

    def test_portable_memory_and_scalar_fp_ir(self):
        spec = importlib.util.spec_from_file_location("portable_compare", HERE / "compare.py")
        compare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compare)
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            reference = compare.snapshot(Path(temporary))
            rng = random.Random(194409)
            words = [(rng.getrandbits(32) & ~(15 << 25)) | rng.choice((6, 14)) << 25
                     for _ in range(12000)]
            words += [(rng.getrandbits(32) & ~(15 << 25)) | 15 << 25 for _ in range(12000)]
            # Scalar FP op0 (bits28..31) selects 1,3,9,11; other AdvSIMD families follow later.
            words = [w for w in words if w >> 25 & 15 in (6, 14) or (w >> 28 & 5) == 1]
            # Exhaust scalar FP immediate payloads for both widths.
            words += [0x1e201000 | t << 22 | imm << 13 | d
                      for t in range(2) for imm in range(256) for d in (0, 31)]
            words += [0x4cdfa03f, 0x4c4073ff, 0x9cffffe0, 0x3dc003e0, 0x3cc10420,
                      0x1e222820, 0x1e624820, 0x9e660000, 0x9eae0000, 0x1e23c000]
            stream = "".join(f"{w:08x}\n" for w in words)
            for pc in (0, 0x801001000):
                arguments = ["--pc", hex(pc), "--simd", "c"]
                old = subprocess.run([sys.executable, str(HERE / "reference_decode.py"),
                                      "--reference", str(reference), *arguments], input=stream,
                                     capture_output=True, text=True)
                self.assertEqual(old.returncode, 0, old.stderr)
                new = subprocess.run([str(self.binary), "decode", *arguments], input=stream,
                                     capture_output=True, text=True, check=True)
                left, right = ([json.loads(line) for line in result.stdout.splitlines()] for result in (old, new))
                self.assertEqual(len(left), len(words))
                self.assertEqual(len(right), len(words))
                for w, a, b in zip(words, left, right):
                    self.assertEqual(a, b, f"portable IR {w:08x}, PC={pc:x}")

    def test_portable_vector_ir_matches_frozen_simdc(self):
        spec = importlib.util.spec_from_file_location("vector_compare", HERE / "compare.py")
        compare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compare)
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            reference = compare.snapshot(Path(temporary))
            rng = random.Random(622512)
            words = [(rng.getrandbits(32) & ~(15 << 25)) | rng.choice((7, 15)) << 25
                     for _ in range(20000)]
            words += [family | q << 30 | u << 29 | sz << 22 | opc << shift | 3 << 5 | 7
                      for family, shift, count in ((0x0e200400, 11, 32), (0x0e200800, 12, 32),
                                                    (0x0e200000, 12, 16), (0x5e200400, 11, 32),
                                                    (0x5e200800, 12, 32))
                      for q in range(2) for u in range(2) for sz in range(4) for opc in range(count)]
            words += [0x0f000400 | q << 30 | u << 29 | ih << 19 | ib << 16 | opc << 11 | 3 << 5 | 7
                      for q in range(2) for u in range(2) for ih in range(1, 16)
                      for ib in range(8) for opc in range(32)]
            words += [0x0f000400 | q << 30 | u << 29 | cm << 12 | (imm >> 5) << 16 | (imm & 31) << 5
                      for q in range(2) for u in range(2) for cm in range(16) for imm in range(256)]
            stream = "".join(f"{w:08x}\n" for w in words)
            args = ["--pc", "0x801001000", "--simd", "c"]
            old = subprocess.run([sys.executable, str(HERE / "reference_decode.py"),
                                  "--reference", str(reference), *args], input=stream,
                                 capture_output=True, text=True)
            self.assertEqual(old.returncode, 0, old.stderr)
            new = subprocess.run([str(self.binary), "decode", *args], input=stream,
                                 capture_output=True, text=True, check=True)
            left, right = ([json.loads(line) for line in result.stdout.splitlines()] for result in (old, new))
            self.assertEqual(len(left), len(words))
            self.assertEqual(len(right), len(words))
            for w, a, b in zip(words, left, right):
                self.assertEqual(a, b, f"vector IR {w:08x}")

    @unittest.skipUnless(shutil.which("clang"), "worker probe requires Clang")
    def test_native_worker_ordering_arena_lifetime_and_failure_cleanup(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            binary = Path(temporary) / "workers"
            src = HERE / "src"
            command = ["clang", "-std=c17", "-O2", "-pthread", "-I", str(src),
                       str(ROOT / "scripts/tests/native_codegen_workers.c"),
                       *(str(src / name) for name in ("workers.c", "support.c", "json.c")),
                       "-o", str(binary)]
            subprocess.run(command, check=True, capture_output=True, text=True)
            for args in ([], ["fail"]):
                result = subprocess.run([str(binary), *args], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_full_analysis_matches_frozen_unicorn_scan(self):
        if self.run_native("--version", "--json").stdout.find('"unicorn":"2.1.4"') < 0:
            self.skipTest("native Unicorn dependency unavailable in this checkpoint build")
        spec = importlib.util.spec_from_file_location("scan_compare", HERE / "compare.py")
        compare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compare)
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            folder = Path(temporary)
            reference = compare.snapshot(folder)
            source = synthetic_nso(folder / "scan.nso")
            raw = bytearray(source.read_bytes())
            # cmp w0,#2; b.hi default; adr table; ldr relative offset; adr cases; add; br.
            words = [0x7100081f, 0x54000168, 0x100001c1, 0xb8605822,
                     0x10000083, 0x8b22c063, 0xd61f0060, 0xd503201f,
                     0xd65f03c0, 0xd65f03c0, 0xd65f03c0, 0xd503201f, 0xd65f03c0]
            base = 0x7000000000
            for taken in (False, True):
                words[1] = 0x54000029 if taken else 0x54000168
                struct.pack_into("<13I", raw, 0x120, *words)
                struct.pack_into("<3I", raw, 0x160, 0, 4, 8)
                source.write_bytes(raw)
                for extra in ((0x20,), (0x20, 0x34, 0x44)):
                    offsets = folder / "entries"
                    offsets.write_text(" ".join(f"{v:x}" for v in extra))
                    for mode in ("asm", "c"):
                        args = [str(source), "synthetic", "--base", hex(base), "--simd", mode,
                                "--entry-offsets", str(offsets)]
                        old = subprocess.run([sys.executable, str(HERE / "reference_scan.py"),
                                              "--reference", str(reference), *args], text=True, capture_output=True)
                        self.assertEqual(old.returncode, 0, old.stderr)
                        new = self.run_native("analyze", *args, "--jobs", "1" if taken else "3")
                        expected = json.loads(old.stdout)
                        self.assertGreater(expected["jumptables"], 0)
                        self.assertEqual(json.loads(new.stdout), expected,
                                         f"taken={taken}, entries={extra}, mode={mode}")

    def test_whole_module_chunk_files_match_frozen_generator(self):
        if json.loads(self.run_native("--version", "--json").stdout).get("unicorn") is None:
            self.skipTest("native Unicorn dependency unavailable")
        spec = importlib.util.spec_from_file_location("chunk_compare", HERE / "compare.py")
        compare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compare)
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            folder = Path(temporary)
            reference = compare.snapshot(folder)
            source = synthetic_nso(folder / "chunks.nso")
            raw = bytearray(source.read_bytes())
            words = [0x7100081f, 0x54000168, 0x100001c1, 0xb8605822, 0x10000083,
                     0x8b22c063, 0xd61f0060, 0xd503201f, 0xd65f03c0, 0xd65f03c0,
                     0xd65f03c0, 0xd503201f, 0xd65f03c0]
            struct.pack_into("<13I", raw, 0x120, *words)
            struct.pack_into("<3I", raw, 0x160, 0, 4, 8)
            source.write_bytes(raw)
            entries = folder / "entries"
            entries.write_text("20 34 44")
            only = folder / "only"
            only.write_text("20 84 99")
            hle = folder / "hle"
            hle.write_text("local\n日本語🧩\n")
            cases = [[], ["--chunk", "1"], ["--chunk-bytes", "80"], ["--big-fn", "0"],
                     ["--window", "16"], ["--limit", "3"], ["--only", str(only)],
                     ["--hle", str(hle)]]
            for mode in ("asm", "c"):
                for index, options in enumerate(cases):
                    old_out = folder / f"old-{mode}-{index}"
                    new_out = folder / f"new-{mode}-{index}"
                    common = ["synthetic", str(source), "0x7000000000"]
                    flags = ["--simd", mode, "--entry-offsets", str(entries), *options]
                    old = subprocess.run([sys.executable, str(reference / "scripts/recomp/eh_gen.py"),
                                          "--las-dir", str(reference / "scripts/recomp/upstream/generator"),
                                          "gen", *common, str(old_out), *flags], text=True, capture_output=True)
                    self.assertEqual(old.returncode, 0, old.stderr)
                    self.run_native("gen", *common, new_out, *flags, "--jobs", "3")
                    expected = {p.name: p.read_bytes() for p in old_out.iterdir()}
                    actual = {p.name: p.read_bytes() for p in new_out.iterdir()}
                    self.assertEqual(actual, expected, f"mode={mode}, options={options}")
                    before = {p.name: p.stat().st_mtime_ns for p in new_out.iterdir()}
                    self.run_native("gen", *common, new_out, *flags, "--jobs", "1")
                    self.assertEqual({p.name: p.stat().st_mtime_ns for p in new_out.iterdir()}, before)
            # Prune only matching chunk files and unlink symlinks without touching their targets.
            outside = folder / "keep.c"
            outside.write_text("preserve")
            (new_out / "synthetic_99999_0.c").symlink_to(outside)
            (new_out / "unrelated.c").write_text("unrelated")
            (new_out / "synthetic_notes.c").write_text("notes")
            self.run_native("gen", *common, new_out, *flags)
            self.assertFalse((new_out / "synthetic_99999_0.c").exists())
            self.assertEqual(outside.read_text(), "preserve")
            self.assertEqual((new_out / "unrelated.c").read_text(), "unrelated")
            self.assertEqual((new_out / "synthetic_notes.c").read_text(), "notes")

    def test_function_emitter_matches_frozen_eh_emitter(self):
        spec = importlib.util.spec_from_file_location("emitter_compare", HERE / "compare.py")
        compare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compare)
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            folder = Path(temporary)
            reference = compare.snapshot(folder)
            module_base = 0x801000000
            base = module_base + 0x20
            source = synthetic_nso(folder / "emitter.nso")
            # NSO text segment is 256 bytes at file offset 0x100, with no unwind table.
            cases = [
                ([0x91000400, 0xd65f03c0], []),  # arithmetic + return
                ([0x14000002, 0xd503201f, 0xd65f03c0], ["--label", hex(base + 8)]),
                ([0x54000040, 0x91000400, 0xd65f03c0], ["--label", hex(base + 8)]),
                ([0x14000020], []),  # tail call inside text but outside function
                ([0x14000100], []),  # tail dispatch outside module text
                ([0x94000020, 0x94000100, 0xd63f0060, 0xd65f03c0], []),
                ([0x91000400], []),  # fallthrough to next function
                ([0xd503201f] * 56, []),  # fallthrough exactly at module text end
                ([0xd4200000], []),  # trap is terminal
                ([0xd61f0060], []),  # indirect tail dispatch
                ([0xd65f0060], []),  # ret x3 is an indirect jump
                ([0x9100009f, 0xd65f03c0], []),  # mov sp,x4; ret override
                ([0xd61f0060], ["--table", f"{base:#x}=all"]),
                ([0xd61f0060, 0xd65f03c0], ["--table", f"{base:#x}={base + 4:#x}"]),
                ([0xd61f0020, 0xd61f0040, 0xd65f03c0],
                 ["--table", f"{base + 4:#x}=all", "--table", f"{base:#x}={base + 8:#x}"]),
                ([0xd65f03c0], ["--hle", "_Z日本語-name"]),
                ([0x54000040, 0x1400001f, 0xd61f0060, 0xd65f03c0],
                 ["--label", hex(base + 8)]),
            ]
            asm_cases = [
                ([0x4e208400, 0x4e208401, 0xd65f03c0], []),
                ([0x1e202000, 0x1e200400, 0xd65f03c0], []),
                ([0x3dc003e0, 0x3dc00020, 0xd65f03c0], []),
                ([0x9c000020, 0x1e260000, 0xd65f03c0], []),
                ([0x1ac04000, 0x9ac04c00, 0xd65f03c0], []),
                ([0x4e208400] * 49 + [0xd65f03c0], []),  # 24-instruction batch limit
                ([0x1e260000 | r for r in range(12)] + [0xd65f03c0], []),  # scratch exhaustion
                ([0x4e208400, 0x4e208401, 0xd65f03c0], ["--label", hex(base + 4)]),
                ([0x4e208400, 0x4e208401, 0xd65f03c0], ["--table", f"{base + 8:#x}=all"]),
            ]
            # Last table case needs an indirect branch; preserve a SIMD prefix to test flush ordering.
            asm_cases[-1][0][-1] = 0xd61f0060
            for index, (words, options, mode) in enumerate(
                    [(w, o, "c") for w, o in cases] + [(w, o, "asm") for w, o in asm_cases]):
                raw = bytearray(source.read_bytes())
                raw[0x120:0x200] = struct.pack("<56I", *(words + [0] * (56 - len(words))))
                source.write_bytes(raw)
                for eh in (False, True):
                    common = [str(source), "--base", hex(module_base), "--entry", hex(base),
                              "--end", hex(base + 4 * len(words)), "--simd", mode, "--json", *options]
                    if eh:
                        common += ["--nle", hex(base), "--nle", hex(base + 4 * (len(words) - 1))]
                    old = subprocess.run([sys.executable, str(HERE / "reference_emit.py"),
                                          "--reference", str(reference), *common],
                                         capture_output=True, text=True)
                    self.assertEqual(old.returncode, 0, old.stderr)
                    new = self.run_native("emit-function", *common)
                    self.assertEqual(json.loads(new.stdout), json.loads(old.stdout),
                                     f"case {index}, EH={eh}")
            # Invalid analysis after a valid instruction must not publish a partial function.
            raw = bytearray(source.read_bytes())
            struct.pack_into("<II", raw, 0x120, 0x91000400, 0x14000000)
            source.write_bytes(raw)
            output = folder / "preserved.c"
            output.write_text("previous valid output")
            result = self.run_native("emit-function", source, "--base", hex(module_base), "--entry", hex(base),
                                     "--end", hex(base + 8), "--simd", "c", "--out", output, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertEqual(output.read_text(), "previous valid output")
            # Reject invalid boundaries, labels and table descriptions before publication.
            for end, options in [(base, []), (base + 3, []), (base + 0x104, []),
                                 (base + 8, ["--label", hex(base + 12)]),
                                 (base + 8, ["--table", f"{base:#x}=all"])]:
                result = self.run_native("emit-function", source, "--base", hex(module_base), "--entry", hex(base),
                                         "--end", hex(end), *options, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    @unittest.skipUnless(shutil.which("clang"), "emitted execution probe requires Clang")
    def test_emitted_scalar_and_eh_functions_compile_and_execute(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            folder = Path(temporary)
            base = 0x801000000
            source = synthetic_nso(folder / "execute.nso")
            raw = bytearray(source.read_bytes())
            # Compute 12, compare, then take the success path and return with x1=15.
            arithmetic = [0xd28000a0, 0x91001c00, 0xf100301f, 0x54000061,
                          0x91000c01, 0xd65f03c0, 0xd29fffe1, 0xd65f03c0]
            # BLR invokes a test dispatcher that longjmps to the landing pad at +16.
            reentry = [0xd503201f, 0xd63f0060, 0xd2800000, 0xd65f03c0,
                       0x91000c01, 0xd65f03c0]
            struct.pack_into("<8I", raw, 0x120, *arithmetic)
            struct.pack_into("<6I", raw, 0x180, *reentry)
            source.write_bytes(raw)
            code = []
            for offset, words, label in [(0x20, arithmetic, 24), (0x80, reentry, 16)]:
                arguments = [source, "--base", hex(base), "--entry", hex(base + offset),
                             "--end", hex(base + offset + len(words) * 4), "--simd", "c",
                             "--label", hex(base + offset + label)]
                if offset == 0x80:
                    arguments += ["--nle", hex(base + offset + label)]
                code.append(self.run_native("emit-function", *arguments).stdout)
            vector_check = ""
            if platform.machine().lower() in ("arm64", "aarch64"):
                # ADD v0.16b,v0.16b,v1.16b checks native assembly register load/store mapping.
                struct.pack_into("<II", raw, 0x1c0, 0x4e218400, 0xd65f03c0)
                source.write_bytes(raw)
                code.append(self.run_native("emit-function", source, "--base", hex(base),
                                            "--entry", hex(base + 0xc0), "--end", hex(base + 0xc8),
                                            "--simd", "asm").stdout)
                vector_check = """
    memset(&c.v[0], 1, 16); memset(&c.v[1], 2, 16);
    f_8010000c0(&c);
    for (int i = 0; i < 16; i++) if (((unsigned char *)&c.v[0])[i] != 3) return 3;
"""
            program = folder / "execution.c"
            program.write_text('#include "cpu.h"\n#include <stdlib.h>\n' + "\n".join(code) + r"""
volatile int g_fnprof;
void fnprof_hit(uint64_t a, uint64_t lr, uint64_t x0) { (void)a; (void)lr; (void)x0; }
void rt_nle_fatal(Cpu *c) { (void)c; abort(); }
void rt_dispatch(Cpu *c) {
    if (!EH_TOP(c)) abort();
    c->pc = 0x801000090ull;
    _longjmp(EH_TOP(c)->jb, 1);
}
int main(void) {
    Cpu c = {0};
    f_801000020(&c);
    if (c.x[0] != 12 || c.x[1] != 15 || EH_TOP(&c)) return 1;
    c.x[1] = 0;
    f_801000080(&c);
    if (c.x[0] != 12 || c.x[1] != 15 || EH_TOP(&c)) return 2;
""" + vector_check + "    return 0;\n}\n")
            executable = folder / "execution-probe"
            result = subprocess.run(["clang", "-std=c17", "-D_DEFAULT_SOURCE", "-O2", "-w", "-I", str(ROOT / "scripts/recomp/rt"),
                                     "-I", str(ROOT / "scripts/recomp/upstream/runtime"),
                                     str(program), "-o", str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            executed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            self.assertEqual(executed.returncode, 0, executed.stderr)

    @unittest.skipUnless(shutil.which("clang"), "portable execution probe requires Clang")
    def test_emitted_portable_simd_memory_and_fp_execute(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            folder = Path(temporary)
            source = synthetic_nso(folder / "portable.nso")
            raw = bytearray(source.read_bytes())
            words = [0x3dc00000, 0x3dc00401, 0x4e218402, 0x3d800802,
                     0x1e242865, 0x9e3800a1, 0xd65f03c0]
            struct.pack_into("<7I", raw, 0x120, *words)
            struct.pack_into("<7I", raw, 0x180, *words)
            source.write_bytes(raw)
            base = 0x801000000
            portable = self.run_native("emit-function", source, "--base", hex(base), "--entry", hex(base + 0x20),
                                       "--end", hex(base + 0x20 + 4 * len(words)), "--simd", "c").stdout
            native = self.run_native("emit-function", source, "--base", hex(base), "--entry", hex(base + 0x80),
                                     "--end", hex(base + 0x80 + 4 * len(words)), "--simd", "asm").stdout
            program = folder / "portable.c"
            program.write_text('#include "cpu.h"\n#include "simd.h"\n#include <stdlib.h>\n' + portable +
                               '#ifdef __aarch64__\n' + native + '#endif\n' + r"""
volatile int g_fnprof;
void fnprof_hit(uint64_t a,uint64_t b,uint64_t d){(void)a;(void)b;(void)d;}
static void prepare(Cpu *c,unsigned char *memory){
    memset(c,0,sizeof(*c));memset(memory,1,16);memset(memory+16,2,16);memset(memory+32,0,16);
    c->x[0]=(uintptr_t)memory;
    float a=1.5f,b=2.25f;
    memcpy(&c->v[3],&a,4);memcpy(&c->v[4],&b,4);c->v[5]=~(u128)0;
}
int main(void){
    Cpu c; unsigned char memory[48];prepare(&c,memory);f_801000020(&c);
    float result;memcpy(&result,&c.v[5],4);
    if(result!=3.75f||c.x[1]!=3||(c.v[5]>>32))return 1;
    for(int i=32;i<48;i++)if(memory[i]!=3)return 2;
#ifdef __aarch64__
    Cpu n;unsigned char other[48];prepare(&n,other);rt_set_fpcr(0);rt_set_fpsr(0);f_801000080(&n);
    if(memcmp(memory,other,48)||c.x[1]!=n.x[1]||memcmp(c.v,n.v,sizeof(c.v)))return 3;
#endif
    return 0;
}
""")
            executable = folder / "portable-probe"
            built = subprocess.run(["clang", "-std=c17", "-D_DEFAULT_SOURCE", "-O2", "-w", "-I", str(ROOT / "scripts/recomp/rt"),
                                    "-I", str(ROOT / "scripts/recomp/upstream/runtime"), str(program), "-lm", "-o", str(executable)],
                                   text=True, capture_output=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)

    def test_failed_publish_preserves_existing_output_and_removes_owned_temporary(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            folder = Path(temporary)
            source = synthetic_nso(folder / "source")
            output = folder / "output"
            (output / "main.img").mkdir(parents=True)
            result = self.run_native("image", source, "main", "--base", "0x801000000", "--out", output,
                                     "--events=jsonl", check=False)
            self.assertEqual(result.returncode, 5)
            self.assertEqual(json.loads(result.stdout)["event"], "error")
            self.assertTrue((output / "main.img").is_dir())
            self.assertEqual({p.name for p in output.iterdir()}, {"main.img"})
            self.assertNotIn(str(folder), result.stdout + result.stderr)

    def test_rejects_unknown_regex_and_invalid_link_metadata(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            folder = Path(temporary)
            nso = synthetic_nso(folder / "source")
            base = ["image", nso, "main", "--base", "0x10000", "--out", folder / "out"]
            result = self.run_native(*base, "--interpose-regex", ".*", check=False)
            self.assertIn("custom interposition", result.stderr)
            metadata = folder / "symbols.json"
            for payload in ('{"a": 18446744073709551616}', '{"a": -1}', '{"a": 1,}', '{"a": 01}', '{"a": 1}junk', '{"a": 1.5}', '{"a": 1}\x00hidden'):
                metadata.write_text(payload)
                result = self.run_native(*base, "--link", metadata, check=False)
                self.assertNotEqual(result.returncode, 0, payload)
            self.assertFalse((folder / "out").exists())


if __name__ == "__main__":
    unittest.main()
