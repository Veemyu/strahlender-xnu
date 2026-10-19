using UnityEditor;
using UnityEditor.Rendering;
using UnityEngine;
using UnityEngine.Rendering;

namespace Xnu.Render.Editor
{
    // Die erzeugten Forward-Shader lesen den Bildschirmschatten (_ShadowMapTexture, Pass „Screen Space Shadows“). Die iOS-Stufen
    // (Graphics Tiers) schalten „Cascaded Shadows“ standardmäßig ab: dann erzeugt Unity keinen Bildschirmschatten, sondern bindet die
    // Schattenkarte selbst, und die Shader lesen Unsinn – das ganze Bild liegt im Schatten (Zone 24: Bildmittel 62/74/82 statt 87/102/111,
    // docs/sichtpruefung-3.md). Das betrifft den Editor mit aktivem Ziel iOS (Mac-Vorschau) und die iPad-App. Die Einstellung wird
    // beim Laden des Editors erzwungen (idempotent) und steht dann in ProjectSettings/GraphicsSettings.asset.
    [InitializeOnLoad]
    public static class RenderProjectSettings
    {
        static readonly BuildTargetGroup[] Groups = { BuildTargetGroup.iOS, BuildTargetGroup.Standalone };
        static readonly GraphicsTier[] Tiers = { GraphicsTier.Tier1, GraphicsTier.Tier2, GraphicsTier.Tier3 };

        static RenderProjectSettings() => EditorApplication.delayCall += () => Enforce();

        // Liefert die Zahl der geänderten Stufen.
        public static int Enforce()
        {
            var changed = 0;
            foreach (var g in Groups)
                foreach (var t in Tiers)
                {
                    var s = EditorGraphicsSettings.GetTierSettings(g, t);
                    if (s.cascadedShadowMaps) continue;
                    s.cascadedShadowMaps = true;
                    EditorGraphicsSettings.SetTierSettings(g, t, s);
                    changed++;
                }
            if (changed > 0)
            {
                AssetDatabase.SaveAssets();
                Debug.Log("[Render] Graphics Tiers: Cascaded Shadows eingeschaltet (" + changed + " Stufen), nötig für den Bildschirmschatten der erzeugten Shader.");
            }
            return changed;
        }

        public static bool AllEnabled()
        {
            foreach (var g in Groups)
                foreach (var t in Tiers)
                    if (!EditorGraphicsSettings.GetTierSettings(g, t).cascadedShadowMaps) return false;
            return true;
        }
    }
}
