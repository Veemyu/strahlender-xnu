using NUnit.Framework;
using Xnu.Core.Display;

namespace Xnu.Tests
{
    public class DisplayTests
    {
        [Test]
        public void GleichesVerhaeltnisFuelltAlles()
        {
            var r = AspectMath.Fit(1920, 1080, AspectMode.Aspect16x9);
            Assert.AreEqual(0f, r.X, 1e-5f);
            Assert.AreEqual(1f, r.Width, 1e-5f);
            Assert.AreEqual(1f, r.Height, 1e-5f);
        }

        [Test]
        public void IpadVierZuDreiBekommtBalkenObenUndUnten()
        {
            // iPad Pro 12,9": 2732x2048 (4:3), Ziel 16:9.
            var r = AspectMath.Fit(2732, 2048, AspectMode.Aspect16x9);
            Assert.AreEqual(1f, r.Width, 1e-5f);
            Assert.AreEqual((2732f / 2048f) / (16f / 9f), r.Height, 1e-4f);
            Assert.AreEqual((1f - r.Height) * 0.5f, r.Y, 1e-5f);
            Assert.AreEqual(0f, r.X, 1e-5f);
        }

        [Test]
        public void BreitbildBekommtBalkenLinksUndRechts()
        {
            var r = AspectMath.Fit(2560, 1080, AspectMode.Aspect16x9);
            Assert.AreEqual(1f, r.Height, 1e-5f);
            Assert.Less(r.Width, 1f);
            Assert.AreEqual((1f - r.Width) * 0.5f, r.X, 1e-5f);
        }

        [Test]
        public void RenderGroessenSindGerade()
        {
            Assert.AreEqual((1920, 1080), AspectMath.RenderSize(AspectMode.Aspect16x9));
            Assert.AreEqual((1440, 1080), AspectMath.RenderSize(AspectMode.Aspect4x3));
            Assert.AreEqual((1728, 1080), AspectMath.RenderSize(AspectMode.Aspect16x10));
        }

        [Test]
        public void UngueltigeGroessenWerfenFehler()
        {
            Assert.Throws<System.ArgumentException>(() => AspectMath.Fit(0, 100, 1.5f));
            Assert.Throws<System.ArgumentException>(() => AspectMath.Fit(100, 100, 0f));
        }

        [Test]
        public void SechzigFpsAuf120HzNutztVSyncZaehlerZwei()
        {
            var p = FrameRatePlanner.Plan(FrameRateMode.Fixed60, 120);
            Assert.AreEqual(60, p.TargetFrameRate);
            Assert.AreEqual(2, p.VSyncCount);
            Assert.IsFalse(p.Variable);
        }

        [Test]
        public void OriginalDreissigFpsAuf60HzNutztVSyncZaehlerZwei()
        {
            var p = FrameRatePlanner.Plan(FrameRateMode.Original30, 60);
            Assert.AreEqual(30, p.TargetFrameRate);
            Assert.AreEqual(2, p.VSyncCount);
        }

        [Test]
        public void HundertzwanzigFpsAuf120HzNutztVSyncZaehlerEins()
        {
            var p = FrameRatePlanner.Plan(FrameRateMode.Fixed120, 120);
            Assert.AreEqual(120, p.TargetFrameRate);
            Assert.AreEqual(1, p.VSyncCount);
        }

        [Test]
        public void ZielHoeherAlsAnzeigeBegrenztAufAnzeige()
        {
            var p = FrameRatePlanner.Plan(FrameRateMode.Fixed120, 60);
            Assert.AreEqual(60, p.TargetFrameRate);
            Assert.AreEqual(1, p.VSyncCount);
        }

        [Test]
        public void KeinTeilerSchaltetVSyncAusUndBegrenztPerTarget()
        {
            var p = FrameRatePlanner.Plan(FrameRateMode.Fixed60, 90);
            Assert.AreEqual(60, p.TargetFrameRate);
            Assert.AreEqual(0, p.VSyncCount);
        }

        [Test]
        public void VariableRateSetztNurObergrenze()
        {
            var p = FrameRatePlanner.Plan(FrameRateMode.Variable120, 120);
            Assert.IsTrue(p.Variable);
            Assert.AreEqual(120, p.TargetFrameRate);
            Assert.AreEqual(0, p.VSyncCount);
        }

        [Test]
        public void UngueltigeAnzeigerateWirftFehler()
        {
            Assert.Throws<System.ArgumentOutOfRangeException>(() => FrameRatePlanner.Plan(FrameRateMode.Fixed60, 0));
        }
    }
}
