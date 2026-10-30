"""Shared helpers of the differential test (docs/recomp-diff.md): assembling, loop template, Unicorn run,
input types, loading the C libraries. Own code (helper functions only, no game bytes)."""
import ctypes
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools" / "pydeps"))
sys.dont_write_bytecode = True
import numpy as np  # noqa: E402

LAS = ROOT / "research" / "LASRecomp"
CASE_SZ, OUT_SZ = 384, 240
SLOT_MARKS = (0xE7F0A001, 0xE7F0A002, 0xE7F0A003, 0xE7F0A004)
NOP = 0xD503201F
OUT_DT = np.dtype([("v0", "<u8", 2), ("x0", "<u8"), ("nzcv", "<u8"), ("fpsr", "<u8"), ("x1", "<u8"), ("mem", "u1", 192)])
CASE_DT = np.dtype([("v", "u1", (8, 16)), ("x", "<u8", 4), ("nzcv", "<u8"), ("fpcr", "<u8"), ("memflag", "<u8"), ("pad", "<u8"),
                    ("mem", "u1", 192)])
assert OUT_DT.itemsize == OUT_SZ and CASE_DT.itemsize == CASE_SZ
T_BITS, T_F32, T_F64, T_F16, T_I8, T_I16, T_I32, T_I64 = range(8)
DF_FPCR, DF_AHP, DF_FMACANCEL, DF_MEM = 1, 2, 4, 8


def elf_text(path):
    """.text of an ELF64 object (little endian), without objcopy."""
    d = Path(path).read_bytes()
    shoff = struct.unpack_from("<Q", d, 0x28)[0]
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", d, 0x3A)
    sec = [struct.unpack_from("<IIQQQQIIQQ", d, shoff + i * shentsize) for i in range(shnum)]
    stro = sec[shstrndx][4]
    for s in sec:
        name = d[stro + s[0]:d.index(b"\0", stro + s[0])]
        if name == b".text":
            return d[s[4]:s[4] + s[5]]
    raise RuntimeError("no .text")


def assemble(lines, cc="clang", workdir=None):
    """Assembles AArch64 lines (text) -> list of 32-bit words."""
    wd = Path(workdir or ROOT / "work" / "recomp" / "diff")
    wd.mkdir(parents=True, exist_ok=True)
    src, obj = wd / "asm_tmp.S", wd / "asm_tmp.o"
    src.write_text("\t.text\n" + "\n".join("\t" + l for l in lines) + "\n")
    subprocess.run([cc, "--target=aarch64-linux-gnu", "-march=armv8-a+crypto+crc", "-c", str(src), "-o", str(obj)], check=True)
    t = elf_text(obj)
    return list(struct.unpack("<%dI" % (len(t) // 4), t))


_TMPL = {}


def template(cc="clang", workdir=None):
    """Machine code of the reference loop (tmpl.S) and the position of the four instruction slots."""
    if "code" not in _TMPL:
        wd = Path(workdir or ROOT / "work" / "recomp" / "diff")
        wd.mkdir(parents=True, exist_ok=True)
        obj = wd / "tmpl.o"
        subprocess.run([cc, "--target=aarch64-linux-gnu", "-c", str(HERE / "tmpl.S"), "-o", str(obj)], check=True)
        code = elf_text(obj)
        words = struct.unpack("<%dI" % (len(code) // 4), code)
        _TMPL["code"] = code
        _TMPL["slots"] = [words.index(m) * 4 for m in SLOT_MARKS]
    return _TMPL["code"], _TMPL["slots"]


def code_for(words):
    code, slots = template()
    b = bytearray(code)
    ws = list(words) + [NOP] * (4 - len(words))
    assert len(words) <= 4
    for off, w in zip(slots, ws):
        struct.pack_into("<I", b, off, w)
    return bytes(b)


def uc_run(words, cases, n):
    """Referenz: Unicorn (ARM64, Cortex-A57-Modell = Switch-Kern)."""
    import unicorn as uc
    from unicorn import arm64_const as A
    mu = uc.Uc(uc.UC_ARCH_ARM64, uc.UC_MODE_ARM)
    mu.ctl_set_cpu_model(A.UC_CPU_ARM64_A57)
    code = code_for(words)
    CODE, IN, STK = 0x10000, 0x1000000, 0x800000
    in_sz = (n * CASE_SZ + 0xFFF) & ~0xFFF
    out_sz = (n * OUT_SZ + 0xFFF) & ~0xFFF
    OUT = IN + in_sz
    mu.mem_map(CODE, 0x4000)
    mu.mem_write(CODE, code)
    mu.mem_map(STK, 0x10000)
    mu.mem_map(IN, in_sz + out_sz)
    mu.mem_write(IN, cases.tobytes())
    mu.reg_write(A.UC_ARM64_REG_CPACR_EL1, 0x300000)
    mu.reg_write(A.UC_ARM64_REG_SP, STK + 0xF000)
    mu.reg_write(A.UC_ARM64_REG_X0, IN)
    mu.reg_write(A.UC_ARM64_REG_X1, OUT)
    mu.reg_write(A.UC_ARM64_REG_X2, n)
    END = 0x7000000
    mu.reg_write(A.UC_ARM64_REG_X30, END)
    mu.emu_start(CODE, END)
    return np.frombuffer(bytes(mu.mem_read(OUT, n * OUT_SZ)), dtype=OUT_DT)


def load_cases_lib(path):
    lib = ctypes.CDLL(str(path))
    lib.gen_cases.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
    return lib


class Desc(ctypes.Structure):
    _fields_ = [("seed", ctypes.c_uint64), ("rt", ctypes.c_int8 * 8), ("flags", ctypes.c_uint32)]


def make_cases(lib, seed, rt, flags, n):
    d = Desc(seed, (ctypes.c_int8 * 8)(*rt), flags)
    arr = np.zeros(n, dtype=CASE_DT)
    lib.gen_cases(ctypes.byref(d), arr.ctypes.data, n)
    return arr


# ---- Input types from the instruction text
FPISH = re.compile(r"^(f|scvtf|ucvtf)")
TOK = re.compile(r"\b([vqdshb])(\d+)(?:\.(\d*)([bhsd]))?(\[\d+\])?")
ARR_INT = {"b": T_I8, "h": T_I16, "s": T_I32, "d": T_I64}
ARR_FP = {"b": T_I8, "h": T_F16, "s": T_F32, "d": T_F64}


def reg_types(texts):
    """texts: list (mnemonic, operand text). Type per V register 0..7 (first mention decides, except BITS)."""
    rt = [T_BITS] * 8
    seen = set()
    for mn, ops in texts:
        fp = bool(FPISH.match(mn))
        for idx, m in enumerate(TOK.finditer(ops)):
            kind, num, _cnt, el, lane = m.groups()
            num = int(num)
            if num > 7 or num in seen:
                continue
            first_src = idx >= 1
            if kind == "q":
                t = T_BITS
            else:
                tbl = ARR_FP if fp and not (mn in ("scvtf", "ucvtf") and first_src) else ARR_INT
                e = el if el else kind  # Skalar: Buchstabe des Registers
                t = tbl.get(e, T_BITS)
            rt[num] = t
            seen.add(num)
    return rt
