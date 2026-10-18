#!/usr/bin/env python3
"""Messskript für die Machbarkeitsstudie zur statischen Rekompilation (docs/recomp-machbarkeit.md).

Eigener Code. Liest nur lokale Dateien (NSO aus work/exefs, optional ELF) und schreibt Zahlen
nach work/recomp/*.json. Es entstehen keine Binärdaten, keine Disassembly und kein erzeugtes C
im Repo; ausgegeben werden nur Zähler und Mnemonic-Namen.

Unterbefehle:
  nso      Segmentgrößen der NSO-Module (rtld, main, sdk, subsdk0)
  hist     Instruktionsklassen-Histogramm je Modul (capstone, linear über __text__)
  imports  Dynsym-Importe von main nach Namensraum und Anbieter-Modul
  npdm     main.npdm parsen (Header, ACI0, ACID, Kernel-Capabilities, SVC-Maske)
  gensample optional: Stichprobe mit gen.py (Funktionsgenerator): C-Bytes je Instruktion/Funktion
  lifter   optional: LASRecomp-Lifter (nur gelesen, Pfad per --lifter-dir) über den Text laufen
           lassen und zählen, welche Encodings er ablehnt (Unsupported) und wie viel C je
           Instruktion entsteht. Es wird nichts aus research/ kopiert.

capstone liegt unter tools/pydeps (pip install --target tools/pydeps capstone).
Beispiel: python3 scripts/recomp_survey.py hist --module main
"""
import argparse
import json
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "pydeps"))
EXEFS = ROOT / "work" / "exefs"
OUT = ROOT / "work" / "recomp"
MODULES = ("rtld", "main", "sdk", "subsdk0")

DT_NULL, DT_NEEDED, DT_HASH, DT_STRTAB, DT_SYMTAB = 0, 1, 4, 5, 6


# ---------------------------------------------------------------- NSO

class Nso:
    """Minimaler NSO-Leser: Segmente entpacken, MOD0/Dynamic/Dynsym lesen."""

    def __init__(self, path):
        import lz4.block
        raw = Path(path).read_bytes()
        if raw[:4] != b"NSO0":
            raise ValueError(f"{path}: kein NSO")
        flags = struct.unpack_from("<I", raw, 0xC)[0]
        segs = []
        for i in range(3):
            foff, moff, dsize = struct.unpack_from("<III", raw, 0x10 + 16 * i)
            csize = struct.unpack_from("<I", raw, 0x60 + 4 * i)[0]
            data = raw[foff:foff + csize]
            if flags & (1 << i):
                data = lz4.block.decompress(data, uncompressed_size=dsize)
            segs.append((moff, data))
        self.file_size = len(raw)
        self.bss = struct.unpack_from("<I", raw, 0x3C)[0]
        self.seg = {"text": (segs[0][0], len(segs[0][1])),
                    "ro": (segs[1][0], len(segs[1][1])),
                    "data": (segs[2][0], len(segs[2][1]))}
        self.compressed = {k: struct.unpack_from("<I", raw, 0x60 + 4 * i)[0] for i, k in enumerate(("text", "ro", "data"))}
        end = segs[2][0] + len(segs[2][1]) + self.bss
        self.image_size = (end + 0xFFF) & ~0xFFF
        self.image = bytearray(self.image_size)
        for moff, data in segs:
            self.image[moff:moff + len(data)] = data
        self.syms = []
        self.needed = []
        self._dynamic()

    def text_bytes(self):
        off, size = self.seg["text"]
        return bytes(self.image[off:off + size])

    def _u32(self, o):
        return struct.unpack_from("<I", self.image, o)[0]

    def _u64(self, o):
        return struct.unpack_from("<Q", self.image, o)[0]

    def _cstr(self, o):
        e = self.image.index(b"\0", o)
        return self.image[o:e].decode("utf-8", "replace")

    def _dynamic(self):
        mod0 = self._u32(4)
        if self.image[mod0:mod0 + 4] != b"MOD0":
            return
        dyn_off = mod0 + struct.unpack_from("<i", self.image, mod0 + 4)[0]
        dyn, needed, o = {}, [], dyn_off
        while True:
            tag, val = self._u64(o), self._u64(o + 8)
            o += 16
            if tag == DT_NULL:
                break
            if tag == DT_NEEDED:
                needed.append(val)
            dyn.setdefault(tag, val)
        st = dyn.get(DT_STRTAB, 0)
        self.needed = [self._cstr(st + n) for n in needed]
        if DT_HASH in dyn and DT_SYMTAB in dyn:
            nchain = self._u32(dyn[DT_HASH] + 4)
            for i in range(nchain):
                p = dyn[DT_SYMTAB] + 24 * i
                name, info, _o, shndx = struct.unpack_from("<IBBH", self.image, p)
                value, size = struct.unpack_from("<QQ", self.image, p + 8)
                self.syms.append((self._cstr(st + name), info, shndx, value, size))

    def imports(self):
        return [s for s in self.syms if s[0] and s[2] == 0]

    def exports(self):
        return [s for s in self.syms if s[0] and s[2] != 0]


