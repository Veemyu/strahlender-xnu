#!/usr/bin/env python3
"""Handler-Karte der Kampf-Scheibe 3: Nummer (Tokusei/Item/Waza/Seite/...) -> ADD-Funktion -> Tabelle -> Handler.

Fuehrt die echten .cctor der Handler-Klassen im Unicorn-Orakel aus, liest GET_FUNC_TABLE (Nummer -> HandlerGetFunc) und
ruft jede ADD-Funktion auf; der zurueckgegebene Tabellenzeiger wird mit den statischen HandlerTable_*-Feldern verglichen.
Ausgabe (nur Zahlen/Funktionsnamen, lokal): work/battleevents/handler_map.json
Aufruf: PYTHONPATH=tools/pydeps python3 scripts/battle_handler_map.py
"""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import battle_oracle_heap as bh  # noqa: E402

ROOT = bh.ROOT
OUT = ROOT / "work/battleevents/handler_map.json"
TABLE_FIELD = {"Field": "getHandlerGetFuncTable"}


def read_table(o, arr):
    entries = []
    for i in range(o.read_u32(arr + 0x18)):
        elem = o.u64(arr + 0x20 + 8 * i)
        delegate = o.u64(elem + 0x18)
        method = o.u64(delegate + 0x10) if delegate else 0
        entries.append([o.read_u16(elem + 0x10), o.method_name(method + bh.IMAGE_BASE) if method else None,
                        method + bh.IMAGE_BASE if method else 0])
    return entries


def build_map(o=None):
    o = o or bh.EventOracle()

    def new_array(orc, _klass, length):
        # Struct-Arrays (GET_FUNC_TABLE_ELEM, 16 Byte je Element) brauchen mehr Platz als der Standard-Stub (8 Byte)
        p = orc.alloc(0x20 + 32 * length)
        orc.write(p + 0x18, struct.pack("<I", length))
        return p

    o.stub(0x3AFB00, new_array)
    o.populate_method_slots()
    dump = bh.DumpTypes()
    result = {}
    for cls, (cctor, ptr, type_index) in bh.HANDLER_CLASSES.items():
        fields = dump.fields(cls, type_index)
        # make_class legt nur 0x100 Byte Statics an; die Klassen haben bis zu ~1800 Byte (222 Tabellen)
        klass = o.alloc(0x200)
        statics = o.alloc(0x2000)
        o.write(klass + 0xB8, struct.pack("<Q", statics))
        o.write(o.u64(ptr - bh.IMAGE_BASE), struct.pack("<Q", klass))
        o.run(cctor, max_insns=50_000_000)
        tables = {}
        for name, f in fields.items():
            if f.static and name.startswith("HandlerTable_"):
                arr = o.u64(statics + f.offset)
                if arr:
                    tables[arr] = (name, read_table(o, arr))
        o.prepare(bh.decomp_text(f"Dpr_Battle_Logic_Handler_{cls}.c"))
        gf = fields[TABLE_FIELD.get(cls, "GET_FUNC_TABLE")]
        func_arr = o.u64(statics + gf.offset)
        items = {}
        for i in range(o.read_u32(func_arr + 0x18)):
            base = func_arr + 0x20 + 16 * i
            number = o.read_u32(base)
            delegate = o.u64(base + 8)
            method = o.u64(delegate + 0x10) if delegate else 0
            add_addr = method + bh.IMAGE_BASE if method else 0
            tbl_name, entries = None, []
            if add_addr:
                prio = o.alloc(8)
                try:
                    ret = o.run(add_addr, prio)
                except bh.GuestError:
                    ret = 0
                if ret in tables:
                    tbl_name, entries = tables[ret]
                elif ret:
                    entries = read_table(o, ret)
            items[number] = {"add": o.method_name(add_addr) if add_addr else None, "addAddr": add_addr,
                             "table": tbl_name, "entries": entries}
        result[cls] = items
        print(f"{cls}: {len(items)} Nummern, {sum(1 for v in items.values() if v['table'])} mit Tabelle", file=sys.stderr)
    return result


def main():
    data = build_map()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
