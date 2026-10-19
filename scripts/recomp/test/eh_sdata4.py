#!/usr/bin/env python3
"""Assembler-Filter für den Exception-Test: schreibt die EH-Kodierungen von sdata8 (0x1c/0x9c) auf sdata4 (0x1b/0x9b).

Eigener Code. Die Gast-ABI der Switch (und damit die libunwind des Spiels) arbeitet mit 32-Bit-Kodierungen; der
lokale Clang schreibt für aarch64-linux 64-Bit-Kodierungen. Gelesen wird Assembler von stdin, geschrieben nach stdout.
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