def cmd_nso(args):
    rows = {}
    for m in MODULES:
        n = Nso(EXEFS / m)
        rows[m] = {
            "file_bytes": n.file_size,
            "text": n.seg["text"][1], "ro": n.seg["ro"][1], "data": n.seg["data"][1], "bss": n.bss,
            "text_off": n.seg["text"][0], "ro_off": n.seg["ro"][0], "data_off": n.seg["data"][0],
            "image_bytes": n.image_size,
            "instructions_4B": n.seg["text"][1] // 4,
            "dynsym": len(n.syms), "imports": len(n.imports()), "exports": len(n.exports()),
            "needed": n.needed,
        }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "nso_segments.json").write_text(json.dumps(rows, indent=1))
    print(f"{'Modul':8} {'Datei':>11} {'text':>11} {'ro':>11} {'data':>10} {'bss':>10} {'Image':>11} {'Instr.':>10} {'Imp.':>5} {'Exp.':>5}")
    tot = Counter()
    for m, r in rows.items():
        print(f"{m:8} {r['file_bytes']:>11,} {r['text']:>11,} {r['ro']:>11,} {r['data']:>10,} {r['bss']:>10,} "
              f"{r['image_bytes']:>11,} {r['instructions_4B']:>10,} {r['imports']:>5} {r['exports']:>5}")
        for k in ("file_bytes", "text", "ro", "data", "bss", "image_bytes", "instructions_4B"):
            tot[k] += r[k]
    print(f"{'Summe':8} {tot['file_bytes']:>11,} {tot['text']:>11,} {tot['ro']:>11,} {tot['data']:>10,} {tot['bss']:>10,} "
          f"{tot['image_bytes']:>11,} {tot['instructions_4B']:>10,}")


# ---------------------------------------------------------------- Klassifikation

LSE_PREFIX = ("ldadd", "ldclr", "ldeor", "ldset", "ldsmax", "ldsmin", "ldumax", "ldumin", "swp", "cas",
              "stadd", "stclr", "steor", "stset", "stsmax", "stsmin", "stumax", "stumin")
EXCL = {"ldxr", "ldxrb", "ldxrh", "ldxp", "stxr", "stxrb", "stxrh", "stxp", "ldaxr", "ldaxrb", "ldaxrh",
        "ldaxp", "stlxr", "stlxrb", "stlxrh", "stlxp", "clrex"}
ACQREL = {"ldar", "ldarb", "ldarh", "stlr", "stlrb", "stlrh", "ldlar", "ldlarb", "ldlarh", "stllr", "stllrb",
          "stllrh", "ldapr", "ldaprb", "ldaprh", "ldapur", "ldapurb", "ldapurh", "ldapursb", "ldapursh",
          "ldapursw", "stlur", "stlurb", "stlurh"}
CRYPTO = {"aese", "aesd", "aesmc", "aesimc", "sha1c", "sha1p", "sha1m", "sha1h", "sha1su0", "sha1su1",
          "sha256h", "sha256h2", "sha256su0", "sha256su1", "pmull", "pmull2"}
SYS_BARRIER = {"dmb", "dsb", "isb", "ssbb", "pssbb", "sb", "csdb"}
SYS_OTHER = {"mrs", "msr", "dc", "ic", "tlbi", "at", "sys", "sysl", "svc", "hvc", "smc", "brk", "hlt", "udf",
             "nop", "yield", "wfe", "wfi", "sev", "sevl", "hint", "esb", "dgh", "dcps1", "dcps2", "dcps3",
             "eret", "drps"}
PAC_PREFIX = ("pac", "aut", "xpac", "bti", "retaa", "retab", "braa", "brab", "blraa", "blrab", "ldraa",
              "ldrab", "eretaa", "eretab")
MULDIV = {"mul", "madd", "msub", "mneg", "smull", "umull", "smaddl", "smsubl", "umaddl", "umsubl", "smnegl",
          "umnegl", "smulh", "umulh", "udiv", "sdiv"}
COND = {"csel", "csinc", "csinv", "csneg", "cset", "csetm", "cinc", "cinv", "cneg", "ccmp", "ccmn"}
PCREL = {"adr", "adrp"}
BITMANIP = {"rbit", "rev", "rev16", "rev32", "clz", "cls", "extr", "ror"}

CLASSES = ["Integer (ALU/Move/Bitfeld)", "Integer Mul/Div", "Integer bedingt (CSEL/CCMP)", "PC-relativ (ADR/ADRP)",
           "Load/Store (einzeln, GPR)", "Load/Store Paare (GPR)", "Load-Acquire/Store-Release",
           "Prefetch", "Exklusive (LDXR/STXR/LDAXR/STLXR)", "Atomics/LSE (CAS/SWP/LDADD...)",
           "FP/NEON/SIMD (Rechnen)", "FP/NEON/SIMD Load/Store", "Crypto (AES/SHA/PMULL)", "CRC32",
           "System: MRS/MSR", "System: Barrieren (DMB/DSB/ISB)", "System: DC/IC/SYS/TLBI", "System: SVC/BRK/UDF/HLT",
           "System: NOP/Hints", "PAC/BTI", "Sprung direkt (B/BL/B.cond/CBZ/TBZ)", "Sprung indirekt (BR/BLR)",
           "Return (RET)", "nicht dekodierbar/Daten"]


