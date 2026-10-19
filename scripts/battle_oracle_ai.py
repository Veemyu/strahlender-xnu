#!/usr/bin/env python3
"""Orakel fuer die Gegner-KI (Kampf-Scheibe 6).

Die Trainer-KI (BtlAiBasic, BtlAiStrong, BtlAiExpert, BtlAiDouble, BtlAiAllowance, BtlAiItem, BtlAiPokeChange) ist
kompilierter C#-Code, der seinen Spielzustand ausschliesslich ueber `BattleAiCommand.AI_CMD(clientId, cmd, long[] args)`
abfragt und seine Wertung ueber das Feld `p_Score` (+0x14) veraendert. Dieses Orakel fuehrt die ECHTEN ARM64-Funktionen
aus work/elf/main.patched.elf in Unicorn aus; `AI_CMD` wird durch eine deterministische Pseudo-Welt ersetzt.
Gemessen wird damit die Skriptlogik (Verzweigungen, Argumente, Wertungsaenderung), unabhaengig davon, wie die
130 Abfragebefehle im Spiel berechnet werden.

Pseudo-Welt (identisch in C#, siehe BattleAiScriptOracleTests): Antwort = f(seed, Aufrufnummer, Befehl) mit
SplitMix64; 62,5 % kleine Zahl 0..13, 18,75 % Konstante aus der Liste `big` (alle Zahlen <= 1000 im Funktionstext),
9,4 % 1, 9,4 % 0.

Aufruf:  PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_ai.py [--out DIR] [--cases N] [--only KLASSE ...]
Ausgabe: BattleAiScripts.json (nur Zahlen: Funktionen, Aufrufzaehler, Hash der Aufruffolge, Endwertung) und
         BattleAiDispatch.json (Attacken-KI-Nummer -> Funktion je Skriptklasse) und BattleAiCmdUsage.json.

Scheibe 7 (uebersetzte Skriptklassen, Fixtures je Klasse mit --suffix; Include-Eintraege duerfen Muster enthalten, `name@62=k` legt die KI-Nummer fest):
  --only BtlAiDouble --cases 16 --include scripts/battle_oracle_ai_functions.json --suffix Double
  --only BtlAiExpert --cases 12 --include scripts/battle_oracle_ai_expert_strong.json --suffix Expert
  --only BtlAiStrong --cases 32 --include scripts/battle_oracle_ai_expert_strong.json --suffix StrongFull
  --only BtlAiBasic  --cases 12 --include scripts/battle_oracle_ai_basic_seq.json --suffix BasicSeq
"""
import argparse
import fnmatch
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import battle_oracle as bo  # noqa: E402
import battle_oracle_heap as bh  # noqa: E402

ROOT = bo.ROOT
IMAGE_BASE = bo.IMAGE_BASE
AI_CMD = 0x20ECDB0
DECOMP = ROOT / "work/decomp/battle_all"
CLASSES = ["BtlAiBasic", "BtlAiStrong", "BtlAiExpert", "BtlAiDouble", "BtlAiAllowance", "BtlAiItem", "BtlAiPokeChange"]
MASK = (1 << 64) - 1

BASE_BIG = [15, 16, 17, 18, 20, 25, 26, 27, 31, 38, 40, 48, 57, 65, 67, 69, 100, 104, 106, 120, 126, 135, 150, 200, 255]


def splitmix(x):
    x = (x + 0x9E3779B97F4A7C15) & MASK
    z = x
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
    return z ^ (z >> 31)


def world_answer(seed, call_idx, cmd, big):
    h = splitmix((seed * 0x9E3779B97F4A7C15 + call_idx * 0xD1B54A32D192ED03 + cmd * 0x94D049BB133111EB) & MASK)
    sel = h % 32
    if sel < 20:
        return (h >> 8) % 14
    if sel < 26:
        return big[(h >> 8) % len(big)]
    if sel < 29:
        return 1
    return 0


def fnv(vals, h=0xCBF29CE484222325):
    for v in vals:
        h ^= v & MASK
        h = (h * 0x100000001B3) & MASK
    return h


