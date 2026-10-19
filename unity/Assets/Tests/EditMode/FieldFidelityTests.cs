using System;
using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
using UnityEngine;
using Xnu.Field;
using Xnu.Render;

namespace Xnu.Tests
{
    // Feldoptik (docs/sichtpruefung-3.md): NPC-Modelle aus CharacterGraphics, Marker als Rückfall, Materialexport-Suche, Kamera-Ausstattung.
    public class FieldFidelityTests
    {
        const string GraphicsJson = "{\"class\":\"CharacterGraphics\",\"instances\":[{\"name\":\"CharacterGraphics_data\",\"data\":{\"Data\":[" +
            "{\"ID\":\"pc0001_00_hero\",\"FieldGraphic\":\"fc0001_00\",\"Scale\":1.0}," +
            "{\"ID\":\"tr0000_00_mother\",\"FieldGraphic\":\"fc2005_00\",\"Scale\":1.100000023841858}," +
            "{\"ID\":\"\",\"FieldGraphic\":\"\",\"Scale\":1.0}]}}]}";

        [Test]
        public void CharacterGraphicsLiestModellnamenUndGroesse()
        {
            var t = CharacterGraphicsTable.Parse(GraphicsJson);
            Assert.AreEqual(3, t.Count);
            Assert.IsTrue(t.TryGet(1, out var e));
            Assert.AreEqual("fc2005_00", e.FieldGraphic);
            Assert.AreEqual("Characters/persons/field/fc2005_00", e.BundleName);
            Assert.AreEqual(1.1f, e.Scale, 1e-5f);
        }

        [Test]
        public void CharacterGraphicsKennztObjekteUndLuecken()
        {
            var t = CharacterGraphicsTable.Parse(GraphicsJson);
            Assert.IsFalse(t.TryGet(2, out _), "Eintrag ohne FieldGraphic");
            Assert.IsFalse(t.TryGet(500, out _), "Index 500 (Item-Ball) ist keine Figur");
            Assert.IsFalse(t.TryGet(-1, out _), "-1 = unsichtbar");
        }

        [Test]
        public void CharacterGraphicsLehntFalscheWurzelAb()
        {
            Assert.Throws<FormatException>(() => CharacterGraphicsTable.Parse("{\"class\":\"X\"}"));
        }

        [Test]
        public void NpcAnsichtZeigtMarkerWennKeinModellAufloesbarIst()
        {
            var shader = Shader.Find("Sprites/Default");
            Assert.IsNotNull(shader);
            var root = new GameObject("test").transform;
            var view = new FieldNpcView(root, shader);
            try
            {
                var asked = 0;
                view.ModelFactory = (p, parent) => { asked++; return null; };
                var npc = new PlacementRecord { Id = "A", GraphicIndex = 3, WorkFlag = 4000, DoNotLoadFlag = 4000, X = 10, Y = 10 };
                view.Refresh(new[] { npc }, 10, 10, 5, null, (x, y) => 0f);
                Assert.AreEqual(1, asked);
                Assert.AreEqual(1, view.LiveCount);
                Assert.AreEqual(0, view.ModelCount, "ohne Modell zählt nur der Marker");
                view.Refresh(new[] { npc }, 10, 10, 5, null, (x, y) => 0f);
                Assert.AreEqual(1, asked, "ein vorhandener NPC wird nicht erneut angefragt");
            }
            finally
            {
                view.Destroy();
                UnityEngine.Object.DestroyImmediate(root.gameObject);
            }
        }

        [Test]
        public void MaterialexportWirdImMaterialordnerUndImAllOrdnerGesucht()
        {
            var baseDir = Path.Combine(Path.GetDirectoryName(Application.dataPath), "Temp", "xnu-fidelity-test");
            var main = Path.Combine(baseDir, "materials");
            var all = Path.Combine(baseDir, "materials_all");
            Directory.CreateDirectory(main);
            Directory.CreateDirectory(all);
            var old = Environment.GetEnvironmentVariable(GeneratedShaderLibrary.MaterialsEnvVar);
            try
            {
                File.WriteAllText(Path.Combine(main, "Environments__fields__a.json"), "{}");
                File.WriteAllText(Path.Combine(all, "Characters__persons__field__fc0001_00.json"), "{}");
                Environment.SetEnvironmentVariable(GeneratedShaderLibrary.MaterialsEnvVar, main);
                Assert.AreEqual(Path.Combine(main, "Environments__fields__a.json"), GeneratedShaderLibrary.FindMaterialFile("Environments/fields/a"));
                Assert.AreEqual(Path.Combine(all, "Characters__persons__field__fc0001_00.json"), GeneratedShaderLibrary.FindMaterialFile("Characters/persons/field/fc0001_00"));
                Assert.IsNull(GeneratedShaderLibrary.FindMaterialFile("Characters/persons/field/fc9999_00"));
            }
            finally
            {
                Environment.SetEnvironmentVariable(GeneratedShaderLibrary.MaterialsEnvVar, old);
                Directory.Delete(baseDir, true);
            }
        }

        [Test]
        public void IosStufenSchaltenCascadedShadowsFuerDenBildschirmschattenEin()
        {
            foreach (var g in new[] { UnityEditor.BuildTargetGroup.iOS, UnityEditor.BuildTargetGroup.Standalone })
                foreach (var t in new[] { UnityEngine.Rendering.GraphicsTier.Tier1, UnityEngine.Rendering.GraphicsTier.Tier2, UnityEngine.Rendering.GraphicsTier.Tier3 })
                    Assert.IsTrue(UnityEditor.Rendering.EditorGraphicsSettings.GetTierSettings(g, t).cascadedShadowMaps, g + " " + t);
        }

        [Test]
        public void KameraAusstattungIstIdempotentUndEntferntNurEigenes()
        {
            var go = new GameObject("rigtest", typeof(Camera));
            try
            {
                var cam = go.GetComponent<Camera>();
                var rig = FieldRenderRig.Attach(cam, null, true, true, 0.5f);
                Assert.IsNotNull(rig.Depth);
                Assert.IsNotNull(rig.Post);
                Assert.IsNotNull(rig.Reflection);
                var rig2 = FieldRenderRig.Attach(cam, null, false, true);
                Assert.AreSame(rig.Depth, rig2.Depth);
                Assert.AreSame(rig.Post, rig2.Post);
                Assert.IsNull(rig2.Reflection);
                var reflectionObject = rig.Reflection.gameObject;
                rig.Detach();
                Assert.IsTrue(reflectionObject == null, "Reflexionskamera entfernt");
                Assert.IsTrue(cam.GetComponent<PostChain>() == null, "Nachbearbeitung gehörte dem ersten Anlegen");
                Assert.IsTrue(cam.GetComponent<DepthCaptureDriver>() == null);
            }
            finally { UnityEngine.Object.DestroyImmediate(go); }
        }
    }
}