def classify(mn, w):
    """Klasse einer Instruktion nach Mnemonic (capstone) und Wort w (Encodings nach Arm ARM, Gruppe op0)."""
    if mn.startswith(PAC_PREFIX) and mn not in ("autiasp_",):
        return "PAC/BTI"
    if mn in EXCL:
        return "Exklusive (LDXR/STXR/LDAXR/STLXR)"
    if mn in ACQREL:
        return "Load-Acquire/Store-Release"
    if mn.startswith(LSE_PREFIX):
        return "Atomics/LSE (CAS/SWP/LDADD...)"
    if mn in CRYPTO:
        return "Crypto (AES/SHA/PMULL)"
    if mn.startswith("crc32"):
        return "CRC32"
    if mn == "mrs" or mn == "msr":
        return "System: MRS/MSR"
    if mn in SYS_BARRIER:
        return "System: Barrieren (DMB/DSB/ISB)"
    if mn in ("dc", "ic", "tlbi", "at", "sys", "sysl"):
        return "System: DC/IC/SYS/TLBI"
    if mn in ("svc", "hvc", "smc", "brk", "hlt", "udf", "dcps1", "dcps2", "dcps3", "eret", "drps"):
        return "System: SVC/BRK/UDF/HLT"
    if mn in ("nop", "yield", "wfe", "wfi", "sev", "sevl", "hint", "esb", "dgh"):
        return "System: NOP/Hints"
    if mn == "ret":
        return "Return (RET)"
    if mn in ("br", "blr"):
        return "Sprung indirekt (BR/BLR)"
    if mn in ("b", "bl", "cbz", "cbnz", "tbz", "tbnz") or mn.startswith("b."):
        return "Sprung direkt (B/BL/B.cond/CBZ/TBZ)"
    if mn.startswith("prfm") or mn.startswith("prfum"):
        return "Prefetch"
    op0 = (w >> 25) & 0xF
    if (op0 & 0b0101) == 0b0100:  # Load/Store-Gruppe
        if (w >> 26) & 1:  # V-Bit: FP/SIMD-Register
            return "FP/NEON/SIMD Load/Store"
        if (w >> 27) & 7 == 0b101:
            return "Load/Store Paare (GPR)"
        return "Load/Store (einzeln, GPR)"
    if (op0 & 0b0111) == 0b0111:
        return "FP/NEON/SIMD (Rechnen)"
    if mn in MULDIV:
        return "Integer Mul/Div"
    if mn in COND:
        return "Integer bedingt (CSEL/CCMP)"
    if mn in PCREL:
        return "PC-relativ (ADR/ADRP)"
    return "Integer (ALU/Move/Bitfeld)"


def decode_all(code, base=0):
    """Gibt (Klassenzähler, Mnemonic-Zähler, nicht dekodierbare Wörter) zurück; linear, 4 Byte je Wort."""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    cls, mn_count = Counter(), Counter()
    bad = 0
    nwords = len(code) // 4
    chunk = 1 << 18  # Wörter je Block (1 MiB Maschinencode)
    for start in range(0, nwords, chunk):
        end = min(nwords, start + chunk)
        words = struct.unpack_from(f"<{end - start}I", code, start * 4)
        blk = code[start * 4:end * 4]
        i = 0
        while i < end - start:
            got = 0
            for _a, _s, mn, _ops in md.disasm_lite(blk[i * 4:], base + (start + i) * 4):
                cls[classify(mn, words[i + got])] += 1
                mn_count[mn] += 1
                got += 1
            i += got
            if i < end - start:  # nicht dekodierbares Wort überspringen
                bad += 1
                cls["nicht dekodierbar/Daten"] += 1
                i += 1
    return cls, mn_count, bad


def cmd_hist(args):
    mods = [args.module] if args.module else list(MODULES)
    OUT.mkdir(parents=True, exist_ok=True)
    result = {}
    for m in mods:
        n = Nso(EXEFS / m)
        code = n.text_bytes()
        cls, mnc, bad = decode_all(code)
        total = sum(cls.values())
        result[m] = {"words": len(code) // 4, "classes": dict(cls), "undecodable": bad,
                     "distinct_mnemonics": len(mnc), "mnemonics": dict(mnc.most_common())}
        print(f"\n== {m}: {len(code) // 4:,} Wörter, {len(mnc)} verschiedene Mnemonics, {bad:,} nicht dekodierbar")
        for c in CLASSES:
            v = cls.get(c, 0)
            print(f"  {c:46} {v:>12,}  {100.0 * v / total:6.2f} %")
        (OUT / f"hist_{m}.json").write_text(json.dumps(result[m], indent=1))
    if len(mods) > 1:
        agg = Counter()
        for r in result.values():
            agg.update(r["classes"])
        t = sum(agg.values())
        print(f"\n== Summe aller Module: {t:,} Wörter")
        for c in CLASSES:
            print(f"  {c:46} {agg.get(c, 0):>12,}  {100.0 * agg.get(c, 0) / t:6.2f} %")


# ---------------------------------------------------------------- Importe