def split_functions(text):
    out = []
    for p in re.split(r"\n(?=// 0x)", text):
        m = re.match(r"// 0x([0-9a-f]+) (\w+)\$\$(\w+)", p)
        if m:
            out.append((int(m.group(1), 16), m.group(3), p))
    return out


def int_constants(src):
    vals = set()
    for m in re.finditer(r"\b(0x[0-9a-fA-F]+|\d+)\b", src):
        v = int(m.group(1), 0)
        if 2 <= v <= 1000:
            vals.add(v)
    return sorted(vals)


class AiOracle(bh.EventOracle):
    def __init__(self):
        super().__init__()
        self.cmd_log = []
        self.world = None
        self._install_ai_cmd()
        for a in range(0x28F9B70, 0x28F9B70 + 1):  # Platzhalter, nicht benoetigt
            pass
        self.stub(0x352FD8, lambda o, a, b: o.alloc(0x20))   # Boxing fuer Debug-Ausgabe
        for m in bo_script_methods("System.String$$Format"):
            self.stub(m, lambda o, a, b: o.alloc(0x20))
        self.empty_args = self.make_array(8, [])

    def _install_ai_cmd(self):
        from unicorn import UC_HOOK_CODE
        from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_LR, UC_ARM64_REG_PC
        target = AI_CMD - IMAGE_BASE

        def hook(uc, address, size, _user):
            if address != target:
                return
            client = uc.reg_read(UC_ARM64_REG_X0) & 0xFFFFFFFF
            cmd = uc.reg_read(UC_ARM64_REG_X0 + 1) & 0xFF
            arr = uc.reg_read(UC_ARM64_REG_X0 + 2)
            n = struct.unpack("<I", bytes(uc.mem_read(arr + 0x18, 4)))[0] if arr else 0
            args = [struct.unpack("<q", bytes(uc.mem_read(arr + 0x20 + 8 * i, 8)))[0] for i in range(n)] if arr else []
            idx = len(self.cmd_log)
            ans = world_answer(self.world["seed"], idx, cmd, self.world["big"])
            if cmd in self.world.get("override", {}):
                ans = self.world["override"][cmd]
            self.cmd_log.append((cmd, tuple(args), ans))
            uc.reg_write(UC_ARM64_REG_X0, ans & MASK)
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))

        self._u.hook_add(UC_HOOK_CODE, hook, begin=target, end=target)

    def watch_entries(self, addrs):
        """Zeichnet den Eintritt in die gegebenen Funktionen auf (Ghidra-Adresse -> self.entered)."""
        from unicorn import UC_HOOK_CODE
        targets = {a - IMAGE_BASE: a for a in addrs}
        if getattr(self, "_watch_installed", False):
            self._watch_targets.update(targets)
            return
        self._watch_installed = True
        self._watch_targets = dict(targets)
        self.entered = []

        def hook(uc, address, size, _user):
            a = self._watch_targets.get(address)
            if a is not None:
                self.entered.append(a)

        self._u.hook_add(UC_HOOK_CODE, hook, begin=0x1000000, end=0x3000000)

    def prepare_slots(self, src):
        """PTR_DAT-Klassenzeiger, die ueber +0x30 auf statische Felder zeigen (leeres Argument-Array in Slot 0)."""
        for a in sorted({int(m, 16) for m in re.findall(r"\*\(long \*\)PTR_DAT_([0-9a-f]{8})", src)}):
            self._make_static_class(a)

    def _make_static_class(self, ptr_dat):
        key = ("cls", ptr_dat)
        if key in self._made:
            return
        self._made.add(key)
        klass, _statics = self.make_class(ptr_dat, [])
        inner = self.alloc(0x200)
        statics = self.alloc(0x40)
        self.write(statics, struct.pack("<Q", self.empty_args))
        self.write(inner + 0xB8, struct.pack("<Q", statics))
        self.write(inner + 0x12E, struct.pack("<H", 1))
        cell = self.alloc(0x10)
        self.write(cell, struct.pack("<Q", inner))
        self.write(klass + 0x30, struct.pack("<Q", cell))
        self.write(klass + 0xB8, struct.pack("<Q", statics))

    _made = set()


