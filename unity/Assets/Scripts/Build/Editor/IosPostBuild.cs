#if UNITY_IOS
using System.IO;
using UnityEditor;
using UnityEditor.Callbacks;
using UnityEditor.iOS.Xcode;

namespace Xnu.Build.Editor
{
    // Unity erzeugt das Xcode-Projekt bei jedem iOS-Build neu. Damit das Entitlement
    // „Increased Memory Limit“ nicht verloren geht, tragen wir es nach dem Build selbst ein.
    // Team-ID und Signatur setzt weiterhin scripts/ios_deploy.sh (nie im Projekt).
    public static class IosPostBuild
    {
        private const string EntitlementsFile = "Xnu.entitlements";
        private const string IncreasedMemoryLimit = "com.apple.developer.kernel.increased-memory-limit";

        [PostProcessBuild(100)]
        public static void OnPostBuild(BuildTarget target, string buildPath)
        {
            if (target != BuildTarget.iOS) return;

            var projectPath = PBXProject.GetPBXProjectPath(buildPath);
            var project = new PBXProject();
            project.ReadFromFile(projectPath);
            var mainTarget = project.GetUnityMainTargetGuid();

            var plist = new PlistDocument();
            plist.Create();
            plist.root.SetBoolean(IncreasedMemoryLimit, true);
            plist.WriteToFile(Path.Combine(buildPath, EntitlementsFile));

            project.AddFile(EntitlementsFile, EntitlementsFile);
            project.SetBuildProperty(mainTarget, "CODE_SIGN_ENTITLEMENTS", EntitlementsFile);
            project.WriteToFile(projectPath);
        }
    }
}
#endif