NS_RULES = [
    ("nn::* (Nintendo-SDK, _ZN2nn)", re.compile(r"^_ZN2nn|^_ZNK2nn|^_ZNSt3__.*2nn")),
    ("nvn* (NVN-Grafik)", re.compile(r"^nvn|^_ZN3nvn|^__nvn")),
    ("nv/nvdrv/EGL/GLES (Nvidia-Treiber)", re.compile(r"^(nv[A-Z_a-z0-9]*$)|^egl|^gl[A-Z]|^_nv")),
    ("Wwise/AK", re.compile(r"^_ZN2AK|^_ZN\d+AK|^AK|^_ZN\d*Ak|^_ZNK2AK|^_ZN3AKM|^_ZN3AKS")),
    ("Unity-Native (UnityPlayer/il2cpp)", re.compile(r"^il2cpp|^_ZN6il2cpp|^unity|^_ZN5Unity|^UnityPlayer|^_Z\d*Unity|^_ZN\d+il2cpp")),
    ("C++-ABI/Unwind/libcxx (__cxa, std::, _Unwind)", re.compile(r"^__cxa|^_Unwind|^_ZNSt|^_ZSt|^_ZNKSt|^_ZTV|^_ZTI|^_ZTS|^_Zn|^_Zd|^_ZN9__gnu|^__gxx|^__dynamic_cast|^_ZN10__cxxabi|^_ZNK10__cxxabi")),
    ("pthread/Thread/Sync", re.compile(r"^pthread|^sem_|^_pthread|^sched_|^__tls|^__errno|^thrd_|^mtx_|^cnd_|^tss_")),
    ("libc/libm (stdio, string, math, malloc, time)", re.compile(r"^[a-z_][a-z0-9_]*$")),
]


def namespace_of(name):
    for label, rx in NS_RULES:
        if rx.search(name):
            return label
    return "sonstige (mangled C++ / Rest)"


def cmd_imports(args):
    mods = {m: Nso(EXEFS / m) for m in MODULES}
    main = mods["main"]
    imps = main.imports()
    by_ns = Counter(namespace_of(s[0]) for s in imps)
    exporter = {}
    for m, n in mods.items():
        for s in n.exports():
            exporter.setdefault(s[0], m)
    prov = Counter(exporter.get(s[0], "(nicht in NSO-Exporten)") for s in imps)
    both = Counter((namespace_of(s[0]), exporter.get(s[0], "(unaufgelöst)")) for s in imps)
    types = Counter({0: "NOTYPE", 1: "OBJECT", 2: "FUNC"}.get(s[1] & 0xF, str(s[1] & 0xF)) for s in imps)
    # häufigste Top-Level-Namespaces der gemangelten Namen (nur Namen, kein Inhalt)
    top = Counter()
    for s in imps:
        m = re.match(r"^_ZN(?:K)?(\d+)", s[0])
        if m:
            k = int(m.group(1))
            top[s[0][m.end():m.end() + k]] += 1
    # zweite Ebene von nn::<x>:: (nur Namen)
    nn2 = Counter()
    for s in imps:
        m = re.match(r"^_ZN(?:K)?2nn(\d+)", s[0])
        if m:
            k = int(m.group(1))
            nn2[s[0][m.end():m.end() + k]] += 1
    other = sorted(s[0] for s in imps if namespace_of(s[0]).startswith(("sonstige", "nv"))
                   or exporter.get(s[0]) is None)
    out = {
        "nn_second_level": dict(nn2.most_common()), "other_import_names": other,
        "main_dynsym_total": len(main.syms), "main_imports": len(imps), "main_exports": len(main.exports()),
        "needed": main.needed, "by_namespace": dict(by_ns), "by_provider": dict(prov),
        "ns_x_provider": {f"{a} | {b}": c for (a, b), c in both.items()},
        "import_types": dict(types), "top_cxx_namespaces": dict(top.most_common(40)),
    }
    for m, n in mods.items():
        out[f"{m}_syms"] = {"dynsym": len(n.syms), "imports": len(n.imports()), "exports": len(n.exports())}
        out[f"{m}_export_namespaces"] = dict(Counter(namespace_of(s[0]) for s in n.exports()))
        out[f"{m}_import_providers"] = dict(Counter(exporter.get(s[0], "(unaufgelöst)") for s in n.imports()))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "imports.json").write_text(json.dumps(out, indent=1))
    print(f"main: Dynsym {len(main.syms)}, Importe {len(imps)}, Exporte {len(main.exports())}, NEEDED {main.needed}")
    print("\nNach Namensraum:")
    for k, v in by_ns.most_common():
        print(f"  {k:52} {v:>5}")
    print("\nNach Anbieter-Modul:")
    for k, v in prov.most_common():
        print(f"  {k:30} {v:>5}")
    print("\nTop gemangelte Namensräume:", dict(top.most_common(15)))
    for m in ("sdk", "subsdk0", "rtld"):
        print(f"\n{m}: Dynsym {len(mods[m].syms)}, Importe {len(mods[m].imports())}, Exporte {len(mods[m].exports())}")
        print("  Exporte nach Namensraum:", dict(Counter(namespace_of(s[0]) for s in mods[m].exports()).most_common()))
        print("  Importe aufgelöst bei:", dict(Counter(exporter.get(s[0], "(unaufgelöst)") for s in mods[m].imports()).most_common()))


# ---------------------------------------------------------------- NPDM