_SM = None


def bo_script_methods(name):
    global _SM
    if _SM is None:
        _SM = json.loads(bo.SCRIPT_JSON.read_text())["ScriptMethod"]
    return [m["Address"] + IMAGE_BASE for m in _SM if m["Name"] == name]


DISPATCHERS = {"BtlAiBasic": [("Calc_BasicAll", "BtlAiBasic")], "BtlAiExpert": [("main_proc", "BtlAiExpert")],
               "BtlAiDouble": [("DoubleAI_Enemy_Main", "BtlAiDouble.Enemy"), ("DoubleAI_Friend_Main", "BtlAiDouble.Friend")]}


def seq_no(name):
    """Skriptnummer aus dem Funktionsnamen (Double: Friend-Funktionen +1000); Hilfsfunktionen ohne Nummer -> None."""
    m = re.search(r"Seq_(\d+)$", name)
    if not m:
        return None
    return int(m.group(1)) + (1000 if "Friend" in name else 0)


def run_function(o, addr, src, name, seed, big, override=None):
    o.cmd_log = []
    o.world = {"seed": seed, "big": big, "override": override or {}}
    obj = o.alloc(0x40)
    o.write(obj + 0x14, struct.pack("<i", 0))
    o.write(obj + 0x18, struct.pack("<I", 1))
    o.write(obj + 0x10, struct.pack("<i", 0))
    mark = o.heap_mark()
    try:
        ret = o.run(addr, obj, max_insns=3_000_000)
        err = None
    except bh.GuestError as e:
        ret, err = 0, str(e)
    score = struct.unpack("<i", o.read(obj + 0x14, 4))[0]
    poke_change = struct.unpack("<i", o.read(obj + 0x10, 4))[0]
    log = list(o.cmd_log)
    o.heap_reset(mark)
    return {"ret": ret & 0xFFFFFFFF, "score": score, "pokeChange": poke_change, "calls": log, "error": err}


