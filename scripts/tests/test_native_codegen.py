"""Native image parity, malformed containers and path tests; no game data."""
import importlib.util
import json
import os
import platform
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


@unittest.skipIf(sys.platform == "win32" and not os.environ.get("BDSP_WINDOWS_NATIVE_CC"),
                 "needs an LLVM-MinGW compiler; windows-buildenv.yml supplies it")
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
        capabilities = ["image", "inspect", "decode-basic", "emit-function"]
        if version["unicorn"]:
            capabilities += ["analyze", "gen"]
        self.assertEqual(version["capabilities"], capabilities)
        self.assertEqual(version["lz4"], "1.9.4")
        cached = builder.build(self.folder / "cached_codegen")
        before = cached.stat().st_mtime_ns
        self.assertEqual(builder.build(cached), cached)
        self.assertEqual(cached.stat().st_mtime_ns, before)
        self.assertEqual(len(version["source"]), 64)

    def test_native_library_relocation_and_corrupt_cache_recovery(self):
        dependency = builder.unicorn_dependency()
        if dependency is None:
            self.skipTest("native Unicorn package unavailable")
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            root = Path(temporary)
            original = builder.build(root / "original" / "codegen")
            relocated = root / "moved installation" / "codegen"
            relocated.parent.mkdir()
            shutil.copy2(original, relocated)
            deps = original.parent / (original.name + ".deps")
            if sys.platform == "win32":
                shutil.copy2(original.parent / dependency["library"].name, relocated.parent)
            else:
                shutil.copytree(deps, relocated.parent / deps.name)
            result = subprocess.run([str(relocated), "--version"], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["unicorn"], "2.1.4")
            metadata = original.with_suffix(original.suffix + ".json")
            record = json.loads(metadata.read_text())
            copied_library = original.parent / record["unicorn"]["library"]
            copied_library.write_bytes(b"damaged cached library")
            metadata.write_text("invalid cached metadata")
            builder.build(original)
            self.assertEqual(copied_library.read_bytes(), dependency["library"].read_bytes())
            self.assertEqual(self.run_native("--version").returncode, 0)
            checked = subprocess.run([str(original), "--version"], capture_output=True, text=True, timeout=10)
            self.assertEqual(checked.returncode, 0, checked.stderr)

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

    def test_native_generation_reaches_installer_protocol_with_function_counts(self):
        if json.loads(self.run_native("--version", "--json").stdout).get("unicorn") is None:
            self.skipTest("native Unicorn dependency unavailable")
        import contextlib
        import io
        from types import SimpleNamespace
        from scripts.install import driver
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            folder = Path(temporary)
            source = synthetic_nso(folder / "game.nso")
            args = SimpleNamespace(root=str(ROOT), base=str(source), prod_keys=None, update=None)
            command = [str(self.binary), "gen", "main", str(source), "0x7000000000",
                       str(folder / "output"), "--simd", "c", "--jobs", "3"]
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = driver._run_command(command, args, "eh_gen")
            self.assertEqual(code, 0, output.getvalue())
            events = [json.loads(line) for line in output.getvalue().splitlines()]
            details = [e for e in events if e.get("module") == "main"]
            self.assertEqual(details[0]["phase"], "analyze")
            self.assertEqual(details[0]["total"], 0)
            functions = [e for e in details if e["phase"] == "emit"]
            self.assertEqual(functions[0]["completed"], 0)
            self.assertGreater(functions[-1]["total"], 0)
            self.assertEqual(functions[-1]["completed"], functions[-1]["total"])
            self.assertTrue(list((folder / "output").glob("*.c")))
            self.assertNotIn(str(source), output.getvalue())

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
