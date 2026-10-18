using System;
using System.Collections.Generic;
using System.Text;

namespace Xnu.Boot
{
    // Minimaler Leser für den .NET-BinaryFormatter-Strom (MS-NRBF), soweit der Katalog ihn nutzt:
    // Klassen mit Typinformation, Strings, Arrays, Referenzen, Null-Läufe. Keine Typauflösung,
    // es entsteht nur ein generischer Objektgraph (siehe docs/bundle-katalog.md).
    public sealed class NrbfClass
    {
        public string Name;
        public string[] MemberNames;
        public object[] Values;

        public object Get(string member)
        {
            for (var i = 0; i < MemberNames.Length; i++)
                if (MemberNames[i] == member) return Values[i];
            throw new FormatException("Member fehlt: " + member + " in " + Name);
        }
    }

    public sealed class NrbfGraph
    {
        internal readonly Dictionary<int, object> Objects = new Dictionary<int, object>();
        public object Root;

        // Löst Rückverweise auf (Arrays enthalten oft Verweise auf später folgende Objekte).
        public object Resolve(object value)
        {
            if (value is NrbfRef r)
            {
                if (!Objects.TryGetValue(r.Id, out var target))
                    throw new FormatException("Unaufgelöste Objekt-ID " + r.Id);
                return target;
            }
            return value;
        }
    }

    public sealed class NrbfRef
    {
        public readonly int Id;
        public NrbfRef(int id) { Id = id; }
    }

    public static class NrbfReader
    {
        const byte RecHeader = 0, RecClassWithId = 1, RecSysClassMembers = 2, RecClassMembers = 3,
            RecSysClassTyped = 4, RecClassTyped = 5, RecString = 6, RecBinaryArray = 7,
            RecPrimitiveTyped = 8, RecReference = 9, RecNull = 10, RecEnd = 11, RecLibrary = 12,
            RecNull256 = 13, RecNullMulti = 14, RecPrimArray = 15, RecObjectArray = 16, RecStringArray = 17;

        sealed class NullRun { public int Count; }

        sealed class ClassMeta
        {
            public string Name;
            public string[] Names;
            public byte[] Types;
            public object[] Infos;
        }

        sealed class State
        {
            public byte[] Data;
            public int Pos;
            public NrbfGraph Graph = new NrbfGraph();
            public Dictionary<int, ClassMeta> Metas = new Dictionary<int, ClassMeta>();
            public int RootId;
        }

        public static NrbfGraph Read(byte[] data)
        {
            if (data == null || data.Length < 17) throw new FormatException("NRBF-Strom zu kurz");
            var s = new State { Data = data };
            if (data[0] != RecHeader) throw new FormatException("Kein NRBF-Header (Byte 0 != 0)");
            while (true)
            {
                if (s.Pos >= data.Length) throw new FormatException("NRBF-Strom ohne MessageEnd");
                var rec = ReadRecord(s);
                if (rec is EndMarker) break;
            }
            if (!s.Graph.Objects.TryGetValue(s.RootId, out var root))
                throw new FormatException("Root-Objekt " + s.RootId + " nicht gefunden");
            s.Graph.Root = root;
            return s.Graph;
        }

        sealed class EndMarker { }
        static readonly EndMarker End = new EndMarker();
        sealed class HeaderMarker { }
        static readonly HeaderMarker Hdr = new HeaderMarker();

        static byte U8(State s)
        {
            if (s.Pos >= s.Data.Length) throw new FormatException("Unerwartetes Ende");
            return s.Data[s.Pos++];
        }

        static int I32(State s)
        {
            if (s.Pos + 4 > s.Data.Length) throw new FormatException("Unerwartetes Ende");
            var v = BitConverter.ToInt32(s.Data, s.Pos);
            s.Pos += 4;
            return v;
        }

        static long I64(State s)
        {
            if (s.Pos + 8 > s.Data.Length) throw new FormatException("Unerwartetes Ende");
            var v = BitConverter.ToInt64(s.Data, s.Pos);
            s.Pos += 8;
            return v;
        }

