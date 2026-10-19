#!/usr/bin/env python3
"""Phase-2-Spike der Rekompilation: .eh_frame / LSDA (C++-Landing-Pads) eines NSO-Moduls auswerten.

Eigener Code. Liest nur lokale Dateien (work/exefs, NSO) und schreibt Zahlen nach work/recomp/spike2/.
Es werden keine Spielbytes, kein erzeugter Code und keine Adressen in das Repo geschrieben; die Ausgabe
enthält Zähler, Formen von Call-Site-Tabellen und (nur auf der Konsole bzw. unter work/) Moduladressen.

Das Modul stellt auch die Bausteine für den Generator bereit (`eh_gen.py`):
  parse_module(image, eh_hdr_off)  ->  Liste von FDE-Beschreibungen mit LSDA-Call-Sites
  landing_pads(fdes)               ->  {Funktionsanfang: [Landing-Pad-Adressen]}

Unterbefehle:
  survey [--module M]   Zahlen über alle Module (FDEs, LSDA, Call-Sites, Landing-Pads, Aktionsarten)
  sample [--module M]   drei echte Funktionen mit unterschiedlicher Form auswählen und beschreiben
"""
import argparse
import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "pydeps"))
OUT = ROOT / "work" / "recomp" / "spike2"
EXEFS = ROOT / "work" / "exefs"
MODULES = ("rtld", "main", "sdk", "subsdk0")

DW_EH_PE_omit = 0xFF


def uleb(img, p):
    v = sh = 0
    while True:
        b = img[p]
        p += 1
        v |= (b & 0x7F) << sh
        sh += 7
        if not b & 0x80:
            return v, p


def sleb(img, p):
    v = sh = 0
    while True:
        b = img[p]
        p += 1
        v |= (b & 0x7F) << sh
        sh += 7
        if not b & 0x80:
            if b & 0x40:
                v -= 1 << sh
            return v, p


def read_enc(img, p, enc):
    """DWARF-EH-Zeigerkodierung lesen: (Wert, nächste Position). pcrel ist relativ zur Lesestelle (Basis 0)."""
    if enc == DW_EH_PE_omit:
        return None, p
    fmt, app = enc & 0x0F, enc & 0x70
    q = p
    if fmt == 0x00:
        v, p = struct.unpack_from("<Q", img, p)[0], p + 8
    elif fmt == 0x01:
        v, p = uleb(img, p)
    elif fmt == 0x02:
        v, p = struct.unpack_from("<H", img, p)[0], p + 2
    elif fmt == 0x03:
        v, p = struct.unpack_from("<I", img, p)[0], p + 4
    elif fmt == 0x04:
        v, p = struct.unpack_from("<Q", img, p)[0], p + 8
    elif fmt == 0x09:
        v, p = sleb(img, p)
    elif fmt == 0x0A:
        v, p = struct.unpack_from("<h", img, p)[0], p + 2
    elif fmt == 0x0B:
        v, p = struct.unpack_from("<i", img, p)[0], p + 4
    elif fmt == 0x0C:
        v, p = struct.unpack_from("<q", img, p)[0], p + 8
    else:
        raise ValueError(f"Kodierung {enc:#x}")
    if app == 0x10:
        v += q
    return v, p


class Cie:
    __slots__ = ("fde_enc", "lsda_enc", "pers", "signal")


def parse_cie(img, off):
    c = Cie()
    body = off + 4
    p = body + 4 + 1
    e = img.index(b"\0", p)
    aug = bytes(img[p:e]).decode()
    p = e + 1
    _, p = uleb(img, p)
    _, p = sleb(img, p)
    p += 1
    c.fde_enc, c.lsda_enc, c.pers, c.signal = 0, DW_EH_PE_omit, False, False
    if aug.startswith("z"):
        alen, p = uleb(img, p)
        q = p
        for ch in aug[1:]:
            if ch == "R":
                c.fde_enc = img[q]
                q += 1
            elif ch == "L":
                c.lsda_enc = img[q]
                q += 1
            elif ch == "P":
                enc = img[q]
                q += 1
                _, q = read_enc(img, q, enc & 0x7F)
                c.pers = True
            elif ch == "S":
                c.signal = True
    return c


