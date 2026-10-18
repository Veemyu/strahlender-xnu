using System;
using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;
using Xnu.Boot;
using Xnu.Core;

namespace Xnu.Tests
{
    public class BootTests
    {
        sealed class FakeHandle : IBundleHandle
        {
            public string Path;
            public bool Unloaded;
            public bool UnloadFlag;
            public string[] Assets = new string[0];
            public UnityEngine.Object Asset;
            public string[] GetAllAssetNames() => Assets;
            public bool IsStreamedSceneBundle => false;
            public UnityEngine.Object LoadAsset(string name, Type type) => Asset;
            public void Unload(bool all) { Unloaded = true; UnloadFlag = all; }
        }

        sealed class FakeSource : IBundleSource
        {
            public readonly List<string> Loads = new List<string>();
            public readonly List<FakeHandle> Handles = new List<FakeHandle>();
            public readonly HashSet<string> Failing = new HashSet<string>();
            public UnityEngine.Object Asset;

            public IBundleHandle Load(string path)
            {
                var file = System.IO.Path.GetFileName(path);
                if (Failing.Contains(file)) throw new BundleLoadException("fehlgeschlagen: " + file);
                Loads.Add(file);
                var h = new FakeHandle { Path = path, Asset = Asset, Assets = new[] { "assets/x.asset" } };
                Handles.Add(h);
                return h;
            }
        }

        static BootTestCatalogWriter.Rec R(string project, string name, string[] deps, string[] assets, long size = 100, uint h0 = 0) =>
            new BootTestCatalogWriter.Rec { Project = project, Name = name, Deps = deps, Assets = assets, Size = size, Hash = new[] { h0, 0u, 0u, 0u }, Time = 123456789L };

        static BundleCatalog SyntheticCatalog()
        {
            var recs = new List<BootTestCatalogWriter.Rec>
            {
                R("Dpr", "masterdatas", new[] { "shaders" }, new[] { "assets/md/a/foo.asset", "assets/md/a/foo.xlsx", "assets/md/b/bar.asset" }, 500, 0x04030201u),
                R("Dpr", "shaders", new string[0], new[] { "assets/shaders/s.shader" }, 50),
                R("Battle", "battle_masterdatas", new[] { "masterdatas", "shaders" }, new[] { "assets/battle/md.asset" }, 70),
                R("Dpr", "scriptableobjects/gamesettings", null, new[] { "assets/scriptableobjects/gamesettings.asset" }, 10),
                R("UIs", "shareduiassets/lang.en", new[] { "shaders", "shaders" }, null, 5),
            };
            return BundleCatalog.FromBytes(BootTestCatalogWriter.Build(recs, "Dpr", 6, new[] { "shareduiassets/lang.en" }));
        }

        [Test]
        public void Katalog_LiestRecordsAbhaengigkeitenUndAssets()
        {
            var c = SyntheticCatalog();
            Assert.AreEqual(6, c.Version);
            Assert.AreEqual("Dpr", c.ProjectName);
            Assert.AreEqual(5, c.Records.Count);
            Assert.AreEqual(1, c.Variants.Count);
            Assert.AreEqual(6, c.AssetCount);

            var md = c.GetBundle("Dpr/masterdatas");
            Assert.AreEqual("Dpr/masterdatas", md.FullName);
            Assert.AreEqual(500, md.Size);
            Assert.AreEqual(123456789L, md.LastWriteTimeRaw);
            Assert.AreEqual(new[] { "shaders" }, md.Dependencies);
            Assert.AreEqual(3, md.AssetPaths.Length);
            Assert.IsTrue(md.Hash.IsValid);
            Assert.AreEqual("01020304" + new string('0', 24), md.Hash.ToString());
            Assert.IsFalse(c.GetBundle("shaders").Hash.IsValid);

            Assert.AreEqual(0, c.GetBundle("scriptableobjects/gamesettings").Dependencies.Length); // ObjectNull
            Assert.AreEqual(0, c.GetBundle("UIs/shareduiassets/lang.en").AssetPaths.Length);
            Assert.AreEqual(new[] { "shaders", "shaders" }, c.GetBundle("lang.en".Insert(0, "shareduiassets/")).Dependencies); // MemberReference
            Assert.AreEqual(0, c.CountMissingDependencies());
        }

