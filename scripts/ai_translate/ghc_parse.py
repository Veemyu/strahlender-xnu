#!/usr/bin/env python3
"""Ghidra-Pseudocode der BtlAi*-Skriptfunktionen -> AST + Vereinfachung (Teil 1 von scripts/ai_translate).

Liest nur Pseudocode (work/decomp/battle_all, nicht im Repo). Die Skripte sind in C# uebersetzter Code, dessen Pseudocode von IL2CPP-Rauschen
umgeben ist: Klassen-Initialisierung, Debug-Ausgaben (PRINTF), Grenzpruefungen der Argument-Arrays (-> Fehlersprung), Array-Allokation je Befehl.
Dieses Modul parst den Pseudocode (Teilmenge von C), entfernt das Rauschen und verschmilzt `new long[n]` + Stores + Aufruf zu `C(cmd, n, ...)`.
"""
import re

KEYW_TYPES = {"undefined8": "ulong", "undefined4": "uint", "undefined2": "ushort", "undefined1": "byte", "undefined": "byte",
              "ulong": "ulong", "long": "long", "int": "int", "uint": "uint", "ushort": "ushort", "byte": "byte", "bool": "bool",
              "short": "short", "char": "sbyte", "void": "void", "float": "float", "double": "double"}
TOK = re.compile(r"\s*(?:(0x[0-9a-fA-F]+[uUlL]*|\d+[uUlL]*)|([A-Za-z_][A-Za-z_0-9]*)|(<<=|>>=|<<|>>|<=|>=|==|!=|&&|\|\||->|\+\+|--|[-+*/%&|^]=|[-+*/%&|^~!<>=?:;,(){}\[\].]))")
JUNK_NAMES = {"thunk_FUN_00364fe0", "FUN_00359b58", "FUN_003afbe0", "thunk_FUN_00352fd8", "thunk_FUN_003ab52c", "FUN_003afc10"}


class Err(Exception):
    pass


def tokenize(s):
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    s = re.sub(r"//[^\n]*", " ", s)
    toks, pos = [], 0
    while pos < len(s):
        if s[pos:].strip() == "":
            break
        m = TOK.match(s, pos)
        if not m:
            raise Err("Token bei " + s[pos:pos + 30])
        pos = m.end()
        toks.append(("num", m.group(1)) if m.group(1) else ("id", m.group(2)) if m.group(2) else ("op", m.group(3)))
    return toks