SVC_NAMES = {
    0x01: "SetHeapSize", 0x02: "SetMemoryPermission", 0x03: "SetMemoryAttribute", 0x04: "MapMemory",
    0x05: "UnmapMemory", 0x06: "QueryMemory", 0x07: "ExitProcess", 0x08: "CreateThread", 0x09: "StartThread",
    0x0A: "ExitThread", 0x0B: "SleepThread", 0x0C: "GetThreadPriority", 0x0D: "SetThreadPriority",
    0x0E: "GetThreadCoreMask", 0x0F: "SetThreadCoreMask", 0x10: "GetCurrentProcessorNumber", 0x11: "SignalEvent",
    0x12: "ClearEvent", 0x13: "MapSharedMemory", 0x14: "UnmapSharedMemory", 0x15: "CreateTransferMemory",
    0x16: "CloseHandle", 0x17: "ResetSignal", 0x18: "WaitSynchronization", 0x19: "CancelSynchronization",
    0x1A: "ArbitrateLock", 0x1B: "ArbitrateUnlock", 0x1C: "WaitProcessWideKeyAtomic",
    0x1D: "SignalProcessWideKey", 0x1E: "GetSystemTick", 0x1F: "ConnectToNamedPort",
    0x20: "SendSyncRequestLight", 0x21: "SendSyncRequest", 0x22: "SendSyncRequestWithUserBuffer",
    0x23: "SendAsyncRequestWithUserBuffer", 0x24: "GetProcessId", 0x25: "GetThreadId", 0x26: "Break",
    0x27: "OutputDebugString", 0x28: "ReturnFromException", 0x29: "GetInfo", 0x2A: "FlushEntireDataCache",
    0x2B: "FlushDataCache", 0x2C: "MapPhysicalMemory", 0x2D: "UnmapPhysicalMemory", 0x2E: "GetDebugFutureThreadInfo",
    0x2F: "GetLastThreadInfo", 0x30: "GetResourceLimitLimitValue", 0x31: "GetResourceLimitCurrentValue",
    0x32: "SetThreadActivity", 0x33: "GetThreadContext3", 0x34: "WaitForAddress", 0x35: "SignalToAddress",
    0x36: "SynchronizePreemptionState", 0x37: "GetResourceLimitPeakValue", 0x3C: "KernelDebug",
    0x3D: "ChangeKernelTraceState", 0x40: "CreateSession", 0x41: "AcceptSession", 0x42: "ReplyAndReceiveLight",
    0x43: "ReplyAndReceive", 0x44: "ReplyAndReceiveWithUserBuffer", 0x45: "CreateEvent", 0x46: "MapIoRegion",
    0x47: "UnmapIoRegion", 0x48: "MapPhysicalMemoryUnsafe", 0x49: "UnmapPhysicalMemoryUnsafe",
    0x4A: "SetUnsafeLimit", 0x4B: "CreateCodeMemory", 0x4C: "ControlCodeMemory", 0x4D: "SleepSystem",
    0x4E: "ReadWriteRegister", 0x4F: "SetProcessActivity", 0x50: "CreateSharedMemory",
    0x51: "MapTransferMemory", 0x52: "UnmapTransferMemory", 0x53: "CreateInterruptEvent",
    0x54: "QueryPhysicalAddress", 0x55: "QueryIoMapping", 0x56: "CreateDeviceAddressSpace",
    0x57: "AttachDeviceAddressSpace", 0x58: "DetachDeviceAddressSpace", 0x59: "MapDeviceAddressSpaceByForce",
    0x5A: "MapDeviceAddressSpaceAligned", 0x5C: "UnmapDeviceAddressSpace", 0x5D: "InvalidateProcessDataCache",
    0x5E: "StoreProcessDataCache", 0x5F: "FlushProcessDataCache",
}
ADDRESS_SPACE = {0: "32 Bit", 1: "64 Bit alt (36 Bit)", 2: "32 Bit ohne Alias", 3: "64 Bit (39 Bit)"}
KC_TYPES = {3: "ThreadInfo", 4: "EnableSystemCalls", 6: "MapIoOrNormalRange", 7: "MapNormalPage",
            11: "EnableInterrupts", 13: "MiscParams", 14: "KernelVersion", 15: "HandleTableSize", 16: "MiscFlags"}


def parse_kc(blob):
    out = {"svc_ids": [], "other": []}
    words = struct.unpack_from(f"<{len(blob) // 4}I", blob)
    i = 0
    while i < len(words):
        w = words[i]
        i += 1
        if w == 0xFFFFFFFF:
            continue
        ones = 0
        while ones < 32 and (w >> ones) & 1:
            ones += 1
        t = KC_TYPES.get(ones, f"unbekannt({ones})")
        if ones == 4:
            mask, idx = (w >> 5) & 0xFFFFFF, w >> 29
            out["svc_ids"] += [idx * 24 + b for b in range(24) if (mask >> b) & 1]
        elif ones == 3:
            out["other"].append({"typ": t, "min_prio": (w >> 4) & 63, "max_prio": (w >> 10) & 63,
                                 "min_core": (w >> 16) & 255, "max_core": (w >> 24) & 255})
        elif ones == 6:  # Paar: zweites Wort folgt
            w2 = words[i] if i < len(words) else 0
            i += 1
            out["other"].append({"typ": t, "begin_roh": (w >> 7) & 0xFFFFFF, "size_roh": (w2 >> 7) & 0xFFFFFF,
                                 "ro": bool((w >> 31) & 1)})
        elif ones == 7:
            out["other"].append({"typ": t, "page": (w >> 8) & 0xFFFFFF})
        elif ones == 11:
            out["other"].append({"typ": t, "irq0": (w >> 12) & 0x3FF, "irq1": (w >> 22) & 0x3FF})
        elif ones == 13:
            out["other"].append({"typ": t, "program_type": (w >> 14) & 7})
        elif ones == 14:
            out["other"].append({"typ": t, "minor": (w >> 15) & 15, "major": (w >> 19) & 0x1FFF})
        elif ones == 15:
            out["other"].append({"typ": t, "handle_table_size": (w >> 16) & 0x3FF})
        elif ones == 16:
            out["other"].append({"typ": t, "enable_debug": bool((w >> 17) & 1), "force_debug": bool((w >> 18) & 1)})
        else:
            out["other"].append({"typ": t, "roh": f"{w:#010x}"})
    return out