        [Test]
        public void Katalog_NameOhneProjektUndCaseInsensitiv()
        {
            var c = SyntheticCatalog();
            Assert.IsTrue(c.TryGetBundle("masterdatas", out var a));
            Assert.IsTrue(c.TryGetBundle("DPR/MasterDatas", out var b));
            Assert.AreSame(a, b);
            Assert.IsFalse(c.TryGetBundle("gibtsnicht", out _));
            Assert.IsFalse(c.TryGetBundle("", out _));
        }

        [Test]
        public void Katalog_TransitiveAbhaengigkeiten()
        {
            var c = SyntheticCatalog();
            var closure = c.GetDependencyClosure(c.GetBundle("battle_masterdatas"));
            Assert.AreEqual(2, closure.Count);
            CollectionAssert.AreEquivalent(new[] { "Dpr/masterdatas", "Dpr/shaders" }, closure.ConvertAll(r => r.FullName));
        }

        [Test]
        public void Katalog_FehlendeAbhaengigkeitWirdErkannt()
        {
            var recs = new List<BootTestCatalogWriter.Rec> { R("Dpr", "a", new[] { "fehlt" }, new string[0]) };
            var c = BundleCatalog.FromBytes(BootTestCatalogWriter.Build(recs));
            Assert.AreEqual(1, c.CountMissingDependencies());
            Assert.Throws<InvalidDataException>(() => c.GetDependencyClosure(c.GetBundle("a")));
        }

        [Test]
        public void Katalog_DoppelterEintragIstFehler()
        {
            var recs = new List<BootTestCatalogWriter.Rec> { R("Dpr", "a", null, null), R("Dpr", "a", null, null) };
            Assert.Throws<InvalidDataException>(() => BundleCatalog.FromBytes(BootTestCatalogWriter.Build(recs)));
        }

        [Test]
        public void Katalog_FalscheVersionOderMuellWirftFehler()
        {
            var recs = new List<BootTestCatalogWriter.Rec> { R("Dpr", "a", null, null) };
            Assert.Throws<InvalidDataException>(() => BundleCatalog.FromBytes(BootTestCatalogWriter.Build(recs, "Dpr", 5)));
            Assert.Throws<FormatException>(() => BundleCatalog.FromBytes(new byte[64]));
            Assert.Throws<FormatException>(() => BundleCatalog.FromBytes(new byte[] { 1, 2, 3 }));
            var good = BootTestCatalogWriter.Build(recs);
            var cut = new byte[good.Length / 2];
            Array.Copy(good, cut, cut.Length);
            Assert.Throws<FormatException>(() => BundleCatalog.FromBytes(cut));
        }

        [Test]
        public void AssetKey_Normalisierung()
        {
            Assert.AreEqual("scriptableobjects/gamesettings", AssetKey.ToLogicalKey("Assets\\ScriptableObjects/GameSettings.asset"));
            Assert.AreEqual("a/b.c/d", AssetKey.ToLogicalKey("assets/a/b.c/d"));
            Assert.AreEqual("a/b", AssetKey.ToLogicalKey("./a/b.png"));
            Assert.AreEqual("x/tt_large-db sdf", AssetKey.ToLogicalKey("assets/x/tt_large-db sdf.asset"));
        }

        [Test]
        public void AssetKey_AufloesungLogischerNameZuBundle()
        {
            var c = SyntheticCatalog();
            Assert.IsTrue(c.TryResolveAsset("scriptableobjects/gamesettings", out var e));
            Assert.AreEqual("Dpr/scriptableobjects/gamesettings", e.Bundle.FullName);
            Assert.AreEqual("assets/scriptableobjects/gamesettings.asset", e.AssetPath);

            Assert.IsTrue(c.TryResolveAsset("Assets/ScriptableObjects/GameSettings.asset", out var e2));
            Assert.AreSame(e.Bundle, e2.Bundle);
            Assert.IsTrue(c.TryResolveAsset("md/b/bar", out var e3));
            Assert.AreEqual("Dpr/masterdatas", e3.Bundle.FullName);
            Assert.IsFalse(c.TryResolveAsset("md/b/nope", out _));
            Assert.IsFalse(c.TryResolveAsset(null, out _));
        }

