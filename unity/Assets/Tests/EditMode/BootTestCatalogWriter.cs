using System.Collections.Generic;
using System.IO;
using System.Text;
using Xnu.Boot;

namespace Xnu.Tests
{
    // Erzeugt synthetische Kataloge im selben NRBF-Layout wie Dpr.bin (nur Testdaten, keine Spieldaten).
    static class BootTestCatalogWriter
    {
        public sealed class Rec
        {
            public string Project, Name;
            public uint[] Hash = new uint[4];
            public long Time;
            public bool Scene;
            public string[] Deps;   // null => ObjectNull
            public string[] Assets; // null => ObjectNull
            public long Size;
        }

        const string Lib = "AssetAssistant, Version=0.0.0.0, Culture=neutral, PublicKeyToken=null";
        const string ManifestName = "SmartPoint.AssetAssistant.AssetBundleDownloadManifest";
        const string RecordName = "SmartPoint.AssetAssistant.AssetBundleRecord";
        const string HashName = "SmartPoint.AssetAssistant.RecordedHash";

        public static byte[] Build(IList<Rec> recs, string project = "Dpr", int version = 6, string[] variants = null)
        {
            var ms = new MemoryStream();
            var w = new BinaryWriter(ms, new UTF8Encoding(false));
            var nextId = 1000;
            var arrayId = 4;
            var recIdBase = 10;

            w.Write((byte)0); w.Write(1); w.Write(-1); w.Write(1); w.Write(0);
            w.Write((byte)12); w.Write(2); w.Write(Lib);

            w.Write((byte)5); w.Write(1); w.Write(ManifestName); w.Write(4);
            foreach (var n in new[] { "_version", "_projectName", "_records", "_assetBundleNamesWithVariant" }) w.Write(n);
            w.Write((byte)0); w.Write((byte)1); w.Write((byte)4); w.Write((byte)6);
            w.Write((byte)8);
            w.Write(RecordName + "[]"); w.Write(2);
            w.Write(2);
            w.Write(version);
            w.Write((byte)6); w.Write(3); w.Write(project);
            w.Write((byte)9); w.Write(arrayId);
            w.Write((byte)9); w.Write(5);

            w.Write((byte)7); w.Write(arrayId); w.Write((byte)0); w.Write(1); w.Write(recs.Count);
            w.Write((byte)4); w.Write(RecordName); w.Write(2);
            for (var i = 0; i < recs.Count; i++) { w.Write((byte)9); w.Write(recIdBase + i); }

            var vs = variants ?? new string[0];
            w.Write((byte)17); w.Write(5); w.Write(vs.Length);
            foreach (var v in vs) { w.Write((byte)6); w.Write(nextId++); w.Write(v); }

            for (var i = 0; i < recs.Count; i++)
            {
                var r = recs[i];
                if (i == 0)
                {
                    w.Write((byte)5); w.Write(recIdBase); w.Write(RecordName); w.Write(8);
                    foreach (var n in new[] { "projectName", "assetBundleName", "hash", "lastWriteTime", "isStreamingSceneAssetBundle", "allDependencies", "assetPaths", "size" }) w.Write(n);
                    foreach (var t in new byte[] { 1, 1, 4, 0, 0, 6, 6, 0 }) w.Write(t);
                    w.Write(HashName); w.Write(2);
                    w.Write((byte)13); w.Write((byte)1); w.Write((byte)9);
                    w.Write(2);
                }
                else { w.Write((byte)1); w.Write(recIdBase + i); w.Write(recIdBase); }

                w.Write((byte)6); w.Write(nextId++); w.Write(r.Project);
                w.Write((byte)6); w.Write(nextId++); w.Write(r.Name);
                if (i == 0)
                {
                    w.Write((byte)5); w.Write(-5); w.Write(HashName); w.Write(4);
                    foreach (var n in new[] { "u0", "u1", "u2", "u3" }) w.Write(n);
                    for (var k = 0; k < 4; k++) w.Write((byte)0);
                    for (var k = 0; k < 4; k++) w.Write((byte)15);
                    w.Write(2);
                }
                else { w.Write((byte)1); w.Write(nextId++); w.Write(-5); }
                foreach (var u in r.Hash) w.Write(u);
                w.Write(r.Time);
                w.Write(r.Scene);
                WriteStrings(w, r.Deps, ref nextId);
                WriteStrings(w, r.Assets, ref nextId);
                w.Write(r.Size);
            }
            w.Write((byte)11);
            return ms.ToArray();
        }

        static void WriteStrings(BinaryWriter w, string[] items, ref int nextId)
        {
            if (items == null) { w.Write((byte)10); return; }
            w.Write((byte)17); w.Write(nextId++); w.Write(items.Length);
            var firstId = -1;
            for (var i = 0; i < items.Length; i++)
            {
                // wiederholte Strings als MemberReference, wie es der BinaryFormatter tut
                if (i > 0 && items[i] == items[0]) { w.Write((byte)9); w.Write(firstId); continue; }
                if (i == 0) firstId = nextId;
                w.Write((byte)6); w.Write(nextId++); w.Write(items[i]);
            }
        }
    }
}
