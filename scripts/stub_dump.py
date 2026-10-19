"""Parser und Index fuer den Il2CppDumper-Dump (dump.cs). Nur Typkoepfe, Felder und Enum-Werte, keine Methoden.

Gehoert zu scripts/stub_gen.py. Der Dump selbst liegt lokal unter work/ und nie im Repo.
"""
import collections
import contextlib
import re

IMAGE_RE = re.compile(r"^// Image (\d+): (.+)\.dll - (\d+)$")
NS_RE = re.compile(r"^// Namespace: ?(.*)$")
HEAD_RE = re.compile(
    r"^(?P<mods>(?:\w+\s+)*?)(?P<kind>class|struct|enum|interface)\s+(?P<rest>.*?)\s*//\s*TypeDefIndex:\s*(?P<idx>\d+)\s*$")
FIELD_MODS = {"public", "private", "protected", "internal", "static", "readonly", "const", "volatile", "new", "event"}
ATTR_NAME_RE = re.compile(r"\[(\w+)")

# Reihenfolge fuer die Aufloesung gleichnamiger Typen ueber Assembly-Grenzen (Engine vor Spielcode)
IMAGE_RANK = ["UnityEngine.UI", "Unity.TextMeshPro", "Unity.Timeline"]


def split_top(s, sep=","):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "<[":
            depth += 1
        elif ch in ">]":
            depth -= 1
        if ch == sep and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def strip_generics(name):
    prev = None
    while prev != name:
        prev = name
        name = re.sub(r"<[^<>]*>", "", name)
    return name


def split_generic(name):
    """'Foo<A, B>' -> ('Foo', ['A', 'B']); 'Outer.Inner' bleibt ungeteilt."""
    name = name.strip()
    if "<" not in name or not name.endswith(">"):
        return name, []
    i = name.index("<")
    return name[:i], split_top(name[i + 1:-1])


class DumpType:
    __slots__ = ("kind", "ns", "name", "gen", "bases", "fields", "enum_values", "enum_base", "image", "idx",
                 "attrs", "mods", "outer", "methods")

    def __init__(self):
        self.fields = []
        self.enum_values = []
        self.enum_base = "int"
        self.bases = []
        self.gen = []
        self.attrs = set()
        self.outer = None
        self.methods = 0

    @property
    def full(self):
        return (self.ns + "." + self.name) if self.ns else self.name

    @property
    def arity(self):
        return len(self.gen)

    @property
    def is_abstract(self):
        return "abstract" in self.mods.split()


def _open_lines(src):
    """Dateipfad oder bereits vorhandene Zeilenliste (fuer Tests mit synthetischem Dump)."""
    if isinstance(src, str):
        return open(src, encoding="utf-8", errors="replace")
    return contextlib.nullcontext(src)


