using NUnit.Framework;
using Xnu.Probe;

namespace Xnu.Tests
{
    public class ProbeMathTests
    {
        private const long Mb = ProbeMath.Mb;

        [Test]
        public void ShouldStop_StopsWhenReserveWouldBeBreached()
        {
            Assert.IsFalse(ProbeMath.ShouldStop(1000 * Mb, 500 * Mb, 128 * Mb, 300 * Mb, 6144 * Mb));
            Assert.IsTrue(ProbeMath.ShouldStop(427 * Mb, 500 * Mb, 128 * Mb, 300 * Mb, 6144 * Mb));
            Assert.IsFalse(ProbeMath.ShouldStop(428 * Mb, 500 * Mb, 128 * Mb, 300 * Mb, 6144 * Mb));
        }

        [Test]
        public void ShouldStop_StopsAtFootprintCap()
        {
            Assert.IsFalse(ProbeMath.ShouldStop(8000 * Mb, 6016 * Mb, 128 * Mb, 300 * Mb, 6144 * Mb));
            Assert.IsTrue(ProbeMath.ShouldStop(8000 * Mb, 6017 * Mb, 128 * Mb, 300 * Mb, 6144 * Mb));
        }

        [Test]
        public void ShouldStop_UnknownAvailableStopsImmediately()
        {
            Assert.IsTrue(ProbeMath.ShouldStop(0, 0, 128 * Mb, 300 * Mb, 6144 * Mb));
            Assert.IsTrue(ProbeMath.ShouldStop(-1, 0, 128 * Mb, 300 * Mb, 6144 * Mb));
        }

        [Test]
        public void Summarize_ComputesRatesAndPercentile()
        {
            var frames = new double[100];
            for (var i = 0; i < frames.Length; i++) frames[i] = 1.0 / 60.0;
            frames[7] = 1.0 / 30.0;
            var s = ProbeMath.Summarize(frames, frames.Length);
            Assert.AreEqual(100, s.Count);
            Assert.AreEqual(100 / (99.0 / 60.0 + 1.0 / 30.0), s.AvgFps, 1e-9);
            Assert.AreEqual(30.0, s.MinFps, 1e-9);
            Assert.AreEqual(60.0, s.MaxFps, 1e-9);
            Assert.AreEqual(1000.0 / 30.0, s.MaxFrameMs, 1e-9);
            Assert.AreEqual(1000.0 / 60.0, s.P99FrameMs, 1e-9);
        }

        [Test]
        public void Summarize_EmptyIsZero()
        {
            var s = ProbeMath.Summarize(new double[4], 0);
            Assert.AreEqual(0, s.Count);
            Assert.AreEqual(0.0, s.AvgFps);
        }
    }
}
