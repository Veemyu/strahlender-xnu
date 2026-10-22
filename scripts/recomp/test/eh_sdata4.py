#!/usr/bin/env python3
"""Assembler filter for the exception test: rewrites the EH encodings from sdata8 (0x1c/0x9c) to sdata4 (0x1b/0x9b).

Own code. The Switch guest ABI (and with it the game's libunwind) works with 32-bit encodings; the
local Clang writes 64-bit encodings for aarch64-linux. Assembler is read from stdin, written to stdout.
"""
import re
import sys

for line in sys.stdin:
    line = re.sub(r"(\.cfi_personality\s+)156,", r"\g<1>155,", line)
    line = re.sub(r"(\.cfi_lsda\s+)28,", r"\g<1>27,", line)
    line = re.sub(r"(\.byte\s+)156(\s+//\s*@TType)", r"\g<1>155\2", line)
    line = re.sub(r"\.xword(\s+\.L_ZTI\w+\.DW\.stub-\.Ltmp\d+)", r".word\1", line)
    line = re.sub(r"\.xword(\s+0\s+//\s*TypeInfo)", r".word\1", line)
    sys.stdout.write(line)
