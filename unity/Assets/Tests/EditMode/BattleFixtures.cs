using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.CompilerServices;
using Xnu.Data;

namespace Xnu.Tests
{
    // Laedt die Orakel-Fixtures (nur Zahlen) aus Fixtures/. Erzeugt von scripts/battle_oracle.py.
    static class BattleFixtures
    {
        public static string Dir([CallerFilePath] string source = "")
        {
            string beside = Path.Combine(Path.GetDirectoryName(source) ?? "", "Fixtures");
            if (Directory.Exists(beside)) return beside;
            string fromRoot = Path.Combine(Directory.GetCurrentDirectory(), "Assets", "Tests", "EditMode", "Fixtures");
            if (Directory.Exists(fromRoot)) return fromRoot;
            throw new DirectoryNotFoundException("Fixture-Verzeichnis nicht gefunden: " + beside);
        }

        public static Dictionary<string, object> Load(string file)
        {
            return (Dictionary<string, object>)MiniJson.Parse(File.ReadAllText(Path.Combine(Dir(), file)));
        }

        public static List<Dictionary<string, object>> Cases(Dictionary<string, object> root, string key)
        {
            var list = new List<Dictionary<string, object>>();
            foreach (var item in (List<object>)root[key]) list.Add((Dictionary<string, object>)item);
            return list;
        }

        public static long L(Dictionary<string, object> d, string key) => Convert.ToInt64(d[key]);

        public static int I(Dictionary<string, object> d, string key) => checked((int)Convert.ToInt64(d[key]));

        public static uint U32(Dictionary<string, object> d, string key) => unchecked((uint)Convert.ToInt64(d[key]));

        public static bool B(Dictionary<string, object> d, string key) => Convert.ToInt64(d[key]) != 0;

        // 64-Bit-Werte stehen als Strings im JSON.
        public static ulong U64(Dictionary<string, object> d, string key) => ulong.Parse((string)d[key]);

        public static List<long> LongList(object list)
        {
            var result = new List<long>();
            foreach (var v in (List<object>)list) result.Add(Convert.ToInt64(v));
            return result;
        }

        public static List<List<long>> Matrix(object rows)
        {
            var result = new List<List<long>>();
            foreach (var r in (List<object>)rows) result.Add(LongList(r));
            return result;
        }
    }
}
