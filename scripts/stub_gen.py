#!/usr/bin/env python3
"""Stub-Generator: C#-Stubs fuer Assembly-CSharp aus TypeTree-Daten (Bundles) und Il2Cpp-Dump.

Zweck: Original-Szenen/-Prefabs/-Bundles sollen mit intakter Verdrahtung laden. Unity bindet ein
MonoBehaviour ueber (Assembly, Namespace, Klassenname) und gleicht die serialisierten Felder per
Name ab. Dieses Werkzeug erzeugt dafuer Klassen OHNE Logik. Die Ausgabe ist generiert, deterministisch
und gehoert nicht ins Repo (nur dieser Generator und seine Tests).

Unterbefehle (Ausgaben nur unter work/):
    scan    Bundles/Player-Dateien lesen (UnityPy, tools/pydeps): Skript-Klassen, Instanzen, TypeTree-Schemata
            -> work/stubs/scan.json
    gen     scan.json (+ dump.cs) -> <Ziel>/Assets/XnuStubs/*.cs, manifest.json, report.json/.md
    stats   Zahlen aus scan.json (Klassen, Instanzen, Typkategorien, Abdeckung ohne dump.cs, Priorisierung)
    conflicts  gleiche volle Typnamen in handgeschriebenem Code und im Stub-Manifest

Beispiel:
    python3 scripts/stub_gen.py scan
    python3 scripts/stub_gen.py gen --out work/unity-stubs/Assets/XnuStubs
    python3 scripts/stub_gen.py gen --out ... --dry-run
"""
import argparse
import collections
import hashlib
import json
import os
import re
import struct
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stub_dump import DumpIndex, parse_dump, split_generic  # noqa: E402,F401
DATA = os.path.join(ROOT, "work", "romfs", "Data")
ASSETS = os.path.join(DATA, "StreamingAssets", "AssetAssistant")
DEFAULT_DUMP = os.path.join(ROOT, "work", "il2cpp", "dump.cs")
DEFAULT_SCAN = os.path.join(ROOT, "work", "stubs", "scan.json")
TARGET_ASSEMBLY = "Assembly-CSharp"
PLAYER_FILES = ["globalgamemanagers", "globalgamemanagers.assets", "level0", "sharedassets0.assets", "resources.assets"]

# Assemblies, deren Typen im Zielprojekt als Paket/Engine vorhanden sind (werden nicht gestubbt)
PROVIDED_IMAGES = {
    "mscorlib", "System", "System.Core", "System.Xml", "System.Configuration", "Mono.Security",
    "UnityEngine", "UnityEngine.UI", "Unity.TextMeshPro", "Unity.Timeline",
}
PROVIDED_PREFIXES = ("UnityEngine.",)
# Assemblies, die der Generator selbst als minimale Stubs erzeugt (kein Paket vorhanden)
STUB_IMAGES = {"Assembly-CSharp", "DOTween", "DOTweenPro", "AssetAssistant", "nn", "DebugLog"}

PRIMITIVE = {
    "SInt8": "sbyte", "UInt8": "byte", "SInt16": "short", "UInt16": "ushort", "SInt32": "int", "int": "int",
    "UInt32": "uint", "unsigned int": "uint", "SInt64": "long", "UInt64": "ulong", "float": "float",
    "double": "double", "bool": "bool", "char": "char", "string": "string",
}
# Unity-Serialisierungsname -> C#-Typ (exakte Struktur, kein Hilfstyp noetig)
UNITY_BUILTIN = {
    "Vector2f": "Vector2", "Vector3f": "Vector3", "Vector4f": "Vector4", "Quaternionf": "Quaternion",
    "ColorRGBA": "Color", "Rectf": "Rect", "AABB": "Bounds", "Matrix4x4f": "Matrix4x4",
    "AnimationCurve": "AnimationCurve", "Gradient": "Gradient", "Hash128": "Hash128",
    "int2_storage": "Vector2Int", "int3_storage": "Vector3Int", "RectInt": "RectInt",
    "BoundsInt": "BoundsInt", "BitField": "LayerMask",
}
CS_KEYWORDS = {
    "abstract", "as", "base", "bool", "break", "byte", "case", "catch", "char", "checked", "class", "const",
    "continue", "decimal", "default", "delegate", "do", "double", "else", "enum", "event", "explicit",
    "extern", "false", "finally", "fixed", "float", "for", "foreach", "goto", "if", "implicit", "in", "int",
    "interface", "internal", "is", "lock", "long", "namespace", "new", "null", "object", "operator", "out",
    "override", "params", "private", "protected", "public", "readonly", "ref", "return", "sbyte", "sealed",
    "short", "sizeof", "stackalloc", "static", "string", "struct", "switch", "this", "throw", "true", "try",
    "typeof", "uint", "ulong", "unchecked", "unsafe", "ushort", "using", "virtual", "void", "volatile", "while",
}


# ---------------------------------------------------------------- TypeTree-Hilfen
def node_to_list(n):
    """UnityPy-TypeTreeNode -> [Typ, Name, MetaFlag, ByteSize, [Kinder]] (kompakt, JSON-faehig)."""
    return [n.m_Type, n.m_Name, int(n.m_MetaFlag), int(n.m_ByteSize), [node_to_list(c) for c in n.m_Children]]


def schema_hash(tree):
    return hashlib.md5(json.dumps(tree, separators=(",", ":")).encode()).hexdigest()[:16]


def is_bool(node):
    return bool(node[2] & 0x4000)


def child(node, name):
    for c in node[4]:
        if c[1] == name:
            return c
    return None


def top_fields(tree):
    """Top-Level-Felder einer MonoBehaviour-Schema-Wurzel ohne die Unity-Basisfelder."""
    skip = {"m_GameObject", "m_Enabled", "m_Script", "m_Name", "m_EditorHideFlags", "m_EditorClassIdentifier",
            "m_ObjectHideFlags", "m_CorrespondingSourceObject", "m_PrefabInstance", "m_PrefabAsset"}
    out = []
    for c in tree[4]:
        out.append(c)
    return out, skip


# ---------------------------------------------------------------- scan (UnityPy)
def group_of(path):
    rel = os.path.relpath(path, ASSETS)
    parts = rel.split(os.sep)
    if parts[0] == "..":
        return "Player"
    return parts[0]


def _resolve_script(sf, st, cab_names):
    """(cab, path_id) des MonoScripts eines SerializedType."""
    idx = st.script_type_index
    if idx is None or idx < 0 or not sf.script_types or idx >= len(sf.script_types):
        return None
    sc = sf.script_types[idx]
    fi = sc.local_serialized_file_index
    if fi == 0:
        return (cab_names[0], sc.local_identifier_in_file)
    ext = sf.externals[fi - 1] if fi - 1 < len(sf.externals) else None
    if ext is None:
        return None
    return (os.path.basename(str(ext.path)).lower() if hasattr(ext, "path") else None, sc.local_identifier_in_file)


