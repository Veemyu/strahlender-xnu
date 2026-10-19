using UnityEngine;

namespace Xnu.Render
{
    // Der Bildschirmschatten (_ShadowMapTexture) wird nur in Bildern gesetzt, in denen Unity eine Schattenkarte erzeugt
    // (mindestens ein Schattenwerfer innerhalb der Schattenentfernung). Sonst bleibt der Wert des letzten Bildes stehen: nach einer
    // Zone mit Schatten ein freigegebener Verweis (null). Die Forward-Shader lesen ihn trotzdem, null bindet Schwarz = alles liegt
    // im Schatten (Zone 422 nach Zone 54 rund 19 % dunkler, docs/sichtpruefung-2.md). Der Wächter setzt vor jedem Kamerabild
    // die weiße Standardtextur („kein Schatten“); erzeugt Unity im Bild eine Schattenkarte, überschreibt sie den Wert danach.
    public static class ShadowMapGuard
    {
        public const string GlobalName = "_ShadowMapTexture";
        static readonly int Id = Shader.PropertyToID(GlobalName);
        static bool _installed;

        public static bool Installed => _installed;

        public static void Install()
        {
            if (_installed) return;
            _installed = true;
            Camera.onPreRender += OnPreRender;
            Reset();
        }

        public static void Uninstall()
        {
            if (!_installed) return;
            _installed = false;
            Camera.onPreRender -= OnPreRender;
        }

        static void OnPreRender(Camera cam) => Reset();

        public static void Reset() => Shader.SetGlobalTexture(Id, Texture2D.whiteTexture);
    }
}