def trace_hash(calls):
    vals = []
    for cmd, args, ans in calls:
        vals.append(cmd)
        vals.append(len(args))
        vals.extend(args)
    return fnv(vals)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(bo.DEFAULT_OUT))
    ap.add_argument("--cases", type=int, default=24)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--trace", help="Klasse.Funktion:Seed - Aufruffolge der echten Funktion ausgeben und beenden")
    ap.add_argument("--include", help="JSON {Klasse: [Funktionsname, ...]}: nur diese Funktionen in die Fixture schreiben")
    ap.add_argument("--suffix", help="Dateinamen-Zusatz (z. B. Double -> BattleAiScriptsDouble.json), damit die Fixtures je Skriptklasse getrennt bleiben")
    ns = ap.parse_args(argv)
    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)

    include = json.loads(Path(ns.include).read_text()) if ns.include else None
    o = AiOracle()
    o.populate_method_slots()
    if ns.trace:
        spec, seed = ns.trace.split(":")
        cls, fname = spec.split(".")
        text = (DECOMP / f"Dpr_Battle_Logic_{cls}.c").read_text()
        for addr, name, src in split_functions(text):
            if name == fname:
                o.prepare(src)
                o.prepare_slots(src)
                r = run_function(o, addr, src, name, int(seed), sorted(set(BASE_BIG) | set(int_constants(src))))
                print(" ".join(f"{c}({','.join(map(str, a))})={v}" for c, a, v in r["calls"]), "| score", r["score"], "ret", r["ret"] & 0xFFFFFFFF)
        return 0
    result = {"classes": {}}
    dispatch = {}
    cmd_usage = {}
    for cls in CLASSES:
        if ns.only and cls not in ns.only:
            continue
        text = (DECOMP / f"Dpr_Battle_Logic_{cls}.c").read_text()
        funcs = []
        for addr, name, src in split_functions(text):
            if name == "_cctor":
                # statische Felder der Skriptklasse (z. B. Seitenliste in BtlAiPokeChange) mit dem echten .cctor fuellen
                o.prepare(src)
                o.prepare_slots(src)
                for a in sorted({int(m, 16) for m in re.findall(r"puVar\d = PTR_DAT_([0-9a-f]{8});", src)}):
                    o._make_static_class(a)
                o.run(addr, max_insns=200000)
        expanded = []
        for addr, name, src in split_functions(text):
            if name == "_ctor" or (name == "main" and cls not in ("BtlAiItem", "BtlAiDouble")):
                continue
            if include is None:
                expanded.append((addr, name, src, {}))
                continue
            # Eintrag "name" oder "name@57=0,128=0" (feste Antworten fuer einzelne Befehle, z. B. Einzelkampf ohne G-Modus);
            # derselbe Name darf mehrfach mit verschiedenen Antworten stehen (z. B. Verteiler mit festgelegter KI-Nummer)
            for spec in [e for e in include.get(cls, []) if fnmatch.fnmatchcase(name, e.split("@")[0])]:
                ov = {}
                if "@" in spec:
                    ov = {int(k): int(v) for k, v in (kv.split("=") for kv in spec.split("@")[1].split(","))}
                expanded.append((addr, name, src, ov))
        for addr, name, src, override in expanded:
            returns_void = re.search(r"\n\s*void\s", src[:200]) is not None
            o.prepare(src)
            o.prepare_slots(src)
            big = sorted(set(BASE_BIG) | set(int_constants(src)))
            seq_addrs = {a: n for a, n, _s in split_functions(text) if "Seq" in n}
            o.watch_entries(list(seq_addrs))
            cases = []
            usage = {}
            errors = 0
            for seed in range(1, ns.cases + 1):
                o.entered = []
                r = run_function(o, addr, src, name, seed, big, override)
                entered_seq = next((seq_no(seq_addrs[a]) for a in o.entered if a in seq_addrs and a != addr and seq_no(seq_addrs[a])), 0)
                if r["error"]:
                    errors += 1
                for c, _a, _v in r["calls"]:
                    usage[c] = usage.get(c, 0) + 1
                cases.append([seed, -1 if returns_void else r["ret"] & 1, r["score"], r["pokeChange"], len(r["calls"]), f"{trace_hash(r['calls']):016x}", entered_seq])
            for c, n in usage.items():
                cmd_usage.setdefault(cls, {})[c] = cmd_usage.setdefault(cls, {}).get(c, 0) + n
            entry = {"name": name, "addr": f"{addr:x}", "big": big, "errors": errors, "cases": cases}
            if override:
                entry["override"] = {str(k): v for k, v in override.items()}
            funcs.append(entry)
        result["classes"][cls] = funcs
        for disp, key in DISPATCHERS.get(cls, []):
            by_addr = {a: n for a, n, _s in split_functions(text)}
            daddr = next(a for a, n in by_addr.items() if n == disp)
            o.watch_entries([a for a, n in by_addr.items() if a != daddr])
            table = {}
            for k in range(0, 700):
                for seed in range(1, 25):
                    o.entered = []
                    r = run_function(o, daddr, "", disp, seed, BASE_BIG, {62: k})
                    names = [by_addr[a] for a in o.entered if a in by_addr and "Seq" in by_addr[a]]
                    if names:
                        table[k] = names[0]
                        break
            dispatch[key] = table
        print(cls, len(funcs), "Funktionen,", sum(f["errors"] for f in funcs), "Fehlerlaeufe", file=sys.stderr)
    sfx = ns.suffix or ""
    (out / f"BattleAiScripts{sfx}.json").write_text(json.dumps(result, separators=(",", ":")))
    (out / f"BattleAiDispatch{sfx}.json").write_text(json.dumps(dispatch, sort_keys=True))
    (out / f"BattleAiCmdUsage{sfx}.json").write_text(json.dumps(cmd_usage, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