def cmd_npdm(args):
    d = Path(args.npdm).read_bytes()
    if d[:4] != b"META":
        raise SystemExit("kein META-Header")
    u32 = lambda o: struct.unpack_from("<I", d, o)[0]
    flags = d[0xC]
    meta = {
        "signature_key_generation": u32(4), "flags_roh": flags, "is_64bit": bool(flags & 1),
        "address_space_type": (flags >> 1) & 7, "address_space": ADDRESS_SPACE.get((flags >> 1) & 7),
        "optimize_memory_allocation": bool(flags & 0x10),
        "main_thread_priority": d[0xE], "default_cpu_id": d[0xF],
        "byte_0x0D": d[0xD], "word_0x10": u32(0x10),
        "system_resource_size": u32(0x14), "version": u32(0x18), "main_thread_stack_size": u32(0x1C),
        "name": d[0x20:0x30].rstrip(b"\0").decode("ascii", "replace"),
        "product_code": d[0x30:0x40].rstrip(b"\0").decode("ascii", "replace"),
        "aci0_off": u32(0x70), "aci0_size": u32(0x74), "acid_off": u32(0x78), "acid_size": u32(0x7C),
    }
    ao = meta["aci0_off"]
    aci = {"magic": d[ao:ao + 4].decode("ascii", "replace"), "title_id": f"{struct.unpack_from('<Q', d, ao + 0x10)[0]:016x}"}
    fac_off, fac_sz, sac_off, sac_sz, kc_off, kc_sz = struct.unpack_from("<6I", d, ao + 0x20)
    aci.update({"fac_size": fac_sz, "sac_size": sac_sz, "kc_size": kc_sz})
    sac = d[ao + sac_off:ao + sac_off + sac_sz]
    services, p = [], 0
    while p < len(sac):  # SAC: Kopfbyte (Bit 7 = Server, niedrige Bits = Länge-1), dann Name
        hb = sac[p]
        ln = (hb & 7) + 1
        services.append((bool(hb & 0x80), sac[p + 1:p + 1 + ln].decode("ascii", "replace")))
        p += 1 + ln
    aci["services_access"] = [s for srv, s in services if not srv]
    aci["services_host"] = [s for srv, s in services if srv]
    kc = parse_kc(d[ao + kc_off:ao + kc_off + kc_sz])
    aci["svc_ids"] = [f"{i:#04x} {SVC_NAMES.get(i, '?')}" for i in sorted(kc["svc_ids"])]
    aci["kernel_caps_other"] = kc["other"]
    do = meta["acid_off"]
    acid = {"magic": d[do + 0x200:do + 0x204].decode("ascii", "replace")}
    acid_flags = u32(do + 0x20C)
    acid.update({"flags_roh": acid_flags, "production": bool(acid_flags & 1), "unqualified_approval": bool(acid_flags & 2),
                 "memory_region": (acid_flags >> 2) & 15,
                 "memory_region_name": {0: "Application", 1: "Applet", 2: "SecureSystem", 3: "NonSecureSystem"}.get((acid_flags >> 2) & 15, "?")})
    acid["title_id_min"] = f"{struct.unpack_from('<Q', d, do + 0x210)[0]:016x}"
    acid["title_id_max"] = f"{struct.unpack_from('<Q', d, do + 0x218)[0]:016x}"
    acid_kc_off, acid_kc_sz = struct.unpack_from("<II", d, do + 0x230)
    acid_kc = parse_kc(d[do + acid_kc_off:do + acid_kc_off + acid_kc_sz])
    acid["svc_count"] = len(acid_kc["svc_ids"])
    res = {"file_bytes": len(d), "meta": meta, "aci0": aci, "acid": acid}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "npdm.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps(res, indent=1, ensure_ascii=False))


# ---------------------------------------------------------------- Lifter-Messung (optional)

