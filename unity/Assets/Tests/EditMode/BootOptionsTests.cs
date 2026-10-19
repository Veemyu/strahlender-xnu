using NUnit.Framework;
using Xnu.Boot;

namespace Xnu.Tests
{
    public class BootOptionsTests
    {
        private static string NoEnv(string _) => null;

        [Test]
        public void StartSceneFromCommandLine()
        {
            var args = new[] { "xnu", "-logFile", "x.log", "-xnuScene", "FieldTest2" };
            Assert.AreEqual("FieldTest2", BootOptions.ResolveStartScene(args, NoEnv));
        }

        [Test]
        public void CommandLineBeatsEnvironment()
        {
            var args = new[] { "-xnuScene", "UiTest" };
            Assert.AreEqual("UiTest", BootOptions.ResolveStartScene(args, n => "FieldTest"));
        }

        [Test]
        public void StartSceneFromEnvironmentOrNone()
        {
            Assert.AreEqual("InputTest", BootOptions.ResolveStartScene(new string[0], n => n == BootOptions.SceneEnv ? " InputTest " : null));
            Assert.IsNull(BootOptions.ResolveStartScene(new[] { "-xnuScene" }, NoEnv));
            Assert.IsNull(BootOptions.ResolveStartScene(null, n => ""));
        }

        [Test]
        public void SceneLookupIgnoresCaseAndFolder()
        {
            var paths = new[] { "Assets/Scenes/FieldTest2.unity", "Assets/Scenes/UiTest.unity" };
            Assert.AreEqual("Assets/Scenes/UiTest.unity", BootOptions.FindScenePath(paths, "uitest"));
            Assert.IsNull(BootOptions.FindScenePath(paths, "Missing"));
            Assert.IsNull(BootOptions.FindScenePath(null, "UiTest"));
            Assert.AreEqual("FieldTest2", BootOptions.SceneName(paths[0]));
        }
    }
}
