"""Native image parity, malformed containers and path tests; no game data."""
import importlib.util
import json
import os
import random
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
        self.assertEqual(version["capabilities"], ["image", "inspect", "decode-basic"])
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
                    old = subprocess.run([sys.executable, str(ROOT / "scripts/recomp/mkimg.py"),
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
            result = subprocess.run([sys.executable, str(ROOT / "scripts/recomp/mkimg.py"),
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

    def test_immediate_and_control_ir_matches_frozen_lifter(self):
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
            pending = subprocess.run([str(self.binary), "decode", "--pc", "0x801001000"],
                                     input="f9400020\n", capture_output=True, text=True, check=True)
            self.assertFalse(json.loads(pending.stdout)["handled"])

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