def parse_lsda(img, p):
    """LSDA lesen. Rückgabe: dict mit Call-Sites [(start, len, lp, action)], Aktionen, Typtabelle."""
    lp_enc = img[p]
    p += 1
    lpstart = None
    if lp_enc != DW_EH_PE_omit:
        lpstart, p = read_enc(img, p, lp_enc)
    tt_enc = img[p]
    p += 1
    tt_end = None
    if tt_enc != DW_EH_PE_omit:
        off, p = uleb(img, p)
        tt_end = p + off
    cs_enc = img[p]
    p += 1
    cs_len, p = uleb(img, p)
    cs_end = p + cs_len
    sites = []
    while p < cs_end:
        start, p = read_enc(img, p, cs_enc)
        ln, p = read_enc(img, p, cs_enc)
        lp, p = read_enc(img, p, cs_enc)
        act, p = uleb(img, p)
        sites.append((start, ln, lp, act))
    # Aktionstabelle: ab cs_end bis zur Typtabelle (Einträge: filter SLEB, next SLEB; Verweis = 1-basiert in Bytes)
    actions = {}
    act_base = cs_end
    q = act_base
    limit = (tt_end - 0) if tt_end else q
    # Die Typtabelle liegt rückwärts vor tt_end; die Aktionstabelle endet dort, wo sie beginnt. Wir lesen
    # Aktionen nur bei Bedarf über die Verkettung der Call-Sites ab (siehe action_chain).
    return {"lpstart": lpstart, "tt_enc": tt_enc, "tt_end": tt_end, "sites": sites, "act_base": act_base,
            "cs_enc": cs_enc, "end_cs": cs_end}


def action_chain(img, lsda, act):
    """Aktionskette ab Verweis `act` (1-basiert in die Aktionstabelle). -> Liste von Filtern (SLEB)."""
    out, off = [], act
    guard = 0
    while off and guard < 64:
        p = lsda["act_base"] + off - 1
        flt, p2 = sleb(img, p)
        nxt, _ = sleb(img, p2)
        out.append(flt)
        if nxt == 0:
            break
        off = off + (p2 - p) + nxt
        guard += 1
    return out


def type_entry(img, lsda, flt):
    """Typtabelleneintrag für Filter > 0: Zeigerwert oder 0 (= catch(...))."""
    enc = lsda["tt_enc"]
    sizes = {0x00: 8, 0x03: 4, 0x0B: 4, 0x04: 8, 0x0C: 8, 0x02: 2, 0x0A: 2}
    sz = sizes.get(enc & 0x0F, 4)
    p = lsda["tt_end"] - flt * sz
    v, _ = read_enc(img, p, enc & 0x0F)  # Rohwert: 0 heißt catch(...)
    return v


def parse_module(img, hdr_off):
    """Alle FDEs aus .eh_frame_hdr: Liste von dicts (start, size, lsda, sites, cie-Infos)."""
    ver, ptr_enc, cnt_enc, tbl_enc = img[hdr_off:hdr_off + 4]
    p = hdr_off + 4
    _, p = read_enc(img, p, ptr_enc)
    count, p = read_enc(img, p, cnt_enc)
    cies, fdes = {}, []
    for i in range(count):
        loc, p = read_enc(img, p, tbl_enc & 0x0F)
        fde_off, p = read_enc(img, p, tbl_enc & 0x0F)
        if (tbl_enc & 0x70) == 0x30:  # datarel: relativ zum Beginn der Hdr
            loc += hdr_off
            fde_off += hdr_off
        ln = struct.unpack_from("<I", img, fde_off)[0]
        body = fde_off + 4
        cid = struct.unpack_from("<I", img, body)[0]
        cie_off = body - cid
        cie = cies.get(cie_off)
        if cie is None:
            cie = cies[cie_off] = parse_cie(img, cie_off)
        q = body + 4
        start, q = read_enc(img, q, cie.fde_enc)
        size, q = read_enc(img, q, cie.fde_enc & 0x0F)
        lsda_ptr = None
        alen, q = uleb(img, q)
        ins_start = q + alen
        if cie.lsda_enc != DW_EH_PE_omit and alen:
            v, _ = read_enc(img, q, cie.lsda_enc)
            lsda_ptr = v if v else None
        f = {"start": start, "size": size, "lsda": lsda_ptr, "pers": cie.pers, "sites": [], "lsda_info": None,
             "ins": (ins_start, body + ln)}
        if lsda_ptr:
            info = parse_lsda(img, lsda_ptr)
            f["lsda_info"] = info
            lps = info["lpstart"] if info["lpstart"] is not None else start
            for (s, l, lp, a) in info["sites"]:
                f["sites"].append((start + s if info["lpstart"] is None else lps + s, l, (lps + lp) if lp else 0, a))
        fdes.append(f)
    return fdes


