using System;
using System.IO;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace Xnu.Render.Editor
{
    // Vor jedem Player-Build: die erzeugten Shader (nicht im Repo) nach Assets/XnuGenerated/Resources kopieren, damit der Player
    // sie per Shader.Find findet (Dateien in Resources sind im Build enthalten). Ohne Quelle (kein variants.json) bleibt der Build
    // unverändert und das Feld fällt auf das Ersatzmaterial zurück; der Build schlägt deshalb nie daran fehl.
    public sealed class GeneratedShaderBuildSync : IPreprocessBuildWithReport
    {
        public int callbackOrder => -100;

        public void OnPreprocessBuild(BuildReport report)
        {
            try
            {
                var src = GeneratedShaderSync.FindSourceDirectory();
                if (src == null)
                {
                    Debug.LogWarning("[Render] Keine erzeugten Shader (variants.json) gefunden: der Build nutzt das Ersatzmaterial. " +
                                     "scripts/shader_build.sh ausführen oder XNU_SHADERS setzen.");
                    return;
                }
                Debug.Log("[Render] Vor dem Build: " + GeneratedShaderSync.Sync(src));
            }
            catch (Exception e)
            {
                Debug.LogWarning("[Render] Shader-Abgleich vor dem Build fehlgeschlagen: " + e.Message);
            }
        }
    }
}
