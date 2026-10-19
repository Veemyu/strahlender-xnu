using NUnit.Framework;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace Xnu.Tests
{
    // Schützt die gemessenen Render-Vorgaben des Originals (docs/render-treue.md):
    // Built-in-Pipeline, Gamma, nur Metal, kein MSAA, Schattenentfernung 20.
    public class RenderSettingsTests
    {
        [Test]
        public void BuiltInPipelineOhneScriptableRenderPipeline()
        {
            Assert.IsNull(GraphicsSettings.defaultRenderPipeline);
        }

        [Test]
        public void FarbraumIstGamma()
        {
            Assert.AreEqual(ColorSpace.Gamma, PlayerSettings.colorSpace);
        }

        [Test]
        public void NurMetalAufMacUndIos()
        {
            CollectionAssert.AreEqual(new[] { GraphicsDeviceType.Metal }, PlayerSettings.GetGraphicsAPIs(BuildTarget.StandaloneOSX));
            CollectionAssert.AreEqual(new[] { GraphicsDeviceType.Metal }, PlayerSettings.GetGraphicsAPIs(BuildTarget.iOS));
        }

        [Test]
        public void QualitaetEntsprichtOriginal()
        {
            var level = QualitySettings.names.Length - 1;
            var previous = QualitySettings.GetQualityLevel();
            try
            {
                QualitySettings.SetQualityLevel(level, false);
                Assert.AreEqual(ShadowQuality.All, QualitySettings.shadows);
                Assert.AreEqual(20f, QualitySettings.shadowDistance, 0.01f);
                Assert.AreEqual(0, QualitySettings.antiAliasing);
            }
            finally
            {
                QualitySettings.SetQualityLevel(previous, false);
            }
        }

        [Test]
        public void AllePlattformenNutzenDieOriginalStufe()
        {
            var path = System.IO.Path.Combine(Application.dataPath, "..", "ProjectSettings", "QualitySettings.asset");
            var last = (QualitySettings.names.Length - 1).ToString();
            var inDefaults = false;
            var checkedPlatforms = 0;
            foreach (var raw in System.IO.File.ReadAllLines(path))
            {
                if (raw.StartsWith("  m_PerPlatformDefaultQuality:")) { inDefaults = true; continue; }
                if (!inDefaults) continue;
                if (!raw.StartsWith("    ")) break;
                Assert.AreEqual(last, raw.Substring(raw.LastIndexOf(':') + 1).Trim(), raw);
                checkedPlatforms++;
            }
            Assert.Greater(checkedPlatforms, 5);
        }

        [Test]
        public void HdrDisplayAus()
        {
            Assert.IsFalse(PlayerSettings.useHDRDisplay);
        }
    }
}