def scan_file(path):
    """Eine Bundle-/Player-Datei lesen. Rueckgabe: dict (nur Strukturen, keine Inhalte)."""
    sys.path.insert(0, os.path.join(ROOT, "tools", "pydeps"))
    import UnityPy
    res = {"path": path, "group": group_of(path), "scripts": {}, "uses": [], "schemas": {}, "scene": False,
           "container": 0, "objects": 0, "cabs": [], "deps": [], "error": None}
    try:
        env = UnityPy.load(path)
    except Exception as e:  # noqa: BLE001
        res["error"] = "load:" + type(e).__name__
        return res
    files = []
    for f in env.files.values():
        if getattr(f, "objects", None) is not None:
            files.append(f)
        elif getattr(f, "files", None):
            files.extend(x for x in f.files.values() if getattr(x, "objects", None) is not None)
    for sf in files:
        cab = os.path.basename(str(getattr(sf, "name", "") or "")).lower()
        res["cabs"].append(cab)
        for ext in (sf.externals or []):
            en = os.path.basename(str(getattr(ext, "path", "") or "")).lower()
            if en.startswith("cab-") and en not in res["deps"]:
                res["deps"].append(en)
        counts = collections.Counter()
        comp = collections.Counter()
        sts = {}
        for pid, o in (sf.objects or {}).items():
            res["objects"] += 1
            cid = o.type.name
            if cid == "MonoScript":
                try:
                    s = o.read()
                    res["scripts"]["%s|%d" % (cab, pid)] = [s.m_AssemblyName, s.m_Namespace, s.m_ClassName]
                except Exception:  # noqa: BLE001
                    pass
            elif cid == "AssetBundle":
                try:
                    a = o.read()
                    res["container"] += len(a.m_Container)
                    res["scene"] = res["scene"] or bool(getattr(a, "m_IsStreamedSceneAssetBundle", False))
                except Exception:  # noqa: BLE001
                    pass
            elif cid == "MonoBehaviour":
                st = o.serialized_type
                if st is None:
                    continue
                key = id(st)
                sts[key] = st
                counts[key] += 1
                try:
                    raw = o.get_raw_data()[:12]
                    fid, gid = struct.unpack("<iq", raw)
                    if gid != 0:
                        comp[key] += 1
                except Exception:  # noqa: BLE001
                    pass
        for key, st in sts.items():
            ref = _resolve_script(sf, st, [cab])
            tree = node_to_list(st.node) if st.node is not None and st.node.m_Children else None
            h = None
            if tree is not None:
                h = schema_hash(tree)
                res["schemas"][h] = tree
            res["uses"].append({"script": "%s|%s" % ref if ref else None, "n": counts[key], "comp": comp[key],
                                "schema": h, "cab": cab})
    return res


def list_scan_files(assets=ASSETS):
    out = []
    for dp, dn, fn in os.walk(assets):
        dn.sort()
        for f in sorted(fn):
            if f.endswith((".manifest", ".json", ".txt", ".DS_Store")):
                continue
            p = os.path.join(dp, f)
            try:
                with open(p, "rb") as fh:
                    if fh.read(7) != b"UnityFS":
                        continue
            except OSError:
                continue
            out.append(p)
    return out


def _init_roots(assets):
    """Wurzeln setzen (auch in Pool-Prozessen: macOS startet sie per spawn)."""
    global ASSETS, DATA
    ASSETS = os.path.abspath(assets)
    DATA = os.path.dirname(os.path.dirname(ASSETS))


