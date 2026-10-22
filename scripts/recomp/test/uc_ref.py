#!/usr/bin/env python3
"""Reference run of the exception test under Unicorn (real ARM64 semantics) for comparison with the recompilation.

Own code. Loads the same images as eh_harness.c (work/recomp/spike2/sdk.img, eht.img), replaces the same
imports/functions with Python hooks (malloc, __cxa_get_globals, GetExceptionInfo, nn::os mutex) and runs
test_basic etc. If this run matches the expected result, the test setup (mini linker,
images, HLE semantics) is correct; deviations of the recompilation are then lifter/generator errors.

Usage: uc_ref.py [--trace]   (requires that run_eh_test.sh was run once)
"""
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "pydeps"))
sys.dont_write_bytecode = True
import unicorn as uc  # noqa: E402
from unicorn import arm64_const as A  # noqa: E402

S = ROOT / "work" / "recomp" / "spike2"
SDK, EHT, STACK, HLE, HEAP, TLS = 0x7004000000, 0x7008000000, 0x7010000000, 0x7080000000, 0x7020000000, 0x7030000000
STACK_SZ = 4 << 20
trace = "--trace" in sys.argv

hle_names = [l for l in (S / "hle.txt").read_text().split("\n") if l]
meta = json.loads((S / "eht.json").read_text())["syms"]
sdk_syms = json.loads((S / "sdk.syms.json").read_text())

mu = uc.Uc(uc.UC_ARCH_ARM64, uc.UC_MODE_ARM)
sdk_img = (S / "sdk.img").read_bytes()
eht_img = (S / "eht.img").read_bytes()
mu.mem_map(SDK, (len(sdk_img) + 0xFFFF) & ~0xFFFF)
mu.mem_write(SDK, sdk_img)
mu.mem_map(EHT, 0x10000)
mu.mem_write(EHT, eht_img)
mu.mem_map(STACK, STACK_SZ)
mu.mem_map(HLE, 0x10000)
mu.mem_map(HEAP, 64 << 20)
mu.mem_map(TLS, 0x10000)
mu.reg_write(A.UC_ARM64_REG_CPACR_EL1, 0x300000)
mu.reg_write(A.UC_ARM64_REG_TPIDRRO_EL0, TLS + 0x100)
mu.reg_write(A.UC_ARM64_REG_TPIDR_EL0, TLS + 0x100)

heap_next = [HEAP + 0x1000]
GLOBALS = TLS + 0x2000
hooks = {}


def _r(n):
    return {29: A.UC_ARM64_REG_X29, 30: A.UC_ARM64_REG_X30}.get(n, A.UC_ARM64_REG_X0 + n)


def reg(n):
    return mu.reg_read(_r(n))


def setreg(n, v):
    mu.reg_write(_r(n), v)


def h_malloc():
    n = reg(0)
    if n > 1 << 40:
        setreg(0, 0)
        return
    a = (heap_next[0] + 15) & ~15
    heap_next[0] = a + max(n, 1)
    setreg(0, a)


def h_calloc():
    n = reg(0) * reg(1)
    a = (heap_next[0] + 15) & ~15
    heap_next[0] = a + max(n, 1)
    setreg(0, a)


def h_free():
    pass


def h_globals():
    setreg(0, GLOBALS)


def h_getexc():
    info, pc = reg(0), reg(1)
    for base, span, img in ((SDK, 13844480, sdk_img), (EHT, 12288, eht_img)):
        if base <= pc < base + span:
            mod0 = struct.unpack_from("<I", img, 4)[0]
            e0, e1 = struct.unpack_from("<ii", img, mod0 + 16)
            mu.mem_write(info, struct.pack("<QQQQ", base, span, mod0 + e0, e1 - e0))
            setreg(0, 1)
            return
    setreg(0, 0)


def h_noop():
    pass