def landing_pads(fdes):
    """{Funktionsanfang: sortierte Liste der Landing-Pad-Adressen}."""
    res = {}
    for f in fdes:
        lps = sorted({lp for (_, _, lp, _) in f["sites"] if lp})
        if lps:
            res[f["start"]] = lps
    return res


def load_module(name):
    from importlib import import_module
    sys.path.insert(0, str(ROOT / "scripts"))
    rs = import_module("recomp_survey")
    n = rs.Nso(EXEFS / name)
    img = n.image
    mod0 = struct.unpack_from("<I", img, 4)[0]
    hdr = mod0 + struct.unpack_from("<i", img, mod0 + 16)[0]
    return n, img, hdr


def classify(img, f):
    """Aktionsarten der Call-Sites: cleanup, catch(typed), catch(...), exception-spec, noexcept-terminate."""
    info = f["lsda_info"]
    kinds = Counter()
    for (_, _, _, act), (s, l, lp, a) in zip(info["sites"], f["sites"]):
        if not lp and not a:
            kinds["no_handler"] += 1
        elif not lp:
            kinds["terminate"] += 1
        elif a == 0:
            kinds["cleanup"] += 1
        else:
            chain = action_chain(img, info, a)
            for flt in chain:
                if flt == 0:
                    kinds["cleanup_in_chain"] += 1
                elif flt > 0:
                    tv = type_entry(img, info, flt) if info["tt_end"] else 0
                    kinds["catch_all" if not tv else "catch_typed"] += 1
                else:
                    kinds["exc_spec"] += 1
    return kinds