def cmd_scan(a):
    import multiprocessing as mp
    _init_roots(a.assets)
    files = [os.path.join(DATA, f) for f in PLAYER_FILES if os.path.exists(os.path.join(DATA, f))]
    files += list_scan_files(a.assets)
    if a.limit:
        files = files[:a.limit]
    print("scan: %d Dateien" % len(files), flush=True)
    results = []
    with mp.Pool(a.jobs, maxtasksperchild=40, initializer=_init_roots, initargs=(a.assets,)) as pool:
        for i, r in enumerate(pool.imap_unordered(scan_file, files, chunksize=1)):
            results.append(r)
            if (i + 1) % 500 == 0:
                print("  %d/%d" % (i + 1, len(files)), flush=True)
    results.sort(key=lambda r: r["path"])
    out = aggregate_scan(results)
    os.makedirs(os.path.dirname(a.scan), exist_ok=True)
    with open(a.scan, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print("geschrieben:", a.scan)
    print_stats(out)


def aggregate_scan(results):
    """Pro-Datei-Ergebnisse -> klassenweise Aggregation (deterministisch)."""
    scripts = {}
    for r in results:
        scripts.update(r["scripts"])
    classes = {}
    schemas = {}
    errors = collections.Counter()
    unresolved = collections.Counter()
    groups = collections.defaultdict(lambda: {"files": 0, "scene_files": 0, "container": 0, "objects": 0})
    for r in results:
        g = groups[r["group"]]
        g["files"] += 1
        g["scene_files"] += 1 if r["scene"] else 0
        g["container"] += r["container"]
        g["objects"] += r["objects"]
        if r["error"]:
            errors[r["error"]] += 1
        for u in r["uses"]:
            sref = u["script"]
            info = scripts.get(sref) if sref else None
            if info is None:
                unresolved[r["group"]] += u["n"]
                key = "?|?|?"
            else:
                key = "%s|%s|%s" % tuple(info)
            c = classes.setdefault(key, {"instances": 0, "components": 0, "bundles": 0, "groups": {}, "schemas": {}})
            c["instances"] += u["n"]
            c["components"] += u["comp"]
            c["bundles"] += 1
            gg = c["groups"].setdefault(r["group"], {"bundles": 0, "instances": 0, "components": 0, "scene_bundles": 0})
            gg["bundles"] += 1
            gg["instances"] += u["n"]
            gg["components"] += u["comp"]
            gg["scene_bundles"] += 1 if r["scene"] else 0
            h = u["schema"]
            if h:
                c["schemas"][h] = c["schemas"].get(h, 0) + u["n"]
                schemas[h] = r["schemas"][h]
            else:
                c["schemas"]["-"] = c["schemas"].get("-", 0) + u["n"]
    all_scripts = collections.Counter()
    for info in scripts.values():
        all_scripts["%s|%s|%s" % tuple(info)] += 1
    bundles = {}
    for r in results:
        if r["cabs"]:
            names = set()
            for u in r["uses"]:
                info = scripts.get(u["script"]) if u["script"] else None
                if info is not None and info[0] == "Assembly-CSharp.dll":
                    names.add("%s|%s|%s" % tuple(info))
            bundles[os.path.relpath(r["path"], ASSETS)] = {"cabs": r["cabs"], "deps": r["deps"], "classes": sorted(names)}
    return {"version": 1, "classes": classes, "schemas": schemas, "groups": groups, "errors": dict(errors),
            "unresolved_instances": dict(unresolved), "script_objects": {k: v for k, v in sorted(all_scripts.items())},
            "files": len(results), "bundles": bundles}


# ---------------------------------------------------------------- Typ-Abbildung
def classify(node):
    """TypeTree-Knoten -> Kategorie (Zaehlung 'ohne dump.cs'): prim|unity|pptr|array|string|class|event|enumint."""
    t = node[0]
    if t in PRIMITIVE and not node[4]:
        return "prim"
    if t == "string":
        return "string"
    if t == "Array" or (node[4] and node[4][0][0] == "Array" and node[4][0][1] == "Array"):
        return "array"
    if t.startswith("PPtr<"):
        return "pptr"
    if t in UNITY_BUILTIN:
        return "unity"
    if node[4] and child(node, "m_PersistentCalls") is not None:
        return "event"
    if node[4]:
        return "class"
    return "unknown"


def csharp_ident(name):
    n = re.sub(r"[^\w]", "_", name)  # \w ist Unicode-faehig: C# erlaubt Buchstaben/Ziffern aller Schriften
    if not n or n[0].isdigit():
        n = "_" + n
    if n in CS_KEYWORDS:
        n = "@" + n
    return n


# ---------------------------------------------------------------- Generator
UNITY_OBJECTS = {  # Engine-Klassen, auf die PPtr<$Name> ohne dump.cs aufgeloest werden kann
    "Object": "UnityEngine.Object", "GameObject": "UnityEngine.GameObject", "Component": "UnityEngine.Component",
    "Transform": "UnityEngine.Transform", "RectTransform": "UnityEngine.RectTransform", "Sprite": "UnityEngine.Sprite",
    "Texture": "UnityEngine.Texture", "Texture2D": "UnityEngine.Texture2D", "Material": "UnityEngine.Material",
    "Mesh": "UnityEngine.Mesh", "AudioClip": "UnityEngine.AudioClip", "AnimationClip": "UnityEngine.AnimationClip",
    "RuntimeAnimatorController": "UnityEngine.RuntimeAnimatorController", "Animator": "UnityEngine.Animator",
    "Camera": "UnityEngine.Camera", "Canvas": "UnityEngine.Canvas", "CanvasGroup": "UnityEngine.CanvasGroup",
    "Renderer": "UnityEngine.Renderer", "MeshRenderer": "UnityEngine.MeshRenderer",
    "SkinnedMeshRenderer": "UnityEngine.SkinnedMeshRenderer", "MeshFilter": "UnityEngine.MeshFilter",
    "ScriptableObject": "UnityEngine.ScriptableObject", "MonoBehaviour": "UnityEngine.MonoBehaviour",
    "Behaviour": "UnityEngine.Behaviour", "Collider": "UnityEngine.Collider", "BoxCollider": "UnityEngine.BoxCollider",
    "Light": "UnityEngine.Light", "AvatarMask": "UnityEngine.AvatarMask", "Font": "UnityEngine.Font",
    "ParticleSystem": "UnityEngine.ParticleSystem", "Shader": "UnityEngine.Shader", "TextAsset": "UnityEngine.TextAsset",
    "VideoClip": "UnityEngine.Video.VideoClip", "Rigidbody": "UnityEngine.Rigidbody",
    "Image": "UnityEngine.UI.Image", "RawImage": "UnityEngine.UI.RawImage", "Text": "UnityEngine.UI.Text",
    "Slider": "UnityEngine.UI.Slider", "Selectable": "UnityEngine.UI.Selectable", "Button": "UnityEngine.UI.Button",
    "Toggle": "UnityEngine.UI.Toggle", "ScrollRect": "UnityEngine.UI.ScrollRect",
    "TextMeshProUGUI": "TMPro.TextMeshProUGUI", "TMP_Text": "TMPro.TMP_Text", "TMP_FontAsset": "TMPro.TMP_FontAsset",
    "SpriteAtlas": "UnityEngine.U2D.SpriteAtlas",
}
UNITY_BUILTIN_FQ = {
    "Vector2": "UnityEngine.Vector2", "Vector3": "UnityEngine.Vector3", "Vector4": "UnityEngine.Vector4",
    "Quaternion": "UnityEngine.Quaternion", "Color": "UnityEngine.Color", "Rect": "UnityEngine.Rect",
    "Bounds": "UnityEngine.Bounds", "Matrix4x4": "UnityEngine.Matrix4x4", "AnimationCurve": "UnityEngine.AnimationCurve",
    "Gradient": "UnityEngine.Gradient", "Hash128": "UnityEngine.Hash128", "Vector2Int": "UnityEngine.Vector2Int",
    "Vector3Int": "UnityEngine.Vector3Int", "RectInt": "UnityEngine.RectInt", "BoundsInt": "UnityEngine.BoundsInt",
    "LayerMask": "UnityEngine.LayerMask", "Color32": "UnityEngine.Color32",
}
CS_PRIMS = {"int", "uint", "short", "ushort", "long", "ulong", "byte", "sbyte", "float", "double", "bool", "char", "string"}
ENUM_BASES = {"int", "uint", "short", "ushort", "long", "ulong", "byte", "sbyte"}
BUILTIN_FIELDS = {"m_GameObject", "m_Enabled", "m_Script", "m_Name", "m_EditorHideFlags", "m_EditorClassIdentifier",
                  "m_ObjectHideFlags"}
AUTO_NS = "Xnu.Stubs.Auto"
# Ordnernamen mit Sonderbedeutung in Unity (Editor-Assembly, Resources usw.) werden im Pfad entschaerft
SPECIAL_DIRS = {"editor", "plugins", "resources", "gizmos", "streamingassets", "standard assets", "editor default resources",
                "webgltemplates", "pro standard assets"}


def array_parts(node):
    """Knoten eines Arrays/Listen-Feldes -> Elementknoten oder None. Der Knotentyp ist dabei der Elementtyp."""
    if node[0] != "string" and len(node[4]) == 1 and node[4][0][0] == "Array" and node[4][0][1] == "Array":
        arr = node[4][0]
        if len(arr[4]) == 2:
            return arr[4][1]
    return None


def is_string_node(node):
    return node[0] == "string"


class Unit:
    """Ein zu erzeugender Typ (Klasse, Struct, Enum)."""

    def __init__(self, ns, name, kind, gen=()):
        self.ns, self.name, self.kind, self.gen = ns, name, kind, list(gen)
        self.base = None
        self.abstract = False
        self.flags = False
        self.serializable = False
        self.fields = collections.OrderedDict()  # Name -> dict(type, public, source)
        self.enum_base = "int"
        self.enum_values = []
        self.origin = "ref"
        self.source = "dump"
        self.shell = False
        self.dt = None
        self.asm = TARGET_ASSEMBLY
        self.dump_fields_done = False
        self.instances = 0
        self.attrs = set()

    @property
    def full(self):
        return (self.ns + "." + self.name) if self.ns else self.name


class Generator:
    def __init__(self, scan, index=None, use_dump=True):
        self.scan = scan
        self.index = index if use_dump else None
        self.units = {}
        self.stats = collections.Counter()
        self.gaps = collections.Counter()
        self.gap_examples = collections.defaultdict(set)
        self.script_units = {}
        self.manifest_classes = {}
        self.cur_asm = TARGET_ASSEMBLY
        self.edges = set()
        self.class_info = {}
        self.class_gaps = {}

    # -- Aufloesung -------------------------------------------------------
    def hoisted(self, dt):
        """Typen, die in einer generischen Aussenklasse stehen, werden als eigene Top-Level-Typen erzeugt."""
        o = dt.outer
        while o is not None:
            if o.arity:
                return True
            o = o.outer
        return False

    def fq(self, dt):
        if self.hoisted(dt):
            return "global::" + ((dt.ns + ".") if dt.ns else "") + dt.name.replace(".", "_")
        return "global::" + dt.full

    def is_provided(self, dt):
        img = dt.image or ""
        return img in PROVIDED_IMAGES or img.startswith("UnityEngine") or img.startswith("System")

    def unit_for(self, dt, kind=None):
        key = (dt.ns, dt.name, dt.arity)
        u = self.units.get(key)
        if u is None:
            u = Unit(dt.ns, dt.name.replace(".", "_") if self.hoisted(dt) else dt.name, kind or dt.kind,
                     [] if dt.kind == "enum" else dt.gen)
            u.abstract = dt.is_abstract
            u.flags = "Flags" in dt.attrs
            u.serializable = "Serializable" in dt.attrs
            u.attrs = set(dt.attrs)
            u.asm = dt.image if dt.image in STUB_IMAGES else TARGET_ASSEMBLY
            self.units[key] = u
            u.dt = dt
            self.note_edge(u)
            base = self.index.base_of(dt) if self.index and dt.kind == "class" else None
            prev, self.cur_asm = self.cur_asm, u.asm
            try:
                u.base = self.render_base(dt, base) if base else None
            finally:
                self.cur_asm = prev
            if dt.kind == "enum":
                u.enum_base = dt.enum_base if dt.enum_base in ENUM_BASES else "int"
                u.enum_values = list(dt.enum_values)
                u.origin = "enum"
            if dt.outer is not None and not self.is_provided(dt.outer):
                self.unit_for(dt.outer)
        else:
            self.note_edge(u)
        return u

    def note_edge(self, u):
        if u.asm != self.cur_asm:
            self.edges.add((self.cur_asm, u.asm))

    def render_base(self, dt, base):
        if isinstance(base, str):
            self.gaps["base_unresolved"] += 1
            return None
        if self.is_provided(base) or base.image not in STUB_IMAGES and base.image is not None:
            b = self.fq(base) if base.arity == 0 else self.generic_name(base, self.base_args(dt), dt)
            return b
        self.unit_for(base)
        if base.arity == 0:
            return self.fq(base)
        return self.generic_name(base, self.base_args(dt), dt)

    def base_args(self, dt):
        _, args = split_generic(dt.bases[0]) if dt.bases else (None, [])
        return args

    def generic_name(self, base, args, ctx):
        out = []
        for a in args:
            r = self.render(None, a, ctx, 0)
            out.append(r or "object")
        return "%s<%s>" % (self.fq(base), ", ".join(out))

    def render(self, node, dtype, ctx, depth):
        """C#-Typ (voll qualifiziert) fuer ein Feld oder None. node = TypeTree-Knoten oder None, dtype = Dump-Typtext oder None."""
        if dtype is not None and self.index is not None:
            r = self.render_dump(node, dtype, ctx, depth)
            if r is not None:
                return r
            if node is not None:
                self.stats["dump_fallback_typetree"] += 1
        if node is not None:
            return self.render_node(node, ctx, depth)
        return None

    def render_dump(self, node, dtype, ctx, depth):
        dtype = dtype.strip()
        if ctx is not None and dtype in ctx.gen:
            return dtype
        if dtype.endswith("[]") and "[,]" not in dtype:
            elem = array_parts(node) if node is not None else None
            if node is not None and elem is None and not is_string_node(node):
                return None
            r = self.render_dump(elem, dtype[:-2], ctx, depth)
            return r + "[]" if r else None
        if dtype in CS_PRIMS:
            if node is not None and classify(node) not in ("prim", "string"):
                return None
            return dtype
        base, args = split_generic(dtype)
        if base == "List" and len(args) == 1:
            elem = array_parts(node) if node is not None else None
            if node is not None and elem is None:
                return None
            r = self.render_dump(elem, args[0], ctx, depth)
            return "global::System.Collections.Generic.List<%s>" % r if r else None
        pred = self.index.is_unity_object if (node is not None and classify(node) == "pptr") else None
        dt = self.index.resolve(dtype, ctx, pred)
        if dt is None:
            return None
        if dt.kind == "interface":
            return None
        if dt.kind == "enum":
            if node is not None and classify(node) != "prim":
                return None
            if self.is_provided(dt):
                return self.fq(dt)
            self.unit_for(dt)
            return self.fq(dt)
        cat = classify(node) if node is not None else None
        if self.is_provided(dt):
            if dt.arity:
                gen = []
                for a in args:
                    ra = self.render_dump(None, a, ctx, depth)
                    if ra is None:
                        return None
                    gen.append(ra)
                if dt.name.startswith("UnityEvent") and cat not in (None, "event"):
                    return None
                return "%s<%s>" % (self.fq(dt), ", ".join(gen))
            if cat is not None and self.index.is_unity_object(dt) and cat != "pptr":
                return None
            if cat == "event" and not dt.name.endswith("Event") and dt.name != "UnityEvent":
                return None
            if cat == "prim":
                return None
            return self.fq(dt)
        # Spiel-/Stub-Typ
        if self.index.is_unity_object(dt):
            if cat not in (None, "pptr"):
                return None
            self.unit_for(dt)
            self.mark_ref(dt)
            return self.fq(dt)
        if dt.kind in ("class", "struct"):
            if cat in ("prim", "string", "pptr", "unity"):
                return None
            if cat is None and "Serializable" not in dt.attrs and dt.kind == "class":
                return None
            if dt.arity:
                gen = []
                for a in args:
                    ra = self.render_dump(None, a, ctx, depth)
                    if ra is None:
                        return None
                    gen.append(ra)
                self.unit_for(dt)
                return "%s<%s>" % (self.fq(dt), ", ".join(gen))
            self.fill_data(self.unit_for(dt), dt, node, depth + 1)
            return self.fq(dt)
        return None

    def mark_ref(self, dt):
        pass

    def render_node(self, node, ctx, depth):
        """Nur aus dem TypeTree (ohne dump.cs)."""
        t = node[0]
        if is_string_node(node):
            return "string"
        elem = array_parts(node)
        if elem is not None:
            r = self.render_node(elem, ctx, depth)
            return r + "[]" if r else None
        if not node[4]:
            if t in PRIMITIVE:
                if t == "UInt8" and is_bool(node):
                    return "bool"
                return PRIMITIVE[t]
            self.gaps["tt_unknown_leaf"] += 1
            return None
        if t.startswith("PPtr<"):
            name = t[5:-1].lstrip("$")
            if name in UNITY_OBJECTS:
                return "global::" + UNITY_OBJECTS[name]
            if self.index is not None:
                dt = self.index.resolve(name, ctx)
                if dt is not None and not self.is_provided(dt):
                    self.unit_for(dt)
                    return self.fq(dt)
                if dt is not None:
                    return self.fq(dt)
            self.gaps["pptr_target_unknown"] += 1
            self.gap_examples["pptr_target_unknown"].add(name)
            return "global::UnityEngine.Object"
        if t == "ColorRGBA" and child(node, "rgba") is not None:
            return "global::UnityEngine.Color32"
        if t in UNITY_BUILTIN:
            return "global::" + UNITY_BUILTIN_FQ[UNITY_BUILTIN[t]]
        if child(node, "m_PersistentCalls") is not None:
            return "global::UnityEngine.Events.UnityEvent"
        if t.startswith("managedReference"):
            self.gaps["managed_reference"] += 1
            return None
        if depth > 12:
            return None
        u = self.auto_unit(t, node, ctx, depth)
        return "global::" + u.full

    def auto_unit(self, tname, node, ctx, depth):
        """Verschachtelter [Serializable]-Typ nur aus dem TypeTree (Namespace unbekannt)."""
        name = csharp_ident(tname.replace("`", "_"))
        ns = AUTO_NS if self.cur_asm == TARGET_ASSEMBLY else AUTO_NS + "." + re.sub(r"[^0-9A-Za-z_]", "_", self.cur_asm)
        key = (ns, name, 0)
        u = self.units.get(key)
        if u is None:
            u = Unit(ns, name, "class")
            u.origin = "data"
            u.serializable = True
            u.source = "typetree"
            u.asm = self.cur_asm
            self.units[key] = u
        for c in node[4]:
            if c[1] in u.fields:
                continue
            r = self.render(c, None, None, depth + 1)
            if r is None:
                self.gaps["field_dropped"] += 1
                continue
            u.fields[c[1]] = {"type": r, "public": True, "source": "typetree"}
        return u

    # -- Felder -----------------------------------------------------------
    def fill_data(self, u, dt, node, depth):
        prev, self.cur_asm = self.cur_asm, u.asm
        try:
            self._fill_data(u, dt, node, depth)
        finally:
            self.cur_asm = prev

    def _fill_data(self, u, dt, node, depth):
        """[Serializable]-Klasse/Struct: Felder aus dem TypeTree-Knoten (bevorzugt) oder dem Dump."""
        if depth > 10:
            return
        u.origin = u.origin if u.origin in ("script", "chain") else "data"
        by_name = {f["name"]: f for f in dt.fields}
        if node is not None and node[4]:
            elem = array_parts(node)
            src = elem if elem is not None else node
            for c in src[4]:
                if c[1] in u.fields:
                    continue
                df = by_name.get(c[1])
                r = self.render(c, df["type"] if df else None, dt, depth)
                if r is None:
                    self.gaps["field_dropped"] += 1
                    continue
                u.fields[c[1]] = {"type": r, "public": df is None or "public" in df["mods"],
                                  "source": "typetree+dump" if df else "typetree"}
            u.dump_fields_done = True
        elif not u.dump_fields_done:
            u.dump_fields_done = True
            self.dump_only_fields(u, dt, depth)

    def serialized_in_dump(self, f):
        if "static" in f["mods"] or "const" in f["mods"] or "NonSerialized" in f["attrs"]:
            return False
        if "readonly" in f["mods"]:
            return False
        return "public" in f["mods"] or "SerializeField" in f["attrs"] or "SerializeReference" in f["attrs"]

    def dump_only_fields(self, u, dt, depth):
        prev, self.cur_asm = self.cur_asm, u.asm
        try:
            self._dump_only_fields(u, dt, depth)
        finally:
            self.cur_asm = prev

    def _dump_only_fields(self, u, dt, depth):
        for f in dt.fields:
            if f["name"] in u.fields or not self.serialized_in_dump(f):
                continue
            r = self.render(None, f["type"], dt, depth)
            if r is None:
                self.gaps["dump_field_unrenderable"] += 1
                continue
            u.fields[f["name"]] = {"type": r, "public": "public" in f["mods"], "source": "dump"}

    def add_script_class(self, key, info):
        """Skriptklasse aus dem Scan (Assembly|Namespace|Name) -> Unit."""
        asm, ns, name = key.split("|")
        asm = asm[:-4] if asm.endswith(".dll") else asm
        dt = self.index.by_key.get((ns, name, 0)) if self.index else None
        if dt is not None and self.is_provided(dt):
            self.stats["classes_provided_skipped"] += 1
            return None
        if dt is None and (asm in PROVIDED_IMAGES or asm.startswith("UnityEngine")):
            self.stats["classes_provided_skipped"] += 1
            return None
        dom = None
        schemas = [(n, h) for h, n in info["schemas"].items() if h != "-"]
        if schemas:
            dom = max(schemas)[1]
        tree = self.scan["schemas"].get(dom) if dom else None
        if dt is not None:
            u = self.unit_for(dt)
            if u.kind != "class":
                return None
        else:
            u = Unit(ns, csharp_ident(name), "class")
            u.source = "typetree"
            u.asm = asm if asm != "?" else TARGET_ASSEMBLY
            self.units[(ns, u.name, 0)] = u
            comp = info["components"]
            u.base = "global::UnityEngine.MonoBehaviour" if comp else "global::UnityEngine.ScriptableObject"
            self.stats["classes_without_dump"] += 1
        u.origin = "script"
        u.instances = info["instances"]
        u.shell = False
        u.serializable = True
        self.script_units[key] = (u, dt)
        if tree is None:
            if dt is not None:
                self.stats["classes_dump_only"] += 1
                chain = self.index.chain(dt)
                for c in chain:
                    if isinstance(c, str) or c.image not in STUB_IMAGES and c.image is not None:
                        break
                    cu = self.unit_for(c)
                    if cu is not u:
                        cu.origin = "chain" if cu.origin == "ref" else cu.origin
                    self.dump_only_fields(cu, c, 0)
            return u
        # TypeTree-Felder auf Basiskette verteilen
        flat = [c for c in tree[4] if c[1] not in BUILTIN_FIELDS]
        allt = [tree] + [self.scan["schemas"][h] for h in info["schemas"] if h not in ("-", dom)]
        for extra in allt[1:]:
            names = {c[1] for c in flat}
            flat.extend(c for c in extra[4] if c[1] not in BUILTIN_FIELDS and c[1] not in names)
            self.stats["schema_variants_merged"] += 1
        if dt is None:
            self.fill_typetree_only(u, flat)
            return u
        chain = self.index.chain(dt)
        owners = []
        for c in chain:
            if isinstance(c, str) or (c.image not in STUB_IMAGES and c.image is not None):
                break
            owners.append(c)
        assigned = {id(o): [] for o in owners}
        rest = list(flat)
        j = 0
        for node in reversed(flat):
            target = None
            for k in range(j, len(owners)):
                if any(f["name"] == node[1] for f in owners[k].fields):
                    target = k
                    break
            if target is None:
                break
            j = target
            assigned[id(owners[target])].append(node)
            rest.pop()
        external_prefix = rest
        external_base = chain[len(owners)] if len(owners) < len(chain) else None
        tail_base = (external_base.full if external_base is not None and not isinstance(external_base, str) else None)
        self.class_info[key] = {"tail_base": tail_base, "owners": len(owners), "external_prefix": len(external_prefix)}
        simple_bases = ("UnityEngine.MonoBehaviour", "UnityEngine.ScriptableObject", "UnityEngine.StateMachineBehaviour",
                        "UnityEngine.Behaviour", "UnityEngine.Object", None)
        self.cur_asm = u.asm
        if external_prefix:
            if tail_base in simple_bases:
                # Felder ohne Gegenstueck im Dump: auf der Blattklasse nachtragen (exakt wie serialisiert)
                for node in external_prefix:
                    r = self.render(node, None, dt, 0)
                    if r is None:
                        self.gaps["field_dropped"] += 1
                        continue
                    u.fields[node[1]] = {"type": r, "public": True, "source": "typetree"}
                    self.stats["orphan_fields_on_leaf"] += 1
            else:
                self.stats["fields_from_external_base"] += len(external_prefix)
        for o in owners:
            ou = self.unit_for(o)
            if ou is not u and ou.origin == "ref":
                ou.origin = "chain"
            by_name = {f["name"]: f for f in o.fields}
            self.cur_asm = ou.asm
            for node in reversed(assigned[id(o)]):
                if node[1] in ou.fields:
                    continue
                df = by_name[node[1]]
                r = self.render(node, df["type"], o, 0)
                if r is None:
                    self.gaps["field_dropped"] += 1
                    continue
                ou.fields[node[1]] = {"type": r, "public": "public" in df["mods"], "source": "typetree+dump"}
        self.cur_asm = TARGET_ASSEMBLY
        return u

    def fill_typetree_only(self, u, flat):
        self.cur_asm = u.asm
        try:
            self._fill_typetree_only(u, flat)
        finally:
            self.cur_asm = TARGET_ASSEMBLY

    def _fill_typetree_only(self, u, flat):
        for node in flat:
            r = self.render(node, None, None, 0)
            if r is None:
                self.gaps["field_dropped"] += 1
                continue
            u.fields[node[1]] = {"type": r, "public": True, "source": "typetree"}

    def run(self):
        watch = ("pptr_target_unknown", "field_dropped", "tt_unknown_leaf", "managed_reference", "dump_field_unrenderable")
        for key in sorted(self.scan["classes"]):
            asm = key.split("|", 1)[0]
            if asm == "?":
                continue
            info = self.scan["classes"][key]
            before = {k: self.gaps[k] for k in watch}
            self.add_script_class(key, info)
            delta = {k: self.gaps[k] - before[k] for k in watch if self.gaps[k] - before[k]}
            if delta:
                self.class_gaps[key] = delta
        self.finish_shells()
        return self

    def finish_shells(self):
        """Basisklassen/Referenzziele ohne Instanzen: Felder aus dem Dump nachtragen (nur Klassen der Ketten)."""
        pass


# ---------------------------------------------------------------- Emission
def cs_name(u):
    n = u.name.rpartition(".")[2]
    if u.gen:
        n += "<%s>" % ", ".join(u.gen)
    return n


def emit_unit(u, units_by_outer, indent=0):
    pad = "    " * indent
    lines = []
    if u.kind == "enum":
        if u.flags:
            lines.append(pad + "[global::System.Flags]")
        lines.append("%spublic enum %s : %s" % (pad, cs_name(u), u.enum_base))
        lines.append(pad + "{")
        seen = set()
        for n, v in u.enum_values:
            ident = csharp_ident(n)
            if ident in seen:
                continue
            seen.add(ident)
            lines.append("%s    %s = %s," % (pad, ident, v))
        lines.append(pad + "}")
        return lines
    if u.serializable or u.kind == "struct":
        lines.append(pad + "[global::System.Serializable]")
    kw = "struct" if u.kind == "struct" else "class"
    mod = "public abstract partial" if u.abstract and kw == "class" else "public partial"
    head = "%s%s %s %s" % (pad, mod, kw, cs_name(u))
    if u.base and kw == "class":
        head += " : " + u.base
    lines.append(head)
    lines.append(pad + "{")
    for fname, f in u.fields.items():
        ident = csharp_ident(fname)
        if f["public"]:
            lines.append("%s    public %s %s;" % (pad, f["type"], ident))
        else:
            lines.append("%s    [global::UnityEngine.SerializeField] private %s %s;" % (pad, f["type"], ident))
    for nu in sorted(units_by_outer.get(u.full, []), key=lambda x: x.name):
        lines.append("")
        lines.extend(emit_unit(nu, units_by_outer, indent + 1))
    lines.append(pad + "}")
    return lines


HEADER = ("// <auto-generated>\n// Von scripts/stub_gen.py erzeugt (TypeTree + Il2Cpp-Dump). Nicht bearbeiten, nicht einchecken.\n"
          "// Enthaelt nur serialisierte Felder, keine Logik.\n// </auto-generated>\n"
          "#pragma warning disable 0649, 0169, 0414, 0108, 0109, 0114, 0219, 0067, 0659, 0661\n")


def emit_all(gen):
    """Units -> {relativer Pfad: Dateitext}. Verschachtelte Typen liegen in der Datei ihres Aeusseren."""
    units = gen.units
    by_outer = collections.defaultdict(list)
    tops = []
    for key in sorted(units):
        u = units[key]
        if "." in u.name and getattr(u, "dt", None) is not None and u.dt.outer is not None \
                and (u.dt.outer.ns, u.dt.outer.name, u.dt.outer.arity) in units:
            by_outer[u.dt.outer.full].append(u)
        else:
            tops.append(u)
    files = {}
    used = {}
    for u in tops:
        body = emit_unit(u, by_outer)
        segs = u.ns.split(".") if u.ns else ["_global"]
        segs = [(s + "_") if s.lower() in SPECIAL_DIRS else s for s in segs]
        d = "/".join(segs)
        if u.asm != TARGET_ASSEMBLY:
            d = "_asm/%s/%s" % (u.asm, d)
        fname = re.sub(r"[^0-9A-Za-z_.`]", "_", u.name) + ("`%d" % len(u.gen) if u.gen else "")
        fname = fname.replace("`", "_G")
        path = "%s/%s.cs" % (d, fname)
        low = path.lower()
        n = 1
        while low in used:
            n += 1
            path = "%s/%s_%d.cs" % (d, fname, n)
            low = path.lower()
        used[low] = True
        text = HEADER
        if u.ns:
            text += "namespace %s\n{\n" % u.ns
            text += "\n".join(("    " + ln) if ln else ln for ln in body) + "\n}\n"
        else:
            text += "\n".join(body) + "\n"
        files[path] = text
    # Fremd-Assemblies: eine asmdef mit dem Originalnamen (Bindung ueber m_AssemblyName), autoReferenced fuer Assembly-CSharp
    asms = sorted({u.asm for u in units.values() if u.asm != TARGET_ASSEMBLY})
    for a in asms:
        refs = sorted(t for (f, t) in gen.edges if f == a and t != TARGET_ASSEMBLY and t != a)
        for (f, t) in gen.edges:
            if f == a and t == TARGET_ASSEMBLY:
                gen.stats["asm_violations"] += 1
        asmdef = collections.OrderedDict([
            ("name", a), ("rootNamespace", ""), ("references", refs), ("includePlatforms", []),
            ("excludePlatforms", []), ("allowUnsafeCode", False), ("overrideReferences", False),
            ("precompiledReferences", []), ("autoReferenced", True), ("defineConstraints", []),
            ("versionDefines", []), ("noEngineReferences", False)])
        files["_asm/%s/%s.asmdef" % (a, a)] = json.dumps(asmdef, indent=2) + "\n"
    return files


def print_stats(scan):
    cl = scan["classes"]
    by_asm = collections.defaultdict(lambda: [0, 0, 0])
    for k, c in cl.items():
        asm = k.split("|", 1)[0]
        by_asm[asm][0] += 1
        by_asm[asm][1] += c["instances"]
        by_asm[asm][2] += c["components"]
    print("Klassen mit Instanzen: %d, Instanzen: %d" % (len(cl), sum(c["instances"] for c in cl.values())))
    for asm, v in sorted(by_asm.items(), key=lambda kv: -kv[1][1]):
        print("  %-28s Klassen %5d  Instanzen %8d  Komponenten %8d" % (asm, v[0], v[1], v[2]))


def build_manifest(gen, files):
    classes = []
    for key in sorted(gen.units):
        u = gen.units[key]
        classes.append({
            "namespace": u.ns, "name": u.name, "kind": u.kind, "origin": u.origin, "source": u.source,
            "assembly": u.asm, "abstract": u.abstract,
            "image": u.dt.image if u.dt is not None else None, "base": u.base, "instances": u.instances,
            "fields": [{"name": n, "type": f["type"], "public": f["public"], "source": f["source"]}
                       for n, f in u.fields.items()],
            "enum_values": len(u.enum_values),
        })
    return {"version": 1, "generator": "scripts/stub_gen.py", "files": sorted(files), "classes": classes}


def build_report(gen, scan):
    units = gen.units
    by_origin = collections.Counter(u.origin for u in units.values())
    by_kind = collections.Counter(u.kind for u in units.values())
    by_image = collections.Counter((u.dt.image if u.dt is not None else "(ohne Dump)") for u in units.values())
    fields = sum(len(u.fields) for u in units.values())
    src = collections.Counter(f["source"] for u in units.values() for f in u.fields.values())
    script_keys = list(gen.script_units)
    inst = sum(scan["classes"][k]["instances"] for k in script_keys)
    return {
        "units": len(units), "by_assembly": dict(collections.Counter(u.asm for u in units.values())),
        "by_origin": dict(by_origin), "by_kind": dict(by_kind), "by_image": dict(by_image),
        "fields": fields, "field_sources": dict(src),
        "script_classes": len(script_keys), "script_instances": inst,
        "stats": dict(gen.stats), "gaps": dict(gen.gaps),
        "gap_examples": {k: len(v) for k, v in gen.gap_examples.items()},
    }


def write_tree(out, files, manifest, dry):
    """Idempotent: schreibt nur geaenderte Dateien, entfernt veraltete erzeugte Dateien. Rueckgabe (neu, geaendert, geloescht)."""
    mpath = os.path.join(out, "manifest.json")
    old = []
    if os.path.exists(mpath):
        try:
            with open(mpath, encoding="utf-8") as f:
                old = json.load(f).get("files", [])
        except (OSError, ValueError):
            old = []
    new = chg = rem = 0
    for rel, text in files.items():
        p = os.path.join(out, rel)
        cur = None
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                cur = f.read()
        if cur == text:
            continue
        if cur is None:
            new += 1
        else:
            chg += 1
        if not dry:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
    for rel in old:
        if rel not in files:
            p = os.path.join(out, rel)
            if os.path.exists(p):
                rem += 1
                if not dry:
                    os.remove(p)
                    for ext in (".meta",):
                        if os.path.exists(p + ext):
                            os.remove(p + ext)
    if not dry:
        os.makedirs(out, exist_ok=True)
        with open(mpath, "w", encoding="utf-8", newline="\n") as f:
            json.dump(manifest, f, indent=1, sort_keys=True)
            f.write("\n")
    return new, chg, rem


def cmd_gen(a):
    with open(a.scan, encoding="utf-8") as f:
        scan = json.load(f)
    index = None
    if not a.no_dump:
        from stub_dump import DumpIndex, parse_dump
        types, images = parse_dump(a.dump)
        index = DumpIndex(types, images)
    gen = Generator(scan, index, use_dump=not a.no_dump).run()
    files = emit_all(gen)
    manifest = build_manifest(gen, files)
    rep = build_report(gen, scan)
    new, chg, rem = write_tree(a.out, files, manifest, a.dry_run)
    rep["files"] = {"gesamt": len(files), "neu": new, "geaendert": chg, "entfernt": rem, "dry_run": a.dry_run}
    if a.report and not a.dry_run:
        os.makedirs(os.path.dirname(os.path.abspath(a.report)), exist_ok=True)
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, sort_keys=True)
            f.write("\n")
    print(json.dumps(rep, indent=1, sort_keys=True))


