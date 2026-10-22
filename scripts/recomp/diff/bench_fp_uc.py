#!/usr/bin/env python3
"""Reference for the float benchmark: runs bench_float from the aarch64 image under Unicorn (real ARM64 semantics)
and prints the result (D0 bits) and the hash of the buffer. Own code. Usage: bench_fp_uc.py <image> <offset-hex> <n>"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "pydeps"))
sys.dont_write_bytecode = True
import unicorn as uc  # noqa: E402
from unicorn import arm64_const as A  # noqa: E402

img = Path(sys.argv[1]).read_bytes()
off, n = int(sys.argv[2], 16), int(sys.argv[3])
GBASE, STACK, SSIZE = 0x7008000000, 0x7010000000, 1 << 20
mu = uc.Uc(uc.UC_ARCH_ARM64, uc.UC_MODE_ARM)
mu.ctl_set_cpu_model(A.UC_CPU_ARM64_A57)
mu.mem_map(GBASE, 0x10000)
mu.mem_write(GBASE, img[:0x10000])
mu.mem_map(STACK, SSIZE)
buf = STACK + 0x10000
mu.mem_write(buf, struct.pack("<1024d", *[i * 0.001 for i in range(1024)]))
mu.reg_write(A.UC_ARM64_REG_CPACR_EL1, 0x300000)
mu.reg_write(A.UC_ARM64_REG_X0, buf)
mu.reg_write(A.UC_ARM64_REG_X1, n)
mu.reg_write(A.UC_ARM64_REG_SP, STACK + SSIZE - 64)
mu.reg_write(A.UC_ARM64_REG_X30, 0x7000000000)
mu.emu_start(GBASE + off, 0x7000000000)
d0 = mu.reg_read(A.UC_ARM64_REG_D0)
h = 1469598103934665603
for u in struct.unpack("<1024Q", bytes(mu.mem_read(buf, 8192))):
    h = ((h ^ u) * 1099511628211) & (2**64 - 1)
print(f"UNI {d0:016x} {h:016x}")