by_name = {"malloc": h_malloc, "calloc": h_calloc, "free": h_free, "realloc": h_malloc, "aligned_alloc": h_malloc}
override = {  # replaced SDK functions (name -> hook); entry is recognized by a code hook
    "__cxa_get_globals": h_globals, "__cxa_get_globals_fast": h_globals,
    "_ZN2nn2ro6detail16GetExceptionInfoEPNS1_13ExceptionInfoEm": h_getexc,
    "_ZN2nn2os9LockMutexEPNS0_9MutexTypeE": h_noop, "_ZN2nn2os11UnlockMutexEPNS0_9MutexTypeE": h_noop,
}
for i, n in enumerate(hle_names):
    if n in by_name:
        hooks[HLE + 16 * i] = by_name[n]
for n, f in override.items():
    hooks[sdk_syms[n]] = f


def code_hook(emu, address, size, user):
    f = hooks.get(address)
    if f:
        f()
        emu.reg_write(A.UC_ARM64_REG_PC, emu.reg_read(A.UC_ARM64_REG_X30))
    elif trace:
        print(f"{address:x}")


def intr_hook(emu, intno, user):
    pc = emu.reg_read(A.UC_ARM64_REG_PC)
    imm = None
    try:
        w = struct.unpack("<I", bytes(emu.mem_read(pc - 4, 4)))[0]
        imm = (w >> 5) & 0xFFFF
    except Exception:
        pass
    if imm == 0x27:
        print("OutputDebugString:", bytes(emu.mem_read(reg(0), reg(1))).decode(errors="replace"))
    else:
        print("SVC", hex(imm or 0), "bei", hex(pc))
    emu.emu_stop()


mu.hook_add(uc.UC_HOOK_CODE, code_hook, begin=SDK, end=SDK + len(sdk_img))
mu.hook_add(uc.UC_HOOK_CODE, code_hook, begin=HLE, end=HLE + 0x10000)
mu.hook_add(uc.UC_HOOK_INTR, intr_hook)

STOP = HLE + 0xFF00


def call(addr, *args):
    for i, a in enumerate(args):
        setreg(i, a)
    mu.reg_write(A.UC_ARM64_REG_SP, STACK + STACK_SZ - 64)
    setreg(30, STOP)
    try:
        mu.emu_start(addr, STOP, count=50_000_000)
    except uc.UcError as e:
        print("Unicorn error:", e, "pc=", hex(mu.reg_read(A.UC_ARM64_REG_PC)))
        return None
    return reg(0)


def rd32(a):
    return struct.unpack("<i", bytes(mu.mem_read(a, 4)))[0]


def main():
    log = STACK + 0x1000
    T = {k: EHT + v for k, v in meta.items() if k.startswith("test_")}
    ok = True
    mu.mem_write(log, struct.pack("<i", 1))
    r = call(T["test_basic"], log, 7, 5, 3)
    exp = 7 + (5 * 7 + 1) + (3 * 5 + 2)
    print(f"T1 (Unicorn) return {r} (expected {exp}), log {rd32(log)} (expected 1234)")
    ok &= r == exp and rd32(log) == 1234
    mu.mem_write(log, struct.pack("<i", 1))
    r = call(T["test_rethrow"], log, 9)
    print(f"T3 (Unicorn) return {r}, log {rd32(log)} (expected 9 / 1256)")
    ok &= r == 9 and rd32(log) == 1256
    print(f"T2 (Unicorn) no throw: return {call(T['test_nothrow'], log)}, log {rd32(log)} (expected 1 / 999992)")
    r = call(T["test_deep"], log, 200, 5)
    print(f"T4 (Unicorn) return {r} (expected 5201)")
    ok &= r == 5201
    if "test_badalloc" in T:
        mu.mem_write(log, struct.pack("<i", 1))
        r = call(T["test_badalloc"], log)
        print(f"T5 (Unicorn) return {r}, log {rd32(log)} (expected 77 / 17)")
        ok &= r == 77 and rd32(log) == 17
    print("RESULT Unicorn:", "all tests passed" if ok else "ERROR")


if __name__ == "__main__":
    main()
