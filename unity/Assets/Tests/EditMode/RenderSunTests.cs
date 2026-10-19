using NUnit.Framework;
using UnityEngine;
using Xnu.Render;

namespace Xnu.Tests
{
    // SunLight im Editor ohne Spielmodus: legt ein Richtungslicht an, findet auch DontSave-Lichter und zählt für RenderChecks.
    public class RenderSunTests
    {
        GameObject _extra;
        readonly System.Collections.Generic.List<Light> _disabled = new System.Collections.Generic.List<Light>();

        [SetUp]
        public void SetUp()
        {
            _disabled.Clear();
            foreach (var l in Object.FindObjectsByType<Light>(FindObjectsSortMode.None))
                if (l.type == LightType.Directional && l.enabled) { l.enabled = false; _disabled.Add(l); }   // vorhandene Szenenlichter zeitweise aus
        }

        [TearDown]
        public void TearDown()
        {
            if (_extra != null) Object.DestroyImmediate(_extra);
            foreach (var l in Resources.FindObjectsOfTypeAll<Light>())
                if (l != null && l.gameObject.scene.IsValid() && l.gameObject.name == "FieldSun") Object.DestroyImmediate(l.gameObject);
            foreach (var l in _disabled) if (l != null) l.enabled = true;
            _disabled.Clear();
        }

        [Test]
        public void Ensure_CreatesOnceAndReusesIt()
        {
            Assert.That(SunLight.FindActive(), Is.Null);
            var a = SunLight.Ensure();
            var b = SunLight.Ensure();
            Assert.That(a, Is.Not.Null);
            Assert.That(b, Is.SameAs(a));
            Assert.That(a.type, Is.EqualTo(LightType.Directional));
            Assert.That(a.intensity, Is.EqualTo(1f));
            Assert.That(SunLight.Collect(null, 1).ActiveDirectionalLights, Is.EqualTo(1));
        }

        [Test]
        public void DontSaveLight_IsFound()
        {
            _extra = new GameObject("TestSun") { hideFlags = HideFlags.DontSave };
            var l = _extra.AddComponent<Light>();
            l.type = LightType.Directional; l.intensity = 0.5f;
            Assert.That(SunLight.FindActive(), Is.SameAs(l));
            Assert.That(SunLight.Ensure(), Is.SameAs(l));
        }

        [Test]
        public void Collect_NoLight_ReportsNoSunAndBlack()
        {
            var f = SunLight.Collect(new GameGlobals(new UnityGlobalSink()), 5);
            Assert.That(f.ActiveDirectionalLights, Is.EqualTo(0));
            Assert.That(RenderChecks.WillBeBlack(f), Is.True);
        }
    }
}
