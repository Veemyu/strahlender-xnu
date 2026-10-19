using System.Linq;
using NUnit.Framework;
using Xnu.Render;

namespace Xnu.Tests
{
    // Regeln gegen schwarzes Bild (Messung im Lab: ohne Richtungslicht Bildmittel 0, 0, 0; mit Licht und ohne Globals 31, 39, 23).
    public class RenderChecksTests
    {
        static RenderFacts Good() => new RenderFacts { GeneratedMaterials = 34, ActiveDirectionalLights = 1, BrightestSunIntensity = 1f, GlobalsSet = 26, GlobalsTotal = 35 };

        [Test]
        public void Healthy_NoProblems() => Assert.That(RenderChecks.Evaluate(Good()), Is.Empty);

        [Test]
        public void NoSun_IsBlack()
        {
            var f = Good(); f.ActiveDirectionalLights = 0; f.BrightestSunIntensity = 0;
            var p = RenderChecks.Evaluate(f);
            Assert.That(p.Select(x => x.Kind), Is.EqualTo(new[] { RenderProblemKind.NoSun }));
            Assert.That(RenderChecks.WillBeBlack(f), Is.True);
        }

        [Test]
        public void SunWithoutIntensity_IsBlack()
        {
            var f = Good(); f.BrightestSunIntensity = 0f;
            Assert.That(RenderChecks.Evaluate(f).Select(x => x.Kind), Is.EqualTo(new[] { RenderProblemKind.DarkSun }));
            Assert.That(RenderChecks.WillBeBlack(f), Is.True);
        }

        [Test]
        public void UnsetGlobals_DarkerButNotBlack()
        {
            var f = Good(); f.GlobalsSet = 0;
            Assert.That(RenderChecks.Evaluate(f).Select(x => x.Kind), Is.EqualTo(new[] { RenderProblemKind.GlobalsUnset }));
            Assert.That(RenderChecks.WillBeBlack(f), Is.False);
        }

        [Test]
        public void SeveralSuns_Reported()
        {
            var f = Good(); f.ActiveDirectionalLights = 2;
            Assert.That(RenderChecks.Evaluate(f).Select(x => x.Kind), Is.EqualTo(new[] { RenderProblemKind.SeveralSuns }));
        }

        [Test]
        public void WithoutGeneratedMaterials_NoRules()
        {
            var f = new RenderFacts { GeneratedMaterials = 0, ActiveDirectionalLights = 0, GlobalsTotal = 35 };
            Assert.That(RenderChecks.Evaluate(f), Is.Empty);
        }

        [Test]
        public void NoSunAndNoGlobals_BothReported()
        {
            var f = new RenderFacts { GeneratedMaterials = 1, ActiveDirectionalLights = 0, GlobalsSet = 0, GlobalsTotal = 35 };
            Assert.That(RenderChecks.Evaluate(f).Select(x => x.Kind), Is.EqualTo(new[] { RenderProblemKind.NoSun, RenderProblemKind.GlobalsUnset }));
        }
    }
}