def field_categories(scan, keys):
    """Kategorien aller Top-Level-Felder (dominantes Schema je Klasse) und der Array-Elemente."""
    top = collections.Counter()
    elem = collections.Counter()
    nested_types = set()
    nested_leaves = 0
    pptr_game = pptr_engine = 0

    def walk_nested(node):
        nonlocal nested_leaves
        for c in node[4]:
            cat = classify(c)
            if cat == "array":
                e = array_parts(c)
                if e is not None and e[4] and classify(e) == "class":
                    nested_types.add(e[0])
                    walk_nested(e)
                elif e is not None:
                    nested_leaves += 1
            elif cat == "class":
                nested_types.add(c[0])
                walk_nested(c)
            else:
                nested_leaves += 1

    for key in keys:
        info = scan["classes"][key]
        sch = [(n, h) for h, n in info["schemas"].items() if h != "-"]
        if not sch:
            continue
        tree = scan["schemas"][max(sch)[1]]
        for c in tree[4]:
            if c[1] in BUILTIN_FIELDS:
                continue
            cat = classify(c)
            top[cat] += 1
            if cat == "array":
                e = array_parts(c)
                ec = classify(e) if e is not None else "unknown"
                elem[ec] += 1
                c = e if e is not None else c
            if c[0].startswith("PPtr<"):
                name = c[0][5:-1].lstrip("$")
                if name in UNITY_OBJECTS:
                    pptr_engine += 1
                else:
                    pptr_game += 1
            if classify(c) == "class":
                nested_types.add(c[0])
                walk_nested(c)
    return {"top_level": dict(top), "array_elements": dict(elem), "nested_class_types": len(nested_types),
            "nested_leaf_fields": nested_leaves, "pptr_to_engine_class": pptr_engine, "pptr_to_game_class": pptr_game}


