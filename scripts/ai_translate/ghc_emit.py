#!/usr/bin/env python3
"""AST (ghc_parse) -> C# (Teil 2 von scripts/ai_translate): typgetreue Ausdruecke, goto-treuer Kontrollfluss, Strukturierung wo moeglich.

C# erlaubt `goto` nur auf Marken im selben oder einem umschliessenden Block. Ein if-Block bleibt strukturiert, wenn jede in ihm sichtbare Marke nur
von innen angesprungen wird; sonst wird er zu `if (!c) goto Lelse; ...` abgeflacht (die Marken wandern in den umgebenden Block).
Typen folgen den Ghidra-Deklarationen (int/uint/long/ulong); Vorzeichen-Idiome wie `x - 0x68U < 0x3d` bleiben vorzeichenlos.
"""
import re

from ghc_parse import Err, strip_paren, const_int, ids_of

CT = {"undefined8": "ulong", "undefined4": "uint", "undefined2": "ushort", "undefined1": "byte", "undefined": "byte", "ulong": "ulong", "long": "long",
      "int": "int", "uint": "uint", "ushort": "ushort", "byte": "byte", "bool": "bool", "short": "short", "char": "sbyte", "void": "void"}
SMALL = {"ushort", "byte", "short", "sbyte"}
PREC = {"||": 1, "&&": 2, "|": 3, "^": 4, "&": 5, "==": 6, "!=": 6, "<": 7, ">": 7, "<=": 7, ">=": 7, "<<": 8, ">>": 8, "+": 9, "-": 9, "*": 10, "/": 10, "%": 10}
FN_PARAMS, FN_RENAME = {}, {}


def promote(t):
    return "int" if t in SMALL else t


def common(a, b):
    a, b = promote(a), promote(b)
    if a == b:
        return a
    for t in ("ulong", "long", "uint"):
        if t in (a, b):
            return t
    return "int"


def lit(tok):
    t = tok.lower()
    u, l = "u" in t, "l" in t
    body = t.rstrip("ul")
    v = int(body, 0)
    hexa = body.startswith("0x")
    if u or l:
        ty = ("ulong" if v > 0xffffffff else "uint") if (u and not l) else ("ulong" if u else "long")
    elif hexa:
        ty = "int" if v <= 0x7fffffff else "uint" if v <= 0xffffffff else "long" if v <= 0x7fffffffffffffff else "ulong"
    else:
        ty = "int" if v <= 0x7fffffff else "long" if v <= 0x7fffffffffffffff else "ulong"
    txt = body if hexa and v >= 10 else str(v)
    return txt + {"int": "", "uint": "u", "long": "L", "ulong": "UL"}[ty], ty, v


def short_label(l):
    m = re.match(r"(?:LAB_01d|joined_r0x01d|switchD_01d)(\w+?)(?:_caseD_(\w+))?$", l)
    if not m:
        return l
    return ("L" if l.startswith("LAB") else "J" if l.startswith("j") else "S") + m.group(1) + ("_" + m.group(2) if m.group(2) else "")


def atom(c):
    return c if re.fullmatch(r"\w+", c) else f"({c})"


def cast(to, c):
    return f"({to}){atom(c)}"