class Parser:
    BIN = [["||"], ["&&"], ["|"], ["^"], ["&"], ["==", "!="], ["<", ">", "<=", ">="], ["<<", ">>"], ["+", "-"], ["*", "/", "%"]]
    ASSIGN = ("=", "+=", "-=", "|=", "&=", "^=", "<<=", ">>=", "*=", "/=", "%=")

    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else ("eof", "")

    def next(self):
        v = self.peek()
        self.i += 1
        return v

    def accept(self, op):
        if self.peek() == ("op", op):
            self.i += 1
            return True
        return False

    def expect(self, op):
        if not self.accept(op):
            raise Err(f"erwartet {op}, gefunden {self.peek()} bei: " + " ".join(v for _, v in self.t[max(0, self.i - 8):self.i + 4]))

    def parse_type(self):
        name, stars = self.next()[1], 0
        while self.accept("*"):
            stars += 1
        return name, stars

    def expr(self):
        e = self.assign()
        if self.peek() == ("op", ","):
            items = [e]
            while self.accept(","):
                items.append(self.assign())
            return ("comma", items)
        return e

    def assign(self):
        lhs = self.ternary()
        t = self.peek()
        if t[0] == "op" and t[1] in self.ASSIGN:
            self.next()
            return ("assign", t[1], lhs, self.assign())
        return lhs

    def ternary(self):
        c = self.binary(0)
        if self.accept("?"):
            a = self.assign()
            self.expect(":")
            return ("tern", c, a, self.assign())
        return c

    def binary(self, lvl):
        if lvl >= len(self.BIN):
            return self.unary()
        e = self.binary(lvl + 1)
        while self.peek()[0] == "op" and self.peek()[1] in self.BIN[lvl]:
            op = self.next()[1]
            e = ("bin", op, e, self.binary(lvl + 1))
        return e

    def unary(self):
        t = self.peek()
        if t[0] == "op" and t[1] in ("!", "-", "~", "*", "&", "+"):
            self.next()
            return ("un", t[1], self.unary())
        if t == ("op", "(") and self.peek(1)[0] == "id" and self.peek(1)[1] in KEYW_TYPES:
            save = self.i
            self.next()
            ty = self.parse_type()
            if self.accept(")"):
                return ("cast", ty, self.unary())
            self.i = save
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while True:
            if self.accept("("):
                args = []
                if not self.accept(")"):
                    args.append(self.assign())
                    while self.accept(","):
                        args.append(self.assign())
                    self.expect(")")
                e = ("call", e, args)
            elif self.accept("["):
                i = self.expr()
                self.expect("]")
                e = ("idx", e, i)
            else:
                return e

    def primary(self):
        t = self.next()
        if t[0] in ("num", "id"):
            return (t[0], t[1])
        if t == ("op", "("):
            e = self.expr()
            self.expect(")")
            return ("paren", e)
        raise Err(f"unerwartet {t}")

    def block(self):
        self.expect("{")
        out = []
        while not self.accept("}"):
            out.extend(self.stmt())
        return out

    def stmt(self):
        t = self.peek()
        if t == ("op", "{"):
            return self.block()
        if t == ("op", ";"):
            self.next()
            return []
        if t[0] == "id":
            if t[1] == "if":
                self.next()
                self.expect("(")
                c = self.expr()
                self.expect(")")
                th = self.stmt()
                el = None
                if self.peek() == ("id", "else"):
                    self.next()
                    el = self.stmt()
                return [("if", c, th, el)]
            if t[1] == "goto":
                self.next()
                lab = self.next()[1]
                self.expect(";")
                return [("goto", lab)]
            if t[1] == "return":
                self.next()
                if self.accept(";"):
                    return [("return", None)]
                e = self.expr()
                self.expect(";")
                return [("return", e)]
            if t[1] == "break":
                self.next()
                self.expect(";")
                return [("break",)]
            if t[1] == "switch":
                self.next()
                self.expect("(")
                e = self.expr()
                self.expect(")")
                return [("switch", e, self.block_switch())]
            if self.peek(1) == ("op", ":"):
                self.next()
                self.next()
                return [("label", t[1])]
            if t[1] in KEYW_TYPES:
                save = self.i
                ty = self.parse_type()
                if self.peek()[0] == "id" and self.peek(1) == ("op", ";"):
                    name = self.next()[1]
                    self.next()
                    return [("decl", ty, name)]
                self.i = save
        e = self.expr()
        self.expect(";")
        return [("expr", e)]

    def block_switch(self):
        self.expect("{")
        out = []
        while not self.accept("}"):
            t = self.peek()
            if t == ("id", "case"):
                self.next()
                v = self.next()[1]
                self.expect(":")
                out.append(("case", int(v.rstrip("uUlL"), 0)))
            elif t == ("id", "default"):
                self.next()
                self.expect(":")
                out.append(("default",))
            else:
                out.extend(self.stmt())
        return out


def parse_function(text):
    m = re.search(r"^// 0x([0-9a-f]+) \S+\$\$(\S+)", text, re.M)
    hdr = re.search(r"\n(\w+(?: \*)?) +\S+__(\w+)\(([^)]*)\)\s*\n", text)
    if not m or not hdr:
        raise Err("Kopf nicht gefunden")
    stmts = Parser(tokenize(text[hdr.end():])).block()
    return {"name": m.group(2), "addr": m.group(1), "ret": hdr.group(1), "params": hdr.group(3), "body": stmts}