def cmd_stats(a):
    with open(a.scan, encoding="utf-8") as f:
        scan = json.load(f)
    cl = scan["classes"]
    ac_keys = [k for k in cl if k.startswith("Assembly-CSharp.dll|")]
    out = {"files": scan["files"], "groups": {}, "assemblies": {}}
    by_asm = collections.defaultdict(lambda: [0, 0, 0])
    for k, c in cl.items():
        v = by_asm[k.split("|", 1)[0]]
        v[0] += 1
        v[1] += c["instances"]
        v[2] += c["components"]
    out["assemblies"] = {k: {"classes": v[0], "instances": v[1], "components": v[2]} for k, v in sorted(by_asm.items())}
    out["script_objects_in_player"] = collections.Counter(k.split("|", 1)[0] for k in scan["script_objects"])
    out["script_objects_in_player"] = dict(out["script_objects_in_player"])
    for g, gi in sorted(scan["groups"].items()):
        gc = {"files": gi["files"], "scene_files": gi["scene_files"], "container_assets": gi["container"], "classes": 0,
              "instances": 0, "components": 0, "bundles_with_stub_class": 0}
        for k in ac_keys:
            x = cl[k]["groups"].get(g)
            if x:
                gc["classes"] += 1
                gc["instances"] += x["instances"]
                gc["components"] += x["components"]
                gc["bundles_with_stub_class"] += x["bundles"]
        out["groups"][g] = gc
    out["fields"] = field_categories(scan, ac_keys)
    out["no_typetree_classes"] = sum(1 for k in ac_keys if "-" in cl[k]["schemas"])
    out["no_typetree_instances"] = sum(cl[k]["schemas"].get("-", 0) for k in ac_keys)
    if os.path.exists(a.dump):
        types, images = parse_dump(a.dump)
        idx = DumpIndex(types, images)
        gd = Generator(scan, idx).run()
        gt = Generator(scan, None, use_dump=False).run()
        simple = {None, "UnityEngine.MonoBehaviour", "UnityEngine.ScriptableObject", "UnityEngine.StateMachineBehaviour",
                  "UnityEngine.Behaviour", "UnityEngine.Object"}
        tiers = {"A_nur_typetree_exakt": [0, 0], "B_binden_mit_abstrichen": [0, 0], "C_braucht_dump": [0, 0], "ohne_typetree": [0, 0]}
        for k in ac_keys:
            c = cl[k]
            ci = gd.class_info.get(k)
            if "-" in c["schemas"] and len(c["schemas"]) == 1:
                t = "ohne_typetree"
            elif ci is not None and ci["tail_base"] not in simple:
                t = "C_braucht_dump"
            else:
                gp = gt.class_gaps.get(k, {})
                if gp.get("field_dropped") or gp.get("tt_unknown_leaf") or gp.get("managed_reference"):
                    t = "C_braucht_dump"
                elif gp.get("pptr_target_unknown"):
                    t = "B_binden_mit_abstrichen"
                else:
                    t = "A_nur_typetree_exakt"
            tiers[t][0] += 1
            tiers[t][1] += c["instances"]
        out["abdeckung_typetree"] = {t: {"klassen": v[0], "instanzen": v[1]} for t, v in tiers.items()}
        out["dump_run"] = build_report(gd, scan)
        rank = []
        grp_pri = collections.defaultdict(lambda: {"klassen": 0, "instanzen": 0, "methoden_eigene": 0, "methoden_mit_basen": 0})
        for k in ac_keys:
            _, ns, name = k.split("|")
            dt = idx.by_key.get((ns, name, 0))
            own = dt.methods if dt is not None else 0
            chain = sum(c.methods for c in idx.chain(dt) if not isinstance(c, str) and c.image == TARGET_ASSEMBLY) if dt else 0
            c = cl[k]
            rank.append({"klasse": k.split("|", 1)[1], "instanzen": c["instances"], "gruppen": sorted(c["groups"]),
                         "methoden_eigene": own, "methoden_mit_basen": chain})
            g = max(c["groups"], key=lambda x: c["groups"][x]["instances"]) if c["groups"] else "?"
            p = grp_pri[g]
            p["klassen"] += 1
            p["instanzen"] += c["instances"]
            p["methoden_eigene"] += own
            p["methoden_mit_basen"] += chain
        rank.sort(key=lambda r: (-r["instanzen"], r["klasse"]))
        out["ranking_nach_instanzen"] = rank
        out["prioritaet_je_gruppe"] = dict(sorted(grp_pri.items()))
        out["methoden_gesamt_assembly_csharp_im_dump"] = sum(t.methods for t in types if t.image == TARGET_ASSEMBLY)
        out["methoden_der_referenzierten_klassen"] = sum(r["methoden_eigene"] for r in rank)
        out["typetree_only_run"] = build_report(gt, scan)
        out["enum_units"] = sum(1 for u in gd.units.values() if u.kind == "enum")
        out["struct_units"] = sum(1 for u in gd.units.values() if u.kind == "struct")
        out["generic_units"] = sum(1 for u in gd.units.values() if u.gen)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print(json.dumps(out, indent=1, sort_keys=True))