        [Test]
        public void AssetKey_MehrdeutigeNamenBrauchenEndung()
        {
            var c = SyntheticCatalog();
            Assert.IsFalse(c.TryResolveAsset("md/a/foo", out _));
            Assert.AreEqual(1, c.AmbiguousLogicalKeyCount);
            Assert.AreEqual(2, c.GetAssetCandidates("md/a/foo").Count);
            Assert.IsTrue(c.TryResolveAsset("md/a/foo.xlsx", out var e));
            Assert.AreEqual("assets/md/a/foo.xlsx", e.AssetPath);
        }

        [Test]
        public void Provider_LaedtAbhaengigkeitenZuerstUndZaehltReferenzen()
        {
            var c = SyntheticCatalog();
            var src = new FakeSource();
            var p = new BundleProvider(c, "root", src);

            p.Acquire("Battle/battle_masterdatas");
            Assert.AreEqual(3, p.LoadedBundleCount);
            Assert.AreEqual("battle_masterdatas", src.Loads[2]);
            CollectionAssert.AreEquivalent(new[] { "masterdatas", "shaders" }, src.Loads.GetRange(0, 2));
            Assert.AreEqual(1, p.GetRefCount("battle_masterdatas"));
            Assert.AreEqual(1, p.GetRefCount("masterdatas"));
            Assert.AreEqual(1, p.GetRefCount("shaders"));

            p.Acquire("masterdatas");
            Assert.AreEqual(3, src.Loads.Count, "bereits geladen: kein zweiter Ladevorgang");
            Assert.AreEqual(2, p.GetRefCount("masterdatas"));
            Assert.AreEqual(2, p.GetRefCount("shaders"));

            Assert.IsFalse(p.Release("masterdatas"));
            Assert.IsTrue(p.IsLoaded("masterdatas"));
            Assert.IsTrue(p.Release("battle_masterdatas"));
            Assert.AreEqual(0, p.LoadedBundleCount);
            Assert.IsTrue(src.Handles.TrueForAll(h => h.Unloaded && h.UnloadFlag));
            Assert.AreEqual(Path.Combine("root", "Battle", "battle_masterdatas"), src.Handles[2].Path);
        }

        [Test]
        public void Provider_ReleaseOhneAcquireWirftFehler()
        {
            var p = new BundleProvider(SyntheticCatalog(), "root", new FakeSource());
            Assert.Throws<InvalidOperationException>(() => p.Release("shaders"));
            Assert.Throws<KeyNotFoundException>(() => p.Acquire("unbekannt"));
        }

        [Test]
        public void Provider_RollbackWennAbhaengigkeitFehlschlaegt()
        {
            var src = new FakeSource();
            src.Failing.Add("masterdatas");
            var p = new BundleProvider(SyntheticCatalog(), "root", src);
            Assert.Throws<BundleLoadException>(() => p.Acquire("battle_masterdatas"));
            Assert.AreEqual(0, p.LoadedBundleCount, "bereits geladene Teile müssen entladen sein");
            Assert.AreEqual(0, p.GetRefCount("shaders"));
            Assert.IsTrue(src.Handles.TrueForAll(h => h.Unloaded));
        }

        [Test]
        public void Provider_UnloadAllUndDispose()
        {
            var src = new FakeSource();
            var p = new BundleProvider(SyntheticCatalog(), "root", src);
            p.Acquire("masterdatas");
            p.Acquire("gamesettings".Insert(0, "scriptableobjects/"));
            Assert.AreEqual(3, p.LoadedBundleCount);
            p.Dispose();
            Assert.AreEqual(0, p.LoadedBundleCount);
            Assert.IsTrue(src.Handles.TrueForAll(h => h.Unloaded));
        }

        [Test]
        public void Provider_LoadAssetPerLogischemNamen()
        {
            var ta = new TextAsset("test");
            try
            {
                var src = new FakeSource { Asset = ta };
                var p = new BundleProvider(SyntheticCatalog(), "root", src);
                var loaded = p.LoadAsset<TextAsset>("md/b/bar", out var bundle);
                Assert.AreSame(ta, loaded);
                Assert.AreEqual("Dpr/masterdatas", bundle.FullName);
                Assert.AreEqual(1, p.GetRefCount("masterdatas"));
                Assert.IsNull(p.LoadAsset<TextAsset>("gibt/es/nicht", out _));
                p.Release(bundle.FullName);
                Assert.AreEqual(0, p.LoadedBundleCount);

                src.Asset = null;
                Assert.IsNull(p.LoadAsset<TextAsset>("md/b/bar", out _));
                Assert.AreEqual(0, p.LoadedBundleCount, "bei fehlendem Asset wird der Zähler zurückgenommen");
            }
            finally { UnityEngine.Object.DestroyImmediate(ta); }
        }