def walk_expr(e, f):
    f(e)
    if not isinstance(e, tuple):
        return
    k = e[0]
    kids = {"bin": e[2:4], "un": e[2:3], "cast": e[2:3], "paren": e[1:2], "idx": e[1:3], "assign": e[2:4], "tern": e[1:4]}.get(k)
    if k == "call":
        kids = [e[1]] + list(e[2])
    elif k == "comma":
        kids = e[1]
    for a in kids or []:
        walk_expr(a, f)


def ids_of(e):
    out = []
    walk_expr(e, lambda x: out.append(x[1]) if isinstance(x, tuple) and x[0] == "id" else None)
    return out


def calls_of(e):
    out = []
    walk_expr(e, lambda x: out.append(x[1][1]) if isinstance(x, tuple) and x[0] == "call" and x[1][0] == "id" else None)
    return out


def strip_paren(e):
    while isinstance(e, tuple) and e[0] == "paren":
        e = e[1]
    return e


def is_junk_call_name(n):
    return n.endswith("PRINTF") or n in JUNK_NAMES or "String__Format" in n


def is_err_call_name(n):
    return n.startswith("thunk_FUN_0035c") or n.startswith("FUN_003afbc0")


def const_int(e):
    e = strip_paren(e)
    if e[0] == "num":
        return int(e[1].rstrip("uUlL"), 0)
    raise Err("keine Konstante: " + repr(e)[:80])


def add_const(e, off):
    e = strip_paren(e)
    return e[0] == "bin" and e[1] == "+" and strip_paren(e[3])[0] == "num" and const_int(e[3]) == off


def is_empty_expr(e):
    # **(T **)(X + 0xb8): statisches leeres Argument-Array
    e = strip_paren(e)
    if e[0] == "cast":
        e = strip_paren(e[2])
    if e[0] != "un" or e[1] != "*":
        return False
    inner = strip_paren(e[2])
    if inner[0] == "un" and inner[1] == "*":
        inner = strip_paren(inner[2])
        if inner[0] == "cast":
            inner = strip_paren(inner[2])
        return add_const(inner, 0xb8)
    if inner[0] == "cast":
        i2 = strip_paren(inner[2])
        if i2[0] == "un" and i2[1] == "*":
            i3 = strip_paren(i2[2])
            if i3[0] == "cast":
                i3 = strip_paren(i3[2])
            return add_const(i3, 0xb8)
    return False


def children(s):
    """Unterlisten einer Anweisung (if: then/else, switch: Rumpf)."""
    if s[0] == "if":
        return [s[2]] + ([s[3]] if s[3] is not None else [])
    return [s[2]] if s[0] == "switch" else []


def rebuild(s, f):
    """Anweisung mit f auf alle Unterlisten angewandt."""
    if s[0] == "if":
        return ("if", s[1], f(s[2]), f(s[3]) if s[3] is not None else None)
    if s[0] == "switch":
        return ("switch", s[1], f(s[2]))
    return s


def map_expr(e, f):
    """Kopie von e, in der jeder Teilausdruck zuerst durch f ersetzt werden darf (f liefert None = unveraendert weitergehen)."""
    r = f(e)
    if r is not None:
        return r
    if not isinstance(e, tuple):
        return e
    k = e[0]
    if k == "bin":
        return ("bin", e[1], map_expr(e[2], f), map_expr(e[3], f))
    if k in ("un", "cast"):
        return (k, e[1], map_expr(e[2], f))
    if k == "paren":
        return ("paren", map_expr(e[1], f))
    if k == "call":
        return ("call", e[1], [map_expr(a, f) for a in e[2]])
    if k == "assign":
        return ("assign", e[1], map_expr(e[2], f), map_expr(e[3], f))
    if k == "comma":
        return ("comma", [map_expr(a, f) for a in e[1]])
    if k == "tern":
        return ("tern", map_expr(e[1], f), map_expr(e[2], f), map_expr(e[3], f))
    if k == "idx":
        return ("idx", map_expr(e[1], f), map_expr(e[2], f))
    return e