def cmd_survey(args):
    res = {}
    for name in ([args.module] if args.module else MODULES):
        n, img, hdr = load_module(name)
        fdes = parse_module(img, hdr)
        with_l = [f for f in fdes if f["lsda"]]
        kinds, sites, lp_total, lp_fn = Counter(), 0, 0, 0
        max_sites = 0
        per_fn_lp = []
        for f in with_l:
            k = classify(img, f)
            kinds.update(k)
            sites += len(f["sites"])
            lps = {lp for (_, _, lp, _) in f["sites"] if lp}
            lp_total += len(lps)
            if lps:
                lp_fn += 1
                per_fn_lp.append(len(lps))
            max_sites = max(max_sites, len(f["sites"]))
        per_fn_lp.sort()
        res[name] = {
            "fdes": len(fdes), "fdes_with_lsda": len(with_l), "functions_with_landing_pads": lp_fn,
            "call_sites": sites, "landing_pads": lp_total, "max_call_sites_one_function": max_sites,
            "landing_pads_per_function_median": per_fn_lp[len(per_fn_lp) // 2] if per_fn_lp else 0,
            "landing_pads_per_function_max": per_fn_lp[-1] if per_fn_lp else 0,
            "action_kinds": dict(kinds),
            "fdes_with_personality_cie": sum(1 for f in fdes if f["pers"]),
            "function_size_bytes_of_lsda_functions": sum(f["size"] for f in with_l),
        }
        print(name, json.dumps(res[name]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ("eh_survey_%s.json" % (args.module or "all"))).write_text(json.dumps(res, indent=1))


def cfa_census(img, fdes):
    """Zählt die DWARF-CFA-Befehle in den FDE-Programmen (Operandenlängen nach DWARF 5 / GNU-Erweiterungen)."""
    names = {0x00: "nop", 0x01: "set_loc", 0x02: "advance_loc1", 0x03: "advance_loc2", 0x04: "advance_loc4",
             0x05: "offset_extended", 0x06: "restore_extended", 0x07: "undefined", 0x08: "same_value",
             0x09: "register", 0x0A: "remember_state", 0x0B: "restore_state", 0x0C: "def_cfa",
             0x0D: "def_cfa_register", 0x0E: "def_cfa_offset", 0x0F: "def_cfa_expression", 0x10: "expression",
             0x11: "offset_extended_sf", 0x12: "def_cfa_sf", 0x13: "def_cfa_offset_sf", 0x14: "val_offset",
             0x15: "val_offset_sf", 0x16: "val_expression", 0x2D: "aarch64_negate_ra_state", 0x2E: "gnu_args_size",
             0x2F: "gnu_negative_offset_extended"}
    cnt, fde_with = Counter(), Counter()
    for f in fdes:
        p, end = f["ins"]
        seen = set()
        while p < end:
            op = img[p]
            p += 1
            hi = op & 0xC0
            if hi:
                nm = {0x40: "advance_loc", 0x80: "offset", 0xC0: "restore"}[hi]
                if hi == 0x80:
                    _, p = uleb(img, p)
            else:
                nm = names.get(op, f"unbekannt_{op:#x}")
                if op in (0x05, 0x09, 0x0C, 0x11, 0x14):
                    _, p = uleb(img, p)
                    _, p = (sleb if op in (0x11,) else uleb)(img, p)
                elif op in (0x06, 0x07, 0x08, 0x0D, 0x0E, 0x2E):
                    _, p = uleb(img, p)
                elif op in (0x12, 0x15):
                    _, p = uleb(img, p)
                    _, p = sleb(img, p)
                elif op == 0x13:
                    _, p = sleb(img, p)
                elif op == 0x2F:
                    _, p = uleb(img, p)
                    _, p = uleb(img, p)
                elif op == 0x02:
                    p += 1
                elif op == 0x03:
                    p += 2
                elif op == 0x04:
                    p += 4
                elif op == 0x01:
                    p += 4
                elif op == 0x0F:
                    n, p = uleb(img, p)
                    p += n
                elif op == 0x10 or op == 0x16:
                    _, p = uleb(img, p)
                    n, p = uleb(img, p)
                    p += n
                elif op not in names:
                    break
            cnt[nm] += 1
            seen.add(nm)
        for nm in seen:
            fde_with[nm] += 1
    return cnt, fde_with


def cmd_cfa(args):
    res = {}
    for name in ([args.module] if args.module else MODULES):
        n, img, hdr = load_module(name)
        fdes = parse_module(img, hdr)
        cnt, fw = cfa_census(img, fdes)
        res[name] = {"fdes": len(fdes), "opcodes": dict(cnt.most_common()), "fdes_containing_opcode": dict(fw.most_common())}
        rare = {k: v for k, v in fw.items() if k in ("remember_state", "restore_state", "def_cfa_expression",
                                                     "expression", "val_expression", "aarch64_negate_ra_state")
                or k.startswith("unbekannt")}
        print(name, "FDEs", len(fdes), "seltene/kritische Befehle (FDEs mit Befehl):", rare)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "eh_cfa_census.json").write_text(json.dumps(res, indent=1))


def cmd_sample(args):
    """Drei echte LSDA-Funktionen (Stichprobe: nur Kennzahlen, keine Adressen im Repo)."""
    n, img, hdr = load_module(args.module)
    fdes = parse_module(img, hdr)
    cand = {"cleanup_only": None, "catch_typed": None, "catch_all": None}
    for f in fdes:
        if not f["lsda"] or not 3 <= len(f["sites"]) <= 40:
            continue
        k = classify(img, f)
        if f["size"] > 4096:
            continue
        if k.get("catch_typed") and not k.get("catch_all") and cand["catch_typed"] is None:
            cand["catch_typed"] = f
        elif k.get("catch_all") and cand["catch_all"] is None:
            cand["catch_all"] = f
        elif k.get("cleanup") and not (k.get("catch_typed") or k.get("catch_all")) and cand["cleanup_only"] is None:
            cand["cleanup_only"] = f
        if all(cand.values()):
            break
    out = {}
    for key, f in cand.items():
        if not f:
            continue
        k = classify(img, f)
        lps = sorted({lp for (_, _, lp, _) in f["sites"] if lp})
        out[key] = {"start": hex(f["start"]), "bytes": f["size"], "instructions": f["size"] // 4,
                    "call_sites": len(f["sites"]), "landing_pads": len(lps), "kinds": dict(k),
                    "lp_offsets_in_function": [lp - f["start"] for lp in lps]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"eh_sample_{args.module}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nm, fn in (("survey", cmd_survey), ("sample", cmd_sample), ("cfa", cmd_cfa)):
        p = sub.add_parser(nm)
        p.add_argument("--module", choices=MODULES, default="main" if nm == "sample" else None)
        p.set_defaults(fn=fn)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
