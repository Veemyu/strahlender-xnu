"""Exercise the native engines used by the generator without game data."""

import capstone
import lz4.block
import unicorn
from unicorn import arm64_const
from PIL import Image


def main():
    payload = b"native runtime smoke test" * 8
    packed = lz4.block.compress(payload)
    assert lz4.block.decompress(packed) == payload

    # MOV W0, #7; ADD W0, W0, #5. Exercise both the disassembler and CPU engine.
    instructions = bytes.fromhex("e000805200140011")
    decoder = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    decoded = list(decoder.disasm(instructions, 0x1000))
    assert len(decoded) == 2 and decoded[0].mnemonic == "mov"

    cpu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    cpu.mem_map(0x1000, 0x1000)
    cpu.mem_write(0x1000, instructions)
    cpu.emu_start(0x1000, 0x1008)
    assert cpu.reg_read(arm64_const.UC_ARM64_REG_X0) == 12

    icon = Image.new("RGB", (2, 2), (17, 23, 31))
    assert icon.getpixel((1, 1)) == (17, 23, 31)
    print("Native engines: LZ4, Capstone, Unicorn ARM64 and Pillow OK")


if __name__ == "__main__":
    main()
