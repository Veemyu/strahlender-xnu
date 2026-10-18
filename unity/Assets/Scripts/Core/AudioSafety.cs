using UnityEngine;

namespace Xnu.Core
{
    // Sicherheitsnetz (Nutzervorgabe): Ton ist standardmäßig komplett aus, damit kein Test,
    // Build oder Start je Ton erzeugt. Aktivierbar nur mit dem Compile-Symbol XNU_ALLOW_AUDIO.
    // Ändert nur die Lautstärke innerhalb der App, nie die Lautstärke des Geräts.
    public static class AudioSafety
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        private static void Apply()
        {
#if !XNU_ALLOW_AUDIO
            AudioListener.volume = 0f;
            AudioListener.pause = true;
#endif
        }
    }
}