        static string Lps(State s)
        {
            var len = 0;
            var shift = 0;
            while (true)
            {
                var b = U8(s);
                len |= (b & 0x7f) << shift;
                if ((b & 0x80) == 0) break;
                shift += 7;
                if (shift > 28) throw new FormatException("Ungültige Stringlänge");
            }
            if (len < 0 || s.Pos + len > s.Data.Length) throw new FormatException("String ragt über das Ende");
            var str = Encoding.UTF8.GetString(s.Data, s.Pos, len);
            s.Pos += len;
            return str;
        }

        static object Primitive(State s, byte type)
        {
            if (s.Pos + PrimitiveSize(type) > s.Data.Length) throw new FormatException("Unerwartetes Ende");
            switch (type)
            {
                case 1: return U8(s) != 0;
                case 2: return U8(s);
                case 3:
                {
                    var lead = U8(s);
                    var extra = lead >= 0xF0 ? 3 : lead >= 0xE0 ? 2 : lead >= 0xC0 ? 1 : 0;
                    var bytes = new byte[1 + extra];
                    bytes[0] = lead;
                    for (var i = 0; i < extra; i++) bytes[1 + i] = U8(s);
                    return Encoding.UTF8.GetString(bytes);
                }
                case 5: return Lps(s);
                case 6: { var v = BitConverter.ToDouble(s.Data, s.Pos); s.Pos += 8; return v; }
                case 7: { var v = BitConverter.ToInt16(s.Data, s.Pos); s.Pos += 2; return v; }
                case 8: return I32(s);
                case 9: return I64(s);
                case 10: return (sbyte)U8(s);
                case 11: { var v = BitConverter.ToSingle(s.Data, s.Pos); s.Pos += 4; return v; }
                case 12:
                case 13: return I64(s); // TimeSpan / DateTime: roher 64-Bit-Wert
                case 14: { var v = BitConverter.ToUInt16(s.Data, s.Pos); s.Pos += 2; return v; }
                case 15: { var v = BitConverter.ToUInt32(s.Data, s.Pos); s.Pos += 4; return v; }
                case 16: { var v = BitConverter.ToUInt64(s.Data, s.Pos); s.Pos += 8; return v; }
                case 18: return Lps(s);
                default: throw new FormatException("Unbekannter Primitivtyp " + type);
            }
        }

        static int PrimitiveSize(byte type)
        {
            switch (type)
            {
                case 6: case 9: case 12: case 13: case 16: return 8;
                case 8: case 11: case 15: return 4;
                case 7: case 14: return 2;
                default: return 1;
            }
        }

        static object ReadTypeInfo(State s, byte binaryType)
        {
            switch (binaryType)
            {
                case 0:
                case 7: return U8(s);
                case 3: return Lps(s);
                case 4: { var n = Lps(s); var lib = I32(s); return n + "|" + lib; }
                default: return null;
            }
        }

        static void CheckCount(State s, long count, int minBytesPerItem)
        {
            if (count < 0 || count * minBytesPerItem > s.Data.Length - s.Pos)
                throw new FormatException("Unplausible Elementanzahl " + count);
        }

        static object[] ReadMembers(State s, ClassMeta meta)
        {
            var n = meta.Names.Length;
            var values = new object[n];
            var nullRun = 0;
            for (var i = 0; i < n; i++)
            {
                if (nullRun > 0) { nullRun--; continue; }
                if (meta.Types[i] == 0)
                {
                    values[i] = Primitive(s, (byte)meta.Infos[i]);
                    continue;
                }
                var v = ReadRecord(s);
                if (v is NullRun nr) { nullRun = nr.Count - 1; continue; }
                values[i] = v;
            }
            if (nullRun > 0) throw new FormatException("Null-Lauf ragt über Klassenende");
            return values;
        }

        static object ReadElements(State s, long total, byte binaryType, object info)
        {
            CheckCount(s, total, 1);
            var list = new object[total];
            var idx = 0;
            while (idx < total)
            {
                if (binaryType == 0)
                {
                    list[idx++] = Primitive(s, (byte)info);
                    continue;
                }
                var v = ReadRecord(s);
                if (v is NullRun nr)
                {
                    if (idx + nr.Count > total) throw new FormatException("Null-Lauf ragt über Array");
                    idx += nr.Count;
                }
                else list[idx++] = v;
            }
            return list;
        }