def assign_of(s):
    """(lhs, op, rhs) einer Zuweisungsanweisung oder None."""
    if s[0] != "expr":
        return None
    e = strip_paren(s[1])
    return (strip_paren(e[2]), e[1], e[3]) if e[0] == "assign" else None


def deref_len(r):
    r = strip_paren(r)
    return r[0] == "un" and r[1] == "*" and "0x18" in repr(r) and len(set(ids_of(r))) == 1


class Simplifier:
    def __init__(self, fn):
        self.fn = fn
        self.decls = {}
        self.body = []
        for s in fn["body"]:
            if s[0] == "decl":
                self.decls[s[2]] = s[1]
            else:
                self.body.append(s)
        self.err_labels, self.cvars, self.lenvars, self.mixedlen, self.ptrvars = set(), set(), set(), set(), {}
        self.blob_fn = None

    def each(self, stmts):
        for s in stmts:
            yield s
            for sub in children(s):
                yield from self.each(sub)

    def find_error_labels(self, stmts):
        for idx, s in enumerate(stmts):
            if s[0] == "label":
                names, j = [], idx + 1
                while j < len(stmts) and stmts[j][0] == "expr":
                    names.extend(calls_of(stmts[j][1]))
                    j += 1
                if names and all(is_err_call_name(n) for n in names):
                    self.err_labels.add(s[1])
            for sub in children(s):
                self.find_error_labels(sub)

    def find_vars(self):
        acc = {}
        for s in self.each(self.body):
            a = assign_of(s)
            if not a or a[0][0] != "id":
                continue
            acc.setdefault(a[0][1], []).append(a[1] == "=" and deref_len(a[2]))
            r = strip_paren(a[2])
            if a[1] == "=" and r[0] == "id" and r[1].startswith("PTR_DAT_"):
                self.ptrvars[a[0][1]] = r[1]
        self.lenvars = {v for v, fl in acc.items() if all(fl)}
        self.mixedlen = {v for v, fl in acc.items() if any(fl) and not all(fl)}

    def run(self):
        self.find_vars()
        self.find_error_labels(self.body)
        self.body = self.clean_list(self.body)
        self.body = self.error_tails(self.body)
        for _ in range(6):
            self.cvars |= self.class_vars()
            self.body = self.noise_pass(self.body)
        self.body = self.arrays(self.body)
        for _ in range(4):
            self.body = self.dead_assign(self.body)
        used = {s[1] for s in self.each(self.body) if s[0] == "goto"}
        return self.drop_labels(self.body, used)

    # ---- Grenzpruefungen der Argument-Arrays -> Fehlersprung
    def clean_list(self, stmts):
        out = []
        for s in stmts:
            if s[0] == "if":
                c, th, el = s[1], self.clean_list(s[2]), self.clean_list(s[3]) if s[3] is not None else None
                gerr = self.err_goto_if(c, th, el)
                if gerr is not None:
                    out.extend(gerr)
                    continue
                gt = self.guard_terms(c)
                if gt is not None:
                    out.extend(gt)
                    out.extend(th)
                    continue
                out.append(("if", c, th, el))
            else:
                out.append(rebuild(s, self.clean_list))
        return out

    @staticmethod
    def split_terms(c, ops):
        terms = []

        def split(e):
            e = strip_paren(e)
            if e[0] == "bin" and e[1] in ops:
                split(e[2])
                split(e[3])
            else:
                terms.append(e)

        split(c)
        return terms

    def err_goto_if(self, c, th, el):
        if el is not None or len(th) != 1 or th[0][0] != "goto" or th[0][1] not in self.err_labels:
            return None
        out = []
        for t in self.split_terms(c, ("||",)):
            if t[0] == "comma":
                out.extend(("expr", a) for a in t[1][:-1])
                if not self.is_bound_check(t[1][-1], True):
                    raise Err("Kommaterm ohne Grenzpruefung: " + repr(t[1][-1])[:120])
            elif not self.is_bound_check(t, True):
                cs = calls_of(t)
                if not (cs and all(is_junk_call_name(x) for x in cs)):
                    raise Err("Fehlersprung mit unerwarteter Bedingung: " + repr(t)[:160])
        return out

    def is_bound_check(self, e, mixed=False):
        e = strip_paren(e)
        if e[0] != "bin" or calls_of(e):
            return False
        ids = set(ids_of(e))
        if ids and ids <= (self.lenvars | self.mixedlen if mixed else self.lenvars):
            return True
        if len(ids) != 1:
            return False
        if next(iter(ids)).startswith("pl"):
            return True
        found = []
        walk_expr(e, lambda x: found.append(1) if isinstance(x, tuple) and add_const(x, 0x18) else None)
        return bool(found)

    def guard_terms(self, c):
        # `(len != 0) && (len > 1 || ...)` -> Zuweisungen der Kommaterme, falls ausschliesslich Grenzpruefungen
        pre = []
        for t in self.split_terms(c, ("&&", "||")):
            if t[0] == "comma":
                pre.extend(("expr", a) for a in t[1][:-1])
                t = t[1][-1]
            if not self.is_bound_check(t):
                return None
        return pre

    def error_tails(self, stmts):
        out, i = [], 0
        while i < len(stmts):
            s = stmts[i]
            if s[0] == "label" and s[1] in self.err_labels:
                i += 1
                while i < len(stmts) and stmts[i][0] == "expr" and calls_of(stmts[i][1]) and all(is_err_call_name(n) for n in calls_of(stmts[i][1])):
                    i += 1
                continue
            if not (s[0] == "goto" and s[1] in self.err_labels):
                out.append(rebuild(s, self.error_tails))
            i += 1
        return out

    # ---- Klassen-Initialisierungsrauschen
    def class_vars(self):
        assigns = {}
        for s in self.each(self.body):
            a = assign_of(s)
            if a and a[0][0] == "id":
                assigns.setdefault(a[0][1], []).append(a[2] if a[1] == "=" else None)
        cv, changed = set(), True
        while changed:
            changed = False
            for v, rhss in assigns.items():
                if v not in cv and all(r is not None and self.noise_expr(r, cv) for r in rhss):
                    cv.add(v)
                    changed = True
        return cv

    def noise_expr(self, e, cv):
        e = strip_paren(e)
        ids = ids_of(e)
        if is_empty_expr(e) or not ids or any(not is_junk_call_name(c) for c in calls_of(e)):
            return False
        found = []
        walk_expr(e, lambda x: found.append(1) if isinstance(x, tuple) and x[0] == "bin" and x[1] == "+" and strip_paren(x[3])[0] == "num"
                  and const_int(x[3]) in (0x12e, 0x12f, 0xe0, 0x30) else None)
        if found:
            return True
        return all(i.startswith(("PTR_", "DAT_", "local_")) or i in cv for i in ids)

    def clean_expr(self, e):
        # Kommaausdruecke: Rauschterme (Klassenzeiger, Debug-Aufrufe) entfernen
        def f(x):
            if not (isinstance(x, tuple) and x[0] == "comma"):
                return None
            items = []
            for a in x[1][:-1]:
                a2 = strip_paren(a)
                rc = strip_paren(a2[3]) if a2[0] == "assign" else None
                if a2[0] == "assign" and (self.noise_expr(a2[3], self.cvars) or (strip_paren(a2[2])[0] == "id" and strip_paren(a2[2])[1] in self.cvars)):
                    continue
                if a2[0] == "call" and a2[1][0] == "id" and is_junk_call_name(a2[1][1]):
                    continue
                if rc is not None and rc[0] == "call" and rc[1][0] == "id" and is_junk_call_name(rc[1][1]):
                    continue
                items.append(map_expr(a, f))
            last = map_expr(x[1][-1], f)
            return ("comma", items + [last]) if items else last

        return map_expr(e, f)

    def noise_pass(self, stmts):
        out = []
        for s in stmts:
            k = s[0]
            if k == "expr":
                e = strip_paren(s[1])
                if e[0] == "assign":
                    lhs, rhs = strip_paren(e[2]), strip_paren(e[3])
                    if lhs[0] == "id" and lhs[1].startswith("local_") and any(c.endswith("CurrentWazaNo") for c in calls_of(e[3])):
                        out.append(("expr", ("assign", "=", ("id", "dummyWaza"), e[3])))   # Debug-Ausgabe ruft CurrentWazaNo (AI_CMD) wirklich auf
                        continue
                    if lhs[0] == "id" and (lhs[1] in self.cvars or lhs[1].startswith(("DAT_", "local_"))):
                        continue
                    if lhs[0] == "id" and e[1] == "=" and (self.noise_expr(e[3], self.cvars) or (deref_len(e[3]) and lhs[1] in self.lenvars)):
                        continue
                    if rhs[0] == "cast":
                        rhs = strip_paren(rhs[2])
                    if rhs[0] == "call" and rhs[1][0] == "id" and (is_junk_call_name(rhs[1][1]) or is_err_call_name(rhs[1][1])):
                        continue
                    if lhs[0] == "idx" and ids_of(lhs[1]) and ids_of(lhs[1])[0].startswith("pl"):
                        continue
                if e[0] == "call" and e[1][0] == "id" and (is_junk_call_name(e[1][1]) or is_err_call_name(e[1][1])):
                    continue
                out.append(s)
            elif k == "if":
                c = self.clean_expr(s[1])
                th = self.noise_pass(s[2])
                el = self.noise_pass(s[3]) if s[3] is not None else None
                if self.noise_expr(c, self.cvars):
                    def real(lst):
                        return [x for x in lst if x[0] not in ("label", "goto") and not (x[0] == "if" and self.noise_expr(x[1], self.cvars))]

                    rth, rel = real(th), real(el or [])
                    keep = rth if (rth == rel or not rel) else rel if not rth else None
                    if keep is None:
                        raise Err("Rausch-Bedingung mit echtem Inhalt: " + repr(c)[:100])
                    out.extend(x for x in th + (el or []) if x[0] == "label")
                    out.extend(keep)
                elif th or el or calls_of(c):
                    out.append(("if", c, th, el))
            else:
                out.append(rebuild(s, self.noise_pass))
        return out

    # ---- Arrays: je Variable zu `C(cmd, n, ...)` verschmolzen (alloc, Stores, genau ein Aufruf in derselben Liste) oder explizit (Variable + "A")
    @staticmethod
    def store_target(lhs):
        lhs = strip_paren(lhs)
        if lhs[0] == "idx" and strip_paren(lhs[1])[0] == "id":
            return strip_paren(lhs[1])[1], const_int(lhs[2])
        if lhs[0] == "un" and lhs[1] == "*":
            inner = strip_paren(lhs[2])
            if inner[0] == "cast":
                inner = strip_paren(inner[2])
            if inner[0] == "bin" and inner[1] == "+" and strip_paren(inner[2])[0] == "id":
                off = const_int(inner[3])
                if off >= 0x20 and (off - 0x20) % 8 == 0:
                    return strip_paren(inner[2])[1], (off - 0x20) // 8
        return None

    @staticmethod
    def is_cmd_call(x):
        return isinstance(x, tuple) and x[0] == "call" and x[1][0] == "id" and x[1][1].endswith(("BtlAIBaseScript__Call", "AI_CMD"))

    def arr_value(self, rhs):
        rhs = strip_paren(rhs)
        if rhs[0] == "cast":
            rhs = strip_paren(rhs[2])
        if rhs[0] == "call" and rhs[1][0] == "id" and rhs[1][1] == "FUN_003afb00":
            return ("new", {}, const_int(rhs[2][1]))
        return ("empty", {}, 0) if is_empty_expr(rhs) else None

    def arrays(self, stmts):
        allocs = set()
        for s in self.each(stmts):
            a = assign_of(s)
            if a and a[1] == "=" and a[0][0] == "id" and self.arr_value(a[2]) is not None:
                allocs.add(a[0][1])
        events, counter = {}, [0]

        def uses(e):
            out = []
            walk_expr(e, lambda x: out.append(strip_paren(x[2][2])[1]) if self.is_cmd_call(x) and strip_paren(x[2][2])[0] == "id" and strip_paren(x[2][2])[1] in allocs else None)
            return out

        def rec(lst):
            lid = counter[0]
            counter[0] += 1
            for idx, s in enumerate(lst):
                ev = lambda v, kind: events.setdefault(v, []).append((kind, lid, idx))  # noqa: E731
                if s[0] == "expr":
                    e = strip_paren(s[1])
                    if e[0] == "assign" and e[1] == "=":
                        sv = self.store_target(e[2]) if strip_paren(e[2])[0] != "id" else None
                        if sv and sv[0] in allocs:
                            ev(sv[0], "store")
                            for u in uses(e[3]):
                                ev(u, "use")
                            continue
                        if strip_paren(e[2])[0] == "id" and strip_paren(e[2])[1] in allocs and self.arr_value(e[3]) is not None:
                            ev(strip_paren(e[2])[1], "alloc")
                            continue
                    if e[0] == "call" and e[1][0] == "id" and "InitializeArray" in e[1][1]:
                        ev(strip_paren(e[2][0])[1], "store")
                        continue
                    for u in uses(e):
                        ev(u, "use")
                else:
                    for u in uses(s[1]) if s[0] in ("if", "switch") or (s[0] == "return" and s[1] is not None) else []:
                        ev(u, "use")
                    for sub in children(s):
                        rec(sub)

        rec(stmts)
        self.mergeable = set()
        for v, ev in events.items():
            ok, i = True, 0
            while ok and i < len(ev):
                lid, j = ev[i][1], i + 1
                while j < len(ev) and ev[j][0] == "store" and ev[j][1] == lid:
                    j += 1
                ok = ev[i][0] == "alloc" and j < len(ev) and ev[j][0] == "use" and ev[j][1] == lid
                i = j + 1
            if ok:
                self.mergeable.add(v)
        self.arrvars, self.arrlen, self.pending = allocs, {}, {}
        return self.arr_list(stmts)

    def arr_list(self, stmts):
        out = []
        for s in stmts:
            k = s[0]
            if k == "expr":
                e = strip_paren(s[1])
                if e[0] == "call" and e[1][0] == "id" and "InitializeArray" in e[1][1]:
                    var = strip_paren(e[2][0])[1]
                    cand = [i for i in ids_of(e[2][1]) if i.startswith("PTR_DAT_")] or [self.ptrvars[i] for i in ids_of(e[2][1]) if i in self.ptrvars]
                    for i, v in enumerate(self.blob_fn(cand[0][8:])):
                        ve = ("num", str(v)) if v >= 0 else ("un", "-", ("num", str(-v)))
                        if var in self.mergeable:
                            self.pending[var][1][i] = ve
                        else:
                            out.append(("expr", ("assign", "=", ("idx", ("id", var + "A"), ("num", str(i))), ve)))
                    continue
                if e[0] == "assign" and e[1] == "=":
                    lhs, rhs = strip_paren(e[2]), strip_paren(e[3])
                    sv = self.store_target(lhs) if lhs[0] != "id" else None
                    if sv and sv[0] in self.arrvars:
                        v, i = sv
                        val = self.subst_arr(e[3])
                        if v in self.mergeable:
                            self.pending[v][1][i] = val
                        else:
                            out.append(("expr", ("assign", "=", ("idx", ("id", v + "A"), ("num", str(i))), val)))
                        continue
                    if lhs[0] == "id" and lhs[1] in self.mixedlen and deref_len(rhs) and ids_of(rhs)[0] in self.arrlen:
                        out.append(("expr", ("assign", "=", e[2], ("num", str(self.arrlen[ids_of(rhs)[0]])))))   # Laenge des zuletzt allokierten Arrays
                        continue
                    if lhs[0] == "id" and lhs[1] in self.arrvars and self.arr_value(rhs) is not None:
                        arrv = self.arr_value(rhs)
                        self.arrlen[lhs[1]] = arrv[2]
                        if lhs[1] in self.mergeable:
                            self.pending[lhs[1]] = arrv
                        else:
                            out.append(("expr", ("assign", "=", ("id", lhs[1] + "A"), ("arrnew", arrv[2], arrv[0]))))
                        continue
                out.append(("expr", self.subst_arr(s[1])))
            elif k == "if":
                out.append(("if", self.subst_arr(s[1]), self.arr_list(s[2]), self.arr_list(s[3]) if s[3] is not None else None))
            elif k == "switch":
                out.append(("switch", self.subst_arr(s[1]), self.arr_list(s[2])))
            elif k == "return" and s[1] is not None:
                out.append(("return", self.subst_arr(s[1])))
            else:
                out.append(s)
        return out

    def subst_arr(self, e):
        def f(x):
            if not self.is_cmd_call(x):
                return None
            cmd, arr = map_expr(x[2][1], f), strip_paren(x[2][2])
            if arr[0] == "id" and arr[1] in self.arrvars:
                if arr[1] not in self.mergeable:
                    return ("call", ("id", "Call"), [cmd, ("id", arr[1] + "A")])
                kind, vals, n = self.pending[arr[1]]
                if kind == "empty":
                    return ("call", ("id", "Call"), [cmd, ("id", "Empty")])
                items = [map_expr(vals.get(i, ("num", "0")), f) for i in range((max(vals) + 1) if vals else 0)]
                return ("call", ("id", "C"), [cmd, ("num", str(n))] + items)
            if is_empty_expr(arr):
                return ("call", ("id", "Call"), [cmd, ("id", "Empty")])
            raise Err("Call-Argument kein bekanntes Array: " + repr(arr)[:100])

        return map_expr(e, f)

    # ---- Aufraeumen
    def dead_assign(self, stmts):
        reads = {}
        for s in self.each(stmts):
            a = assign_of(s)
            es = [a[2]] if a and a[1] == "=" and a[0][0] == "id" else [s[1]] if s[0] in ("expr", "if", "switch") else [s[1]] if s[0] == "return" and s[1] is not None else []
            for e in es:
                for i in ids_of(e):
                    reads[i] = reads.get(i, 0) + 1

        def prune(lst):
            out = []
            for s in lst:
                a = assign_of(s)
                if a and a[1] == "=" and a[0][0] == "id" and reads.get(a[0][1], 0) == 0:
                    cs = calls_of(a[2])
                    if cs and not all(is_junk_call_name(c) for c in cs):
                        out.append(("expr", a[2]))     # Aufruf mit Seiteneffekt behalten, Ergebnis verwerfen
                    continue
                out.append(rebuild(s, prune))
            return out

        return prune(stmts)

    def drop_labels(self, stmts, used):
        return [rebuild(s, lambda l: self.drop_labels(l, used)) for s in stmts if not (s[0] == "label" and s[1] not in used)]
