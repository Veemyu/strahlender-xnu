using System.Collections.Generic;
using NUnit.Framework;
using UnityEngine;
using Xnu.Field;

namespace Xnu.Tests
{
    // Ursache „Zone 367 zeigt keine Karte“ (docs/sichtpruefung-1.md): Der Container R209 liegt bei z = 672 (Zeile 21), seine Meshes reichen
    // aber bis in Zeile 24; der Startpunkt (512, 726) liegt in Zeile 22. Container gehören deshalb zu allen Blöcken, die ihre Meshes berühren.
    public class FieldStreamerContainerTests
    {
        sealed class PassThrough : IMapMaterialSource
        {
            public Material For(Material original) => original;
            public bool IsAllowed(Material m) => true;
            public void Destroy() { }
        }

        [Test]
        public void BlocksCoveringZaehltRasterbloeckeVonWeltrechteck()
        {
            // x -45..-10 = Zellen 10..45 (Spalten 0..1), z 30..70 = Zeilen 0..2
            var l = BlockStreamingMath.BlocksCovering(-45f, -10f, 30f, 70f);
            Assert.AreEqual(6, l.Count);
            Assert.IsTrue(l.Contains(new BlockId(0, 0)));
            Assert.IsTrue(l.Contains(new BlockId(1, 2)));
            Assert.IsFalse(l.Contains(new BlockId(2, 0)));
        }

        [Test]
        public void BlocksCoveringBegrenztAusreisser()
        {
            var l = BlockStreamingMath.BlocksCovering(-5000f, 0f, 0f, 5000f, 16);
            Assert.AreEqual(16 * 16, l.Count);
        }

        [Test]
        public void BlocksCoveringEinzelnerBlock()
        {
            var l = BlockStreamingMath.BlocksCovering(-500f, -498f, 700f, 702f);
            Assert.AreEqual(1, l.Count);
            Assert.AreEqual(new BlockId(15, 21), l[0]);
        }

        [Test]
        public void BodenUeberDerAusgangshoeheWirdNurBeimStartVonObenGesucht()
        {
            var ground = GameObject.CreatePrimitive(PrimitiveType.Cube);
            try
            {
                ground.layer = 10;
                ground.transform.position = new Vector3(-512f, 1.5f, 726f);
                ground.transform.localScale = new Vector3(4f, 1f, 4f);   // Oberseite bei y = 2
                Physics.SyncTransforms();
                var rg = new RaycastGround(1 << 10);
                Assert.IsFalse(rg.TryGetHeight(-512f, 726f, 0f, out _), "normaler Schritt: Strahl beginnt unter dem Boden");
                rg.SpawnSearch = true;
                Assert.IsTrue(rg.TryGetHeight(-512f, 726f, 0f, out var y));
                Assert.AreEqual(2f, y, 0.01f);
                Assert.IsFalse(rg.TryGetHeight(-300f, 726f, 0f, out _), "ohne Boden bleibt es ohne Treffer");
            }
            finally { Object.DestroyImmediate(ground); }
        }

        [Test]
        public void ErsatzmaterialFreigabeLaesstAndereMaterialienUnberuehrt()
        {
            var f = new FallbackMaterials();
            var o1 = new Material(Shader.Find("Hidden/Internal-Colored"));
            var o2 = new Material(Shader.Find("Hidden/Internal-Colored"));
            try
            {
                var a = f.For(o1);
                var b = f.For(o2);
                var missing = f.For(null);
                f.Release(a);
                f.Release(missing);
                Assert.IsTrue(a == null, "freigegeben");
                Assert.IsTrue(b != null, "das Material der Spielerfigur bleibt (Zonenwechsel machte es magenta)");
                Assert.IsTrue(missing != null, "gemeinsames Platzhaltermaterial bleibt");
                Assert.AreSame(b, f.For(o2));
            }
            finally { f.Destroy(); Object.DestroyImmediate(o1); Object.DestroyImmediate(o2); }
        }

        static GameObject MakePrefab(out GameObject cube)
        {
            var prefab = new GameObject("Area");
            var offset = new GameObject("Offset");
            offset.transform.SetParent(prefab.transform, false);
            var container = new GameObject("R209");
            container.transform.SetParent(offset.transform, false);
            container.transform.localPosition = new Vector3(-512f, 0f, 672f);   // Zeile 21, Spalte 16
            cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
            cube.transform.SetParent(container.transform, false);
            cube.transform.localScale = new Vector3(10f, 1f, 100f);
            cube.transform.localPosition = new Vector3(0f, 0f, 50f);           // Welt-z 672..772 = Zeilen 21..24
            return prefab;
        }

        [Test]
        public void ContainerGehoertZuAllenBeruehrtenBloecken()
        {
            var prefab = MakePrefab(out _);
            var parent = new GameObject("Test");
            try
            {
                var s = new FieldAreaStreamer(prefab, new FieldMapBuilder(new PassThrough()), parent.transform, "Map");
                Assert.AreEqual(1, s.ContainersAvailable);
                var avail = new HashSet<BlockId>(s.Available);
                Assert.IsTrue(avail.Contains(new BlockId(16, 21)), "Ursprungsblock");
                Assert.IsTrue(avail.Contains(new BlockId(16, 22)), "Block des Startpunkts (512, 726)");
                Assert.IsTrue(avail.Contains(new BlockId(16, 24)));
                Assert.IsFalse(avail.Contains(new BlockId(16, 25)));

                var sel = s.Update(512, 726, 0, 0);
                Assert.IsTrue(sel.Load.Contains(new BlockId(16, 22)));
                Assert.AreEqual(1, s.BuiltContainers, "ein Container, auch wenn mehrere Blöcke geladen sind");
            }
            finally { Object.DestroyImmediate(parent); Object.DestroyImmediate(prefab); }
        }

        [Test]
        public void GeteilterContainerBleibtBisZumLetztenBlock()
        {
            var prefab = MakePrefab(out _);
            var parent = new GameObject("Test");
            try
            {
                var s = new FieldAreaStreamer(prefab, new FieldMapBuilder(new PassThrough()), parent.transform, "Map");
                Assert.IsTrue(s.LoadBlock(new BlockId(16, 22)));
                Assert.IsTrue(s.LoadBlock(new BlockId(16, 23)));
                Assert.AreEqual(1, s.BuiltContainers);
                Assert.IsTrue(s.UnloadBlock(new BlockId(16, 22)));
                Assert.AreEqual(1, s.BuiltContainers, "noch von Block (16, 23) gebraucht");
                Assert.IsTrue(s.UnloadBlock(new BlockId(16, 23)));
                Assert.AreEqual(0, s.BuiltContainers);
                Assert.IsFalse(s.LoadBlock(new BlockId(40, 40)), "unbekannter Block");
            }
            finally { Object.DestroyImmediate(parent); Object.DestroyImmediate(prefab); }
        }
    }
}