        static string MakeTempRoot()
        {
            var dir = Path.GetFullPath(FileUtil.GetUniqueTempPathInProject());
            Directory.CreateDirectory(dir);
            return dir;
        }

        static void WriteFakeBundle(string aaDir, string project, string name, int extra = 0)
        {
            var path = Path.Combine(aaDir, project, name.Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            var bytes = new byte[16 + extra];
            System.Text.Encoding.ASCII.GetBytes("UnityFS").CopyTo(bytes, 0);
            File.WriteAllBytes(path, bytes);
        }

        [Test]
        public void Katalog_VerzeichnisScan()
        {
            var root = MakeTempRoot();
            try
            {
                WriteFakeBundle(root, "Dpr", "masterdatas");
                WriteFakeBundle(root, "Dpr", "encseq/cave01");
                WriteFakeBundle(root, "Battle", "x");
                File.WriteAllBytes(Path.Combine(root, "Dpr.bin"), new byte[100]);
                File.WriteAllBytes(Path.Combine(root, "Dpr", "kein_bundle"), new byte[100]);
                File.WriteAllBytes(Path.Combine(root, ".DS_Store"), new byte[20]);

                var c = BundleCatalog.FromDirectory(root);
                Assert.IsFalse(c.FromManifest);
                Assert.AreEqual(3, c.Records.Count);
                Assert.IsTrue(c.TryGetBundle("Dpr/encseq/cave01", out var r));
                Assert.AreEqual("Dpr", r.Project);
                Assert.AreEqual("encseq/cave01", r.Name);
                Assert.AreEqual(16, r.Size);
                Assert.IsFalse(c.TryGetBundle("kein_bundle", out _));
            }
            finally { Directory.Delete(root, true); }
        }

        [Test]
        public void BootSequence_MitSynthetischenDaten()
        {
            var gameData = MakeTempRoot();
            var old = Environment.GetEnvironmentVariable(GameDataPaths.EnvVar);
            try
            {
                Environment.SetEnvironmentVariable(GameDataPaths.EnvVar, gameData);
                var aa = GameDataPaths.AssetAssistant;
                Assert.AreEqual(Path.Combine(gameData, "romfs", "Data", "StreamingAssets", "AssetAssistant"), aa);

                var steps = new List<BootStep>();
                var missing = BootSequence.Run(aa, new FakeSource(), steps.Add);
                Assert.IsFalse(missing.Success);
                Assert.AreEqual(BootStatus.Fail, steps[steps.Count - 1].Status);

                Directory.CreateDirectory(aa);
                var recs = new List<BootTestCatalogWriter.Rec>
                {
                    R("Dpr", "masterdatas", new[] { "shaders" }, new[] { "assets/md/x.asset" }),
                    R("Dpr", "shaders", null, new[] { "assets/s.shader" }),
                };
                File.WriteAllBytes(Path.Combine(aa, "Dpr.bin"), BootTestCatalogWriter.Build(recs));
                WriteFakeBundle(aa, "Dpr", "masterdatas");
                WriteFakeBundle(aa, "Dpr", "shaders");

                steps.Clear();
                var report = BootSequence.Run(aa, new FakeSource(), steps.Add);
                Assert.IsTrue(report.Success);
                Assert.AreEqual(2, report.Catalog.Records.Count);
                Assert.IsTrue(report.Catalog.FromManifest);
                Assert.IsNotNull(report.Provider);
                Assert.IsTrue(steps.TrueForAll(s => s.Status == BootStatus.Ok), string.Join("\n", steps));

                // Defekter Katalog: Rückfall auf Verzeichnis-Scan mit Warnung
                File.WriteAllBytes(Path.Combine(aa, "Dpr.bin"), new byte[40]);
                steps.Clear();
                var fallback = BootSequence.Run(aa, new FakeSource(), steps.Add);
                Assert.IsTrue(fallback.Success);
                Assert.IsFalse(fallback.Catalog.FromManifest);
                Assert.AreEqual(2, fallback.Catalog.Records.Count);
                Assert.IsTrue(steps.Exists(s => s.Status == BootStatus.Warn));
            }
            finally
            {
                Environment.SetEnvironmentVariable(GameDataPaths.EnvVar, old);
                Directory.Delete(gameData, true);
            }
        }
    }
}
