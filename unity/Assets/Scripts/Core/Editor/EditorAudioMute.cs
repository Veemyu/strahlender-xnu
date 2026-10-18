using UnityEditor;

namespace Xnu.Core.Editor
{
    // Editor stumm schalten (Nutzervorgabe: nie Ton). Gilt beim Start und nach jedem Domain-Reload.
    [InitializeOnLoad]
    public static class EditorAudioMute
    {
        static EditorAudioMute()
        {
#if !XNU_ALLOW_AUDIO
            EditorUtility.audioMasterMute = true;
#endif
        }
    }
}