def cmd_lifter(args):
    """Lässt den LASRecomp-Lifter (--lifter-dir, nur gelesen) Wort für Wort über den Text laufen."""
    import time
    import capstone
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(args.lifter_dir).resolve()))
    from lifter import Lifter, Unsupported, emit_asm_batch  # noqa: E402

    n = Nso(EXEFS / args.module)
    code = n.text_bytes()
    nwords = len(code) // 4
    stride = max(1, args.stride)
    lf = Lifter(0x7000000000, args.simd)
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    base = 0x7000000000
    kinds = Counter()
    c_bytes = Counter()
    unsupported = Counter()
    unsupported_mn = Counter()
    asm_batch, asm_c = 0, 0
    sample = 0
    t0 = time.time()
    words = struct.unpack(f"<{nwords}I", code)
    batch = []

    def flush():
        nonlocal asm_c, asm_batch
        if batch:
            try:
                asm_c += len(emit_asm_batch(batch)) + 5
                asm_batch += 1
            except Unsupported:
                for a in batch:
                    asm_c += len(emit_asm_batch([a])) + 5
                    asm_batch += 1
            batch.clear()

    i = 0
    while i < nwords:
        w = words[i]
        pc = base + i * 4
        sample += 1
        try:
            ins = lf.lift(w, pc)
        except Unsupported as e:
            key = re.sub(r"[0-9a-f]{8}", "<w>", str(e))
            unsupported[key] += 1
            d = list(md.disasm_lite(struct.pack("<I", w), pc))
            unsupported_mn[d[0][2] if d else "<undecodierbar>"] += 1
            flush()
            kinds["unsupported"] += 1
            c_bytes["unsupported"] += 60
            i += stride
            continue
        kinds[ins.kind] += 1
        if ins.kind == "asm":
            batch.append(ins.asm)
            if len(batch) >= 24:
                flush()
        else:
            flush()
            c_bytes[ins.kind] += len(ins.code) + 5 if ins.kind in ("op", "trap") else 60
        i += stride
    flush()
    res = {
        "module": args.module, "simd": args.simd, "stride": stride, "sampled_words": sample, "text_words": nwords,
        "seconds": round(time.time() - t0, 1), "kinds": dict(kinds), "c_bytes_by_kind": dict(c_bytes),
        "asm_batches": asm_batch, "asm_c_bytes": asm_c,
        "unsupported_reasons": dict(unsupported.most_common()),
        "unsupported_mnemonics": dict(unsupported_mn.most_common()),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"lifter_{args.module}_{args.simd}_s{stride}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


def cmd_eh(args):
    """.eh_frame aus dem NSO lesen: FDE-Zahl und wie viele eine LSDA (C++-Landing-Pads) tragen."""
    n = Nso(EXEFS / args.module)
    img = n.image
    mod0 = struct.unpack_from("<I", img, 4)[0]
    hdr = mod0 + struct.unpack_from("<i", img, mod0 + 16)[0]  # eh_frame_hdr
    ver, ptr_enc, cnt_enc, tbl_enc = img[hdr:hdr + 4]
    eh_ptr = hdr + 4 + struct.unpack_from("<i", img, hdr + 4)[0]  # eh_frame_ptr (pcrel|sdata4)
    cies, fdes, lsda, total_bytes, pers = {}, 0, 0, 0, 0
    off = eh_ptr
    while True:
        ln = struct.unpack_from("<I", img, off)[0]
        if ln == 0:
            break
        body = off + 4
        cid = struct.unpack_from("<I", img, body)[0]
        if cid == 0:  # CIE
            p = body + 4 + 1  # Version
            aug_end = img.index(b"\0", p)
            aug = img[p:aug_end].decode()
            p = aug_end + 1
            for _ in range(2):  # code/data alignment (ULEB/SLEB)
                while img[p] & 0x80:
                    p += 1
                p += 1
            p += 1  # return address register (Version 1)
            fde_enc, lsda_enc, has_pers = 0, 0xFF, False
            if aug.startswith("z"):
                alen = 0
                sh = 0
                while True:
                    b = img[p]
                    p += 1
                    alen |= (b & 0x7F) << sh
                    sh += 7
                    if not b & 0x80:
                        break
                q = p
                for ch in aug[1:]:
                    if ch == "R":
                        fde_enc = img[q]
                        q += 1
                    elif ch == "L":
                        lsda_enc = img[q]
                        q += 1
                    elif ch == "P":
                        has_pers = True
                        e = img[q]
                        q += 1 + {0x00: 8, 0x03: 4, 0x0B: 4, 0x04: 8, 0x0C: 8}.get(e & 0x0F, 4)
            cies[off] = (lsda_enc, has_pers)
        else:
            fdes += 1
            cie = body - cid
            lsda_enc, has_pers = cies.get(cie, (0xFF, False))
            if lsda_enc != 0xFF:
                p = body + 4 + 8  # pc_begin + pc_range (4 Byte je, sdata4)
                alen = 0
                sh = 0
                while True:
                    b = img[p]
                    p += 1
                    alen |= (b & 0x7F) << sh
                    sh += 7
                    if not b & 0x80:
                        break
                if alen and struct.unpack_from("<i", img, p)[0] != 0:
                    lsda += 1
        total_bytes += ln + 4
        off += ln + 4
    res = {"module": args.module, "eh_frame_bytes": total_bytes, "cies": len(cies), "fdes": fdes,
           "fdes_with_lsda": lsda, "personality_cies": sum(1 for v in cies.values() if v[1])}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"eh_{args.module}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


def cmd_svc(args):
    """SVC-Immediates im Text je Modul (SVC = 0xD4000001 | imm16 << 5) gegen NPDM-Maske."""
    res = {}
    for m in MODULES:
        words = struct.unpack("<%dI" % (len(Nso(EXEFS / m).text_bytes()) // 4), Nso(EXEFS / m).text_bytes())
        c = Counter((w >> 5) & 0xFFFF for w in words if (w & 0xFFE0001F) == 0xD4000001)
        res[m] = {f"{k:#04x} {SVC_NAMES.get(k, '?')}": v for k, v in sorted(c.items())}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "svc_used.json").write_text(json.dumps(res, indent=1))
    for m, r in res.items():
        print(m, len(r), "verschiedene SVCs,", sum(r.values()), "Aufrufstellen")
        for k, v in r.items():
            print(f"   {k:44} {v}")


def cmd_gensample(args):
    """Stichprobe mit dem Funktionsgenerator (gen.py aus --lifter-dir, nur gelesen): erzeugtes C je Funktion."""
    import random
    import struct as st
    import time
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(args.lifter_dir).resolve()))
    import gen  # noqa: E402
    gen.PATCHES.clear()  # Patches/Randomizer-Varianten des Zielspiels sind hier ohne Bedeutung
    gen.RANDO_CODE.clear()
    t0 = time.time()
    base = 0x7000000000
    m = gen.Module(args.module, str(EXEFS / args.module), base, args.simd)
    starts = m.boundaries()
    start_set = set(starts)
    n0 = len(start_set)
    for i, w in enumerate(m.words):  # BL-Ziele wie in gen.main
        if (w & 0xFC000000) == 0x94000000:
            t = m.lo + i * 4 + gen.sext26(w) * 4
            if m.in_text(t):
                start_set.add(t)
    order = sorted(start_set)
    ends = {a: (order[i + 1] if i + 1 < len(order) else m.hi) for i, a in enumerate(order)}
    rnd = random.Random(args.seed)
    pick = order if args.functions <= 0 else sorted(rnd.sample(order, min(args.functions, len(order))))
    tot_bytes = tot_ins = nfun = 0
    big = []
    emitted = []
    for a in pick:
        end = ends[a]
        labels, ext, tables = m.scan(a, end)
        lines = m.emit_function(a, end, labels, tables, {})
        size = sum(len(x) + 1 for x in lines)
        if args.emit_dir and size >= args.emit_min_bytes:  # Messdateien nach work/recomp (gitignoriert)
            emitted.append((lines, set(getattr(m, "_refs", set()))))
        tot_bytes += size
        tot_ins += (end - a) // 4
        nfun += 1
        big.append((size, (end - a) // 4))
        m.cache.clear()
    big.sort()
    if args.emit_dir:
        out_dir = Path(args.emit_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        i, chunk = 0, 0
        while i < len(emitted):
            body, refs, size = [], set(), 0
            while i < len(emitted) and size < args.chunk_bytes:
                lines, r = emitted[i]
                body += lines
                refs |= r
                size += sum(len(x) + 1 for x in lines)
                i += 1
            head = '#include "cpu.h"\n' + ('#include "simd.h"\n' if args.simd == "c" else "")
            head += "".join(f"void f_{x:x}(Cpu *c);\n" for x in sorted(refs))
            (out_dir / f"{args.module}_{chunk:03d}.c").write_text(head + "\n".join(body) + "\n")
            chunk += 1
    res = {
        "module": args.module, "simd": args.simd, "seed": args.seed,
        "boundaries_eh_sym_reloc": n0, "boundaries_plus_bl_targets": len(order),
        "sampled_functions": nfun, "sampled_instructions": tot_ins, "sampled_c_bytes": tot_bytes,
        "c_bytes_per_instruction": round(tot_bytes / tot_ins, 2),
        "c_bytes_per_function_mean": round(tot_bytes / nfun, 1),
        "instructions_per_function_mean": round(tot_ins / nfun, 1),
        "c_bytes_per_function_median": big[len(big) // 2][0],
        "c_bytes_per_function_max": big[-1][0],
        "functions_over_100kb": sum(1 for s, _ in big if s > 100000),
        "bytes_in_functions_over_100kb": sum(s for s, _ in big if s > 100000),
        "functions_over_1mb": sum(1 for s, _ in big if s > 1000000),
        "top10_function_sizes": [s for s, _ in big[-10:]],
        "stats": dict(m.stats), "seconds": round(time.time() - t0, 1),
        "extrapolated_c_bytes_whole_text": round(tot_bytes / tot_ins * (m.hi - m.lo) / 4),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"gensample_{args.module}_{args.simd}_{args.seed}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("nso").set_defaults(fn=cmd_nso)
    p = sub.add_parser("hist")
    p.add_argument("--module", choices=MODULES)
    p.set_defaults(fn=cmd_hist)
    sub.add_parser("imports").set_defaults(fn=cmd_imports)
    sub.add_parser("svc").set_defaults(fn=cmd_svc)
    p = sub.add_parser("eh")
    p.add_argument("--module", default="main", choices=MODULES)
    p.set_defaults(fn=cmd_eh)
    p = sub.add_parser("npdm")
    p.add_argument("--npdm", default=str(EXEFS / "main.npdm"))
    p.set_defaults(fn=cmd_npdm)
    p = sub.add_parser("lifter")
    p.add_argument("--lifter-dir", required=True, help="Ordner mit lifter.py (z. B. research/LASRecomp/tools), nur gelesen")
    p.add_argument("--module", default="main", choices=MODULES)
    p.add_argument("--simd", default="asm", choices=("asm", "c"))
    p.add_argument("--stride", type=int, default=1, help="nur jedes n-te Wort lifteten (Stichprobe)")
    p.set_defaults(fn=cmd_lifter)
    p = sub.add_parser("gensample")
    p.add_argument("--lifter-dir", required=True)
    p.add_argument("--module", default="main", choices=MODULES)
    p.add_argument("--simd", default="asm", choices=("asm", "c"))
    p.add_argument("--functions", type=int, default=2000)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--emit-dir", help="Stichproben-C als Chunks hierhin schreiben (nur unter work/recomp)")
    p.add_argument("--chunk-bytes", type=int, default=1500000)
    p.add_argument("--emit-min-bytes", type=int, default=0, help="nur Funktionen mit mindestens so viel C ausgeben")
    p.set_defaults(fn=cmd_gensample)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