        static object ReadRecord(State s)
        {
            var rt = U8(s);
            switch (rt)
            {
                case RecHeader:
                    s.RootId = I32(s);
                    I32(s);
                    var major = I32(s);
                    I32(s);
                    if (major != 1) throw new FormatException("Unbekannte NRBF-Version " + major);
                    return Hdr;
                case RecLibrary:
                    I32(s);
                    Lps(s);
                    return ReadRecord(s);
                case RecSysClassTyped:
                case RecClassTyped:
                {
                    var id = I32(s);
                    var meta = new ClassMeta { Name = Lps(s) };
                    var n = I32(s);
                    CheckCount(s, n, 1);
                    meta.Names = new string[n];
                    for (var i = 0; i < n; i++) meta.Names[i] = Lps(s);
                    meta.Types = new byte[n];
                    for (var i = 0; i < n; i++) meta.Types[i] = U8(s);
                    meta.Infos = new object[n];
                    for (var i = 0; i < n; i++) meta.Infos[i] = ReadTypeInfo(s, meta.Types[i]);
                    if (rt == RecClassTyped) I32(s); // Library-ID
                    s.Metas[id] = meta;
                    return Instantiate(s, id, meta);
                }
                case RecClassWithId:
                {
                    var id = I32(s);
                    var metaId = I32(s);
                    if (!s.Metas.TryGetValue(metaId, out var meta))
                        throw new FormatException("ClassWithId verweist auf unbekannte Klasse " + metaId);
                    return Instantiate(s, id, meta);
                }
                case RecSysClassMembers:
                case RecClassMembers:
                    throw new NotSupportedException("Klassen ohne Typinformation werden nicht unterstützt");
                case RecString:
                {
                    var id = I32(s);
                    var str = Lps(s);
                    s.Graph.Objects[id] = str;
                    return str;
                }
                case RecBinaryArray:
                {
                    var id = I32(s);
                    var arrayType = U8(s);
                    var rank = I32(s);
                    if (rank < 1 || rank > 32) throw new FormatException("Ungültiger Array-Rang");
                    long total = 1;
                    for (var i = 0; i < rank; i++)
                    {
                        total *= I32(s);
                        if (total > int.MaxValue) throw new FormatException("Array zu groß");
                    }
                    if (arrayType >= 3) for (var i = 0; i < rank; i++) I32(s);
                    var bt = U8(s);
                    var info = ReadTypeInfo(s, bt);
                    var arr = ReadElements(s, total, bt, info);
                    s.Graph.Objects[id] = arr;
                    return arr;
                }
                case RecPrimitiveTyped:
                    return Primitive(s, U8(s));
                case RecReference:
                    return new NrbfRef(I32(s));
                case RecNull:
                    return null;
                case RecNull256:
                    return new NullRun { Count = U8(s) };
                case RecNullMulti:
                    return new NullRun { Count = I32(s) };
                case RecPrimArray:
                {
                    var id = I32(s);
                    var len = I32(s);
                    var pt = U8(s);
                    var arr = ReadElements(s, len, 0, pt);
                    s.Graph.Objects[id] = arr;
                    return arr;
                }
                case RecObjectArray:
                case RecStringArray:
                {
                    var id = I32(s);
                    var len = I32(s);
                    var arr = ReadElements(s, len, rt == RecObjectArray ? (byte)2 : (byte)1, null);
                    s.Graph.Objects[id] = arr;
                    return arr;
                }
                case RecEnd:
                    return End;
                default:
                    throw new FormatException("Unbekannter NRBF-Record-Typ " + rt + " bei Offset " + (s.Pos - 1));
            }
        }

        static NrbfClass Instantiate(State s, int id, ClassMeta meta)
        {
            var obj = new NrbfClass { Name = meta.Name, MemberNames = meta.Names };
            s.Graph.Objects[id] = obj;
            obj.Values = ReadMembers(s, meta);
            return obj;
        }
    }
}
