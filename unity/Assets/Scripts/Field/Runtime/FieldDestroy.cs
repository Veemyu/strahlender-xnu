using UnityEngine;

namespace Xnu.Field
{
    // Zerstören im Spiel (Destroy, am Bildende) und im Editor ohne Spielmodus (DestroyImmediate, z. B. für das
    // Prüfwerkzeug Xnu/Field/Verify im Batchmodus).
    public static class FieldDestroy
    {
        public static void Kill(Object o)
        {
            if (o == null) return;
            if (Application.isPlaying) Object.Destroy(o); else Object.DestroyImmediate(o);
        }
    }
}