class Emitter:
    def __init__(self, fn, body, decls):
        self.fn, self.body, self.decls = fn, body, decls
        self.tables, self.total, self.uid = set(), {}, 0

    # ---- Ausdruecke
    def vtype(self, name):
        if name in ("true", "false"):
            return "bool"
        if name.endswith("A") and name[:-1] in self.decls and name not in self.decls:
            return "arr"
        t = self.decls.get(name)
        if t is None:
            if name.startswith("param_"):
                return self.ptypes.get(name, "ulong")
            raise Err("unbekannte Variable " + name)
        if t[1]:
            raise Err("Zeiger-Variable benutzt: " + name)
        return CT[t[0]] if CT[t[0]] in SMALL else promote(CT[t[0]])

    def conv(self, code, frm, to):
        frm, to = promote(frm), promote(to)
        return code if frm == to else cast(to, code)

    def par(self, code, e, parent_prec, right=False):
        k = strip_paren(e)
        if k[0] == "bin":
            p = PREC[k[1]]
            if p < parent_prec or (p == parent_prec and right) or (p != parent_prec and k[1] in ("&", "|", "^", "<<", ">>")):
                return "(" + code + ")"
            if p == parent_prec:
                return code
            return "(" + code + ")" if p < 10 and parent_prec in (6, 7, 8, 9, 10) else code
        return "(" + code + ")" if k[0] in ("assign", "tern", "comma") else code

    def cond(self, e):
        code, ty = self.ex(e)
        return code if ty == "bool" else f"{self.par(code, e, 6)} != 0"

    def intval(self, code, ty):
        return (f"({code} ? 1 : 0)", "int") if ty == "bool" else (code, ty)

    def ex(self, e):
        k = e[0]
        if k == "paren":
            return self.ex(e[1])
        if k == "num":
            code, ty, _ = lit(e[1])
            return code, ty
        if k == "id":
            return e[1], self.vtype(e[1])
        if k == "cast":
            if e[1][1]:
                raise Err("Zeiger-Cast")
            to, inner = CT[e[1][0]], strip_paren(e[2])
            code, ty = self.intval(*self.ex(e[2]))
            if inner[0] == "num":
                v = lit(inner[1])[2]
                bits = {"ulong": 64, "long": 64, "uint": 32, "int": 32, "ushort": 16, "byte": 8, "short": 16, "sbyte": 8}[to]
                v &= (1 << bits) - 1
                if to in ("int", "long", "short", "sbyte") and v >= (1 << (bits - 1)):
                    v -= 1 << bits
                return str(v) + {"ulong": "UL", "long": "L", "uint": "u"}.get(to, ""), promote(to)
            return cast(to, code) if re.fullmatch(r"\w+", code) else f"({to})({code})", promote(to)
        if k == "un":
            op = e[1]
            if op == "*":
                return self.deref(e)
            if op == "!":
                c = self.cond(e[2])
                return ("!(" + c + ")" if strip_paren(e[2])[0] in ("bin", "un") else "!" + c), "bool"
            code, ty = self.intval(*self.ex(e[2]))
            if op == "-":
                if ty in ("uint", "ulong"):
                    return f"unchecked(({ty})(0 - {self.par(code, e[2], 11)}))", ty
                return "-" + self.par(code, e[2], 11), ty
            if op == "~":
                return "~" + self.par(code, e[2], 11), ty
            if op == "+":
                return code, ty
            raise Err("Unaeres " + op)
        if k == "bin":
            return self.binary(e)
        if k == "call":
            return self.call(e)
        if k == "assign":
            return self.assign(e)
        if k == "tern":
            a, ta = self.ex(e[2])
            b, tb = self.ex(e[3])
            t = common(ta, tb)
            return f"({self.cond(e[1])} ? {self.conv(a, ta, t)} : {self.conv(b, tb, t)})", t
        if k == "comma":
            parts = [self.ex(a) for a in e[1]]
            return "(" + ", ".join(c for c, _ in parts) + f").Item{len(parts)}", parts[-1][1]
        if k == "arrnew":
            return ("Empty" if e[2] == "empty" else f"new long[{e[1]}]"), "arr"
        raise Err("Ausdruck " + k)

    def deref(self, e):
        inner = strip_paren(e[2])
        if inner[0] == "cast":
            inner = strip_paren(inner[2])
        if inner[0] == "bin" and inner[1] == "+":
            base, idx = strip_paren(inner[2]), strip_paren(inner[3])
            if base[0] == "id" and base[1] == "param_1":
                off = const_int(idx)
                if off in (0x14, 0x18, 0x10):
                    return {0x14: "Score", 0x18: "MyClientId", 0x10: "PokeChangeEnable"}[off], "int"
            if base[0] == "un" and base[1] == "&" and strip_paren(base[2])[0] == "id" and strip_paren(base[2])[1].startswith("DAT_") \
                    and idx[0] == "bin" and idx[1] == "*" and const_int(idx[3]) == 4:
                name = "Tab" + strip_paren(base[2])[1][4:]
                self.tables.add(name)
                c, _ = self.ex(idx[2])
                return f"{name}[(int){self.par(c, idx[2], 11)}]", "int"
        raise Err("Deref: " + repr(e)[:140])

    def binary(self, e):
        op, l, r = e[1], strip_paren(e[2]), strip_paren(e[3])
        if op in ("&&", "||"):
            a, b = self.cond(e[2]), self.cond(e[3])
            lop = l[1] if l[0] == "bin" else None
            rop = r[1] if r[0] == "bin" else None
            ra = f"({a})" if op == "&&" and lop == "||" else a
            rb = f"({b})" if op == "&&" and rop == "||" else b
            if lop in ("&&", "||") and PREC[lop] < PREC[op]:
                ra = f"({a})"
            if rop in ("&&", "||") and rop != op and PREC[rop] <= PREC[op]:
                rb = f"({b})"
            return f"{ra} {op} {rb}", "bool"
        if op in ("==", "!=") and r[0] == "num" and const_int(r) == 0:
            bt = self.bit_test(l)
            if bt:
                return ("!" if op == "==" else "") + bt, "bool"
        a, ta = self.intval(*self.ex(e[2]))
        b, tb = self.intval(*self.ex(e[3]))
        if op in ("<<", ">>"):
            bc = str(lit(r[1])[2]) if r[0] == "num" else f"(int){self.par(b, e[3], 11)}"
            return f"{self.par(a, e[2], PREC[op])} {op} {bc}", promote(ta)
        t = common(ta, tb)
        for n_, o_ in ((l, ta), (r, tb)):
            if n_[0] == "num" and "u" in n_[1].lower() and promote(o_) in ("long", "ulong", "int", "uint"):
                t = "ulong" if (promote(ta) in ("long", "ulong") or promote(tb) in ("long", "ulong")) else "uint"
        ca = self.conv(a, ta, t) if l[0] != "num" and promote(ta) != t else a
        cb = self.conv(b, tb, t) if r[0] != "num" and promote(tb) != t else b
        if l[0] == "num" and r[0] != "num":
            ca = self.numas(l, t)
        if r[0] == "num" and l[0] != "num":
            cb = self.numas(r, t)
        pa = self.par(ca, e[2], PREC[op]) if ca is a else ca
        pb = self.par(cb, e[3], PREC[op], True) if cb is b else cb
        return f"{pa} {op} {pb}", ("bool" if op in ("==", "!=", "<", ">", "<=", ">=") else t)

    def bit_test(self, e):
        # (1L << (S & 0x3f)) & MASK  ->  Bit(S, MASK);   (1 << (S & 0x1f)) & MASK -> Bit32(S, MASK)
        if e[0] != "bin" or e[1] != "&":
            return None
        for sh, mk in ((strip_paren(e[2]), strip_paren(e[3])), (strip_paren(e[3]), strip_paren(e[2]))):
            if sh[0] == "bin" and sh[1] == "<<" and strip_paren(sh[2])[0] == "num" and const_int(sh[2]) == 1 and mk[0] == "num":
                cnt = strip_paren(sh[3])
                if cnt[0] == "bin" and cnt[1] == "&" and strip_paren(cnt[3])[0] == "num" and const_int(cnt[3]) in (0x3f, 0x1f):
                    src = cnt[2]
                    while strip_paren(src)[0] == "cast":
                        src = strip_paren(src)[2]
                    c, t = self.ex(src)
                    mv = const_int(mk)
                    arg = c if t == "ulong" else (f"(ulong){c}" if re.fullmatch(r"[\w.]+", c) else f"(ulong)({c})")
                    return f"Bit{'' if const_int(cnt[3]) == 0x3f else '32'}({arg}, 0x{mv:x}{'UL' if mv > 0xffffffff else 'u'})"
        return None

    def numas(self, n, t):
        code, ty, v = lit(n[1])
        if t == "int" and ty in ("uint", "ulong") and v > 0x7fffffff:
            return f"unchecked((int){code})"
        return code

    def call(self, e):
        f = strip_paren(e[1])
        if f[0] != "id":
            raise Err("indirekter Aufruf")
        name, args = f[1], e[2]
        if name == "C":
            vals = []
            for a in args[2:]:
                c, t = self.intval(*self.ex(a))
                vals.append(c if strip_paren(a)[0] == "num" or promote(t) in ("int", "long") else f"(long){self.par(c, a, 11)}")
            return f"C({self.cmdname(args[0])}, {args[1][1]}" + "".join(", " + v for v in vals) + ")", "long"
        if name == "Call":
            return f"Call({self.cmdname(args[0])}, {args[1][1] if args[1][0] == 'id' else ''})", "long"
        if name.endswith("CurrentWazaNo"):
            return "(int)CurrentWaza()", "int"
        if name.endswith("BtlAIBaseScript__ScoreCtrl"):
            a1 = strip_paren(args[1])
            if a1[0] == "num":
                v = const_int(a1) & 0xffffffff
                v -= (1 << 32) if v >= 0x80000000 else 0
                return (f"Score -= {-v}" if v < 0 else f"Score += {v}"), "void"
            c, _ = self.ex(args[1])
            return f"Score += (int){self.par(c, args[1], 11)}", "void"
        m = re.match(r"Dpr_Battle_Logic_Btl\w+?__(\w+)$", name)
        if m:
            extra = []
            for a, pt in zip(args[1:], FN_PARAMS.get(m.group(1), [])):
                c_, t_ = self.ex(a)
                if strip_paren(a)[0] == "num":
                    extra.append(c_)
                else:
                    extra.append(f"({pt}){self.par(c_, a, 11)}" if pt in SMALL else self.conv(c_, t_, pt))
            return f"{FN_RENAME.get(m.group(1), m.group(1))}({', '.join(extra)})", self.fn_rets.get(m.group(1), "void")
        raise Err("unbekannter Aufruf " + name)

    def cmdname(self, a):
        a = strip_paren(a)
        if a[0] == "num":
            return self.cmdnames.get(const_int(a), str(const_int(a)))
        return f"(int){self.ex(a)[0]}"

    def assign(self, e):
        op, lhs, rhs = e[1], e[2], e[3]
        l = strip_paren(lhs)
        if l[0] == "idx":
            c, _ = self.ex(rhs)
            return f"{strip_paren(l[1])[1]}[{const_int(l[2])}] = {c if strip_paren(rhs)[0] == 'num' else '(long)' + self.par(c, rhs, 11)}", "void"
        if op != "=":
            return self.assign(("assign", "=", lhs, ("bin", op[:-1], lhs, rhs)))
        lc, lt = self.ex(lhs)
        rc, rt = self.ex(rhs)
        if lt == "arr":
            return f"{lc} = {rc}", "void"
        if lt == "bool":
            return f"{lc} = " + (rc if rt == "bool" else f"{self.par(rc, rhs, 6)} != 0"), "bool"
        rc, rt = self.intval(rc, rt)
        if strip_paren(rhs)[0] == "num":
            code, ty, v = lit(strip_paren(rhs)[1])
            if promote(lt) != ty:
                if v > 0x7fffffff and lt == "int" and ty == "uint":
                    code = f"unchecked((int){code})"
                elif lt in SMALL:
                    code = f"({lt}){code}"
            return f"{lc} = {code}", lt
        if promote(rt) != promote(lt):
            rc = f"({lt}){self.par(rc, rhs, 11)}"
        elif lt in SMALL:
            rc = f"({lt}){rc}"
        return f"{lc} = {rc}", lt

    # ---- Strukturierung
    def count_gotos(self, lst, tgt):
        for s in lst:
            if s[0] == "goto":
                tgt[s[1]] = tgt.get(s[1], 0) + 1
            elif s[0] == "if":
                self.count_gotos(s[2], tgt)
                self.count_gotos(s[3] or [], tgt)
            elif s[0] == "switch":
                self.count_gotos(s[2], tgt)
            elif s[0] == "swjump":
                for _, l in s[2]:
                    tgt[l] = tgt.get(l, 0) + 1
                tgt[s[3]] = tgt.get(s[3], 0) + 1

    def flatten(self, lst):
        out = []
        for s in lst:
            if s[0] == "if":
                th = self.flatten(s[2])
                el = self.flatten(s[3]) if s[3] is not None else None
                ok = True
                for branch in (th, el or []):
                    cnt = {}
                    self.count_gotos(branch, cnt)
                    for l in (x[1] for x in branch if x[0] == "label"):
                        ok = ok and cnt.get(l, 0) == self.total.get(l, 0)
                if ok:
                    out.append(("if", s[1], th, el))
                    continue
                self.uid += 1
                lend, lelse = f"Lx{self.uid}e", f"Lx{self.uid}f"
                neg = ("un", "!", ("paren", s[1]))
                self.total[lend] = 1
                if el is None:
                    out += [("if", neg, [("goto", lend)], None)] + th + [("label", lend)]
                else:
                    self.total[lelse] = 1
                    out += [("if", neg, [("goto", lelse)], None)] + th + [("goto", lend), ("label", lelse)] + el + [("label", lend)]
            elif s[0] == "switch":
                self.uid += 1
                lend, default, body, cases, prev_case = f"Lx{self.uid}e", None, [], [], False
                default = lend
                for x in s[2]:
                    if x[0] == "case":
                        if not prev_case:
                            body.append(("label", f"Lx{self.uid}c{x[1] if x[1] >= 0 else 'm' + str(-x[1])}"))
                        cases.append((x[1], body[-1][1] if not prev_case else cases[-1][1]))
                        prev_case = True
                        continue
                    prev_case = False
                    if x[0] == "default":
                        default = f"Lx{self.uid}d"
                        body.append(("label", default))
                    else:
                        body.append(self.fix_breaks(x, lend))
                body = self.flatten(body)
                self.total[lend] = self.total.get(lend, 0) + 1 + sum(1 for x in self.iter_stmts(body) if x[0] == "goto" and x[1] == lend)
                for _, l in cases:
                    self.total[l] = sum(1 for _, cl in cases if cl == l)
                if default != lend:
                    self.total[default] = 1
                out += [("swjump", s[1], cases, default)] + body + [("label", lend)]
            else:
                out.append(s)
        return out

    def fix_breaks(self, x, lend):
        if x[0] == "break":
            return ("goto", lend)
        if x[0] == "if":
            return ("if", x[1], [self.fix_breaks(y, lend) for y in x[2]], [self.fix_breaks(y, lend) for y in x[3]] if x[3] is not None else None)
        return x

    def drop_labels(self, lst, refs):
        out = []
        for x in lst:
            if x[0] == "label" and refs.get(x[1], 0) == 0:
                continue
            out.append(("if", x[1], self.drop_labels(x[2], refs), self.drop_labels(x[3], refs) if x[3] is not None else None) if x[0] == "if" else x)
        return out

    def iter_stmts(self, lst):
        for s in lst:
            yield s
            if s[0] == "if":
                yield from self.iter_stmts(s[2])
                yield from self.iter_stmts(s[3] or [])

    def emit_list(self, lst, ind):
        pad, out = "    " * ind, []
        for s in lst:
            k = s[0]
            if k == "label":
                out.append(f"{'    ' * max(ind - 1, 0)}{short_label(s[1])}:;")
            elif k == "goto":
                out.append(f"{pad}goto {short_label(s[1])};")
            elif k == "return":
                if s[1] is None:
                    out.append(f"{pad}return;")
                else:
                    c, t = self.ex(s[1])
                    rt = self.fn_ret
                    if rt == "bool" and t != "bool":
                        c = f"{self.par(c, s[1], 6)} != 0"
                    elif rt != "bool" and t != rt and rt != "void" and strip_paren(s[1])[0] != "num" and t != "bool":
                        c = self.conv(c, t, rt)
                    out.append(f"{pad}return {c};")
            elif k == "expr":
                c, _ = self.ex(s[1])
                out.append(f"{pad}{'CurrentWaza()' if c.startswith('(int)CurrentWaza()') else c};")
            elif k == "swjump":
                c, _ = self.ex(s[1])
                out += [f"{pad}switch ((long){self.par(c, s[1], 11)})", pad + "{"]
                groups = {}
                for v, l in s[2]:
                    groups.setdefault(l, []).append(v)
                for l, vs in groups.items():
                    out.append(f"{pad}    " + " ".join(f"case {v}:" for v in vs) + f" goto {short_label(l)};")
                out += [f"{pad}    default: goto {short_label(s[3])};", pad + "}"]
            elif k == "if":
                self.emit_if(s, ind, out, False)
        return out

    def emit_if(self, s, ind, out, is_elif):
        pad, c, th, el = "    " * ind, self.cond(s[1]), s[2], s[3]
        if len(th) == 1 and th[0][0] in ("goto", "return") and el is None and not is_elif and (th[0][0] == "goto" or th[0][1] is None):
            out.append(f"{pad}if ({c}) " + (f"goto {short_label(th[0][1])};" if th[0][0] == "goto" else "return;"))
            return
        out += [f"{pad}else if ({c})" if is_elif else f"{pad}if ({c})", pad + "{"] + self.emit_list(th, ind + 1) + [pad + "}"]
        if el:
            if len(el) == 1 and el[0][0] == "if":
                self.emit_if(el[0], ind, out, True)
            else:
                out += [pad + "else", pad + "{"] + self.emit_list(el, ind + 1) + [pad + "}"]

    def iter_all(self, lst):
        for s in lst:
            yield s
            if s[0] == "if":
                yield from self.iter_all(s[2])
                yield from self.iter_all(s[3] or [])
            elif s[0] == "switch":
                yield from self.iter_all(s[2])

    def run(self, fn_rets, cmdnames):
        self.fn_rets, self.cmdnames, self.ptypes = fn_rets, cmdnames, {}
        plist = []
        for p in [x.strip() for x in self.fn["params"].split(",") if x.strip() and x.strip() != "void"]:
            ty, nm = p.rsplit(" ", 1)
            if nm != "param_1":
                ty = CT[ty.replace("*", "").strip()]
                self.ptypes[nm] = promote(ty)
                plist.append(f"{ty} {nm}")
        rt = CT.get(self.fn["ret"], self.fn["ret"])
        self.fn_ret = promote(rt) if rt != "void" else "void"
        used = set()
        for s in self.iter_all(self.body):
            if s[0] in ("expr", "if", "switch") or (s[0] == "return" and s[1] is not None):
                used.update(ids_of(s[1]))
        self.count_gotos(self.body, self.total)
        flat = self.flatten(self.body)
        refs = {}
        self.count_gotos(flat, refs)
        lines = self.emit_list(self.drop_labels(flat, refs), 2)
        grouped = {}
        for v in sorted(used):
            if v.startswith("param_"):
                continue
            if v in self.decls and not self.decls[v][1]:
                t = CT[self.decls[v][0]]
                grouped.setdefault(t, []).append(v + (" = false" if t == "bool" else " = 0"))
            elif v.endswith("A") and v[:-1] in self.decls:
                grouped.setdefault("long[]", []).append(v + " = null")
        out = [f"        {self.fn_ret} {self.fn['name']}({', '.join(plist)})", "        {"]
        out += [f"        {t} {', '.join(names)};" for t, names in grouped.items()] + lines
        if self.fn_ret != "void":
            out.append("            throw new InvalidOperationException();")
        return out + ["        }"]