def parse_dump(path):
    images = []
    types = []
    ns = ""
    cur = None
    pending = []
    fpending = []
    last_by_name = {}
    with _open_lines(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            if line[0] != "\t":
                m = IMAGE_RE.match(line)
                if m:
                    images.append((int(m.group(3)), m.group(2)))
                    continue
                m = NS_RE.match(line)
                if m:
                    ns = m.group(1).strip()
                    pending = []
                    continue
                if line.startswith("["):
                    pending.extend(ATTR_NAME_RE.findall(line.split("//")[0]))
                    continue
                if line in ("{", "}", "{}"):
                    continue
                m = HEAD_RE.match(line)
                if m:
                    t = DumpType()
                    t.kind = m.group("kind")
                    t.mods = m.group("mods") or ""
                    t.idx = int(m.group("idx"))
                    t.attrs = set(pending)
                    pending = []
                    rest = m.group("rest")
                    head, bases = rest, ""
                    depth = 0
                    for i, ch in enumerate(rest):
                        if ch in "<[":
                            depth += 1
                        elif ch in ">]":
                            depth -= 1
                        elif ch == ":" and depth == 0:
                            head, bases = rest[:i].strip(), rest[i + 1:].strip()
                            break
                    t.bases = split_top(bases)
                    gen = []
                    last = head.rpartition(".")[2] if "<" not in head.rpartition(".")[2] or ">" in head.rpartition(".")[2] else head
                    for g in re.findall(r"<([^<>]*)>", last):
                        gen.extend(x.strip() for x in g.split(","))
                    t.gen = gen
                    t.name = strip_generics(head).strip()
                    t.ns = ns
                    t.image = None
                    if "." in t.name:
                        outer = last_by_name.get(t.name.rpartition(".")[0])
                        if outer is not None:
                            t.outer = outer
                            t.ns = outer.ns
                    last_by_name[t.name] = t
                    types.append(t)
                    cur = t
                    fpending = []
                continue
            if cur is None or line.startswith("\t\t"):
                continue
            s = line.strip()
            if s.startswith("["):
                fpending.extend(ATTR_NAME_RE.findall(s.split("//")[0]))
                continue
            if s.startswith("//"):
                continue
            body = s.split("//")[0].strip()
            if "(" in body or "{" in body or not body.endswith(";"):
                if "(" in body and body.endswith("{ }"):
                    cur.methods += 1
                fpending = []
                continue
            body = body[:-1].strip()
            val = None
            if " = " in body:
                body, val = body.split(" = ", 1)
                val = val.strip()
            toks = body.split(" ")
            mods = []
            while toks and toks[0] in FIELD_MODS:
                mods.append(toks.pop(0))
            if len(toks) < 2 or "event" in mods:
                fpending = []
                continue
            fname = toks[-1]
            ftype = " ".join(toks[:-1]).strip()
            if cur.kind == "enum":
                if fname == "value__":
                    cur.enum_base = ftype
                elif "const" in mods and val is not None:
                    cur.enum_values.append((fname, val))
            else:
                cur.fields.append({"name": fname, "type": ftype, "attrs": sorted(set(fpending)), "mods": mods})
            fpending = []
    firsts = sorted(images)
    for t in types:
        img = None
        for first, n in firsts:
            if first <= t.idx:
                img = n
        t.image = img
    return types, images


class DumpIndex:
    """Suche nach Namen (mit Kontext) und Basisketten."""

    def __init__(self, types, images=None):
        self.types = types
        self.by_name = collections.defaultdict(list)
        self.by_key = {}
        for t in types:
            self.by_name[(t.name, t.arity)].append(t)
            self.by_key[(t.ns, t.name, t.arity)] = t

    @staticmethod
    def rank(t):
        img = t.image or ""
        if img in IMAGE_RANK:
            return IMAGE_RANK.index(img)
        if img.startswith("UnityEngine"):
            return 10
        return 20 if not img or img == "mscorlib" or img.startswith("System") else 30

    def resolve(self, name, ctx=None, pred=None):
        """Typname wie im Dump gedruckt (z. B. 'Foo', 'Outer.Inner', 'List<Foo>') -> DumpType oder None.
        pred filtert Kandidaten (z. B. nur UnityEngine.Object-Ableitungen, wenn der TypeTree einen PPtr zeigt)."""
        base, args = split_generic(name)
        arity = len(args)
        base = base.strip()
        if ctx is not None:
            o = ctx
            while o is not None:
                t = self.by_key.get((o.ns, o.name + "." + base, arity))
                if t:
                    return t
                o = o.outer
        cands = self.by_name.get((base, arity), [])
        if pred is not None:
            cands = [c for c in cands if pred(c)]
        if not cands and "." in base:
            ns, _, n = base.rpartition(".")
            t = self.by_key.get((ns, n, arity))
            if t:
                return t
        if len(cands) == 1:
            return cands[0]
        if not cands:
            return None
        if ctx is not None:
            parts = ctx.ns.split(".") if ctx.ns else []
            for k in range(len(parts), -1, -1):
                nsx = ".".join(parts[:k])
                same = [c for c in cands if c.ns == nsx]
                if len(same) == 1:
                    return same[0]
        best = min(self.rank(c) for c in cands)
        top = [c for c in cands if self.rank(c) == best]
        return top[0] if len(top) == 1 else None

    def base_of(self, t):
        """Direkte Basisklasse (DumpType), Name (unbekannt) oder None."""
        if t.kind != "class" or not t.bases:
            return None
        b = t.bases[0]
        r = self.resolve(b, t)
        if r is not None:
            return None if r.kind == "interface" else r
        if re.match(r"^I[A-Z]\w*(<.*>)?$", b):
            return None
        return b

    def chain(self, t):
        """[t, Basis1, ...]; letztes Element ggf. ein Name-String (nicht aufloesbar)."""
        out = [t]
        seen = {id(t)}
        cur = t
        while True:
            b = self.base_of(cur)
            if b is None:
                break
            if isinstance(b, str):
                out.append(b)
                break
            if id(b) in seen:
                break
            seen.add(id(b))
            out.append(b)
            cur = b
        return out

    def is_unity_object(self, t):
        return any(not isinstance(c, str) and c.full == "UnityEngine.Object" for c in self.chain(t))