def cmd_conflicts(a):
    """Gleiche voll qualifizierte Typnamen in handgeschriebenen Skripten und im Stub-Manifest (nur Namen, keine Inhalte)."""
    with open(a.manifest, encoding="utf-8") as f:
        man = json.load(f)
    stub = {}
    for c in man["classes"]:
        stub[(c["namespace"] + "." + c["name"]) if c["namespace"] else c["name"]] = c
    hand = collections.defaultdict(list)
    decl = re.compile(r"^\s*(?:(?:public|internal|static|sealed|abstract|partial)\s+)*(?:class|struct|enum|interface)\s+(\w+)", re.M)
    nsre = re.compile(r"^\s*namespace\s+([\w.]+)", re.M)
    for dp, _, fn in os.walk(a.scripts):
        for f in fn:
            if not f.endswith(".cs"):
                continue
            with open(os.path.join(dp, f), encoding="utf-8", errors="replace") as fh:
                t = fh.read()
            nss = nsre.findall(t) or [""]
            for m in decl.finditer(t):
                for ns in nss:
                    hand[(ns + "." + m.group(1)) if ns else m.group(1)].append(os.path.relpath(os.path.join(dp, f), a.scripts))
    fq = sorted(k for k in hand if k in stub)
    simple_stub = collections.defaultdict(list)
    for k in stub:
        simple_stub[k.rpartition(".")[2]].append(k)
    simple = sorted({k.rpartition(".")[2] for k in hand if k.rpartition(".")[2] in simple_stub and k not in stub})
    res = {"handgeschriebene_typen": len(hand), "stub_typen": len(stub), "gleicher_voller_name": len(fq),
           "nur_gleicher_kurzname": len(simple)}
    print(json.dumps(res, indent=1))
    for k in fq:
        print("KONFLIKT (CS0436/CS0433 moeglich):", k)
    return 1 if fq else 0


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("stats")
    st.add_argument("--scan", default=DEFAULT_SCAN)
    st.add_argument("--dump", default=DEFAULT_DUMP)
    st.add_argument("--out", default=os.path.join(ROOT, "work", "stubs", "stats.json"))
    st.set_defaults(fn=cmd_stats)
    cf = sub.add_parser("conflicts")
    cf.add_argument("--manifest", required=True)
    cf.add_argument("--scripts", default=os.path.join(ROOT, "unity", "Assets", "Scripts"))
    cf.set_defaults(fn=lambda a: sys.exit(cmd_conflicts(a)))
    g = sub.add_parser("gen")
    g.add_argument("--scan", default=DEFAULT_SCAN)
    g.add_argument("--dump", default=DEFAULT_DUMP)
    g.add_argument("--out", required=True)
    g.add_argument("--report", default=os.path.join(ROOT, "work", "stubs", "report.json"))
    g.add_argument("--no-dump", action="store_true", help="nur TypeTree (Messung der Abdeckung ohne dump.cs)")
    g.add_argument("--dry-run", action="store_true")
    g.set_defaults(fn=cmd_gen)
    s = sub.add_parser("scan")
    s.add_argument("--assets", default=ASSETS)
    s.add_argument("--scan", default=DEFAULT_SCAN)
    s.add_argument("--jobs", type=int, default=6)
    s.add_argument("--limit", type=int, default=0)
    s.set_defaults(fn=cmd_scan)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
