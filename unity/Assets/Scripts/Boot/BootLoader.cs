using UnityEngine;
using Xnu.Core;

namespace Xnu.Boot
{
    // Startpunkt: prüft die Spieldaten-Pfade, liest den Bundle-Katalog und legt den BundleProvider an.
    // Nur Log-Ausgabe, keine UI.
    public sealed class BootLoader : MonoBehaviour
    {
        [SerializeField] string[] preloadBundles = new string[0];

        public BootReport Report { get; private set; }
        public BundleCatalog Catalog => Report?.Catalog;
        public BundleProvider Provider => Report?.Provider;

        void Start()
        {
            Debug.Log("[Boot] Start, GameData-Root: " + GameDataPaths.Root);
            Report = BootSequence.Run(GameDataPaths.AssetAssistant, new UnityBundleSource(), LogStep);
            if (!Report.Success)
            {
                Debug.LogError("[Boot] Abbruch: Spieldaten nicht nutzbar. XNU_GAMEDATA setzen (Ordner mit romfs/Data/StreamingAssets).");
                return;
            }

            foreach (var name in preloadBundles)
            {
                if (string.IsNullOrWhiteSpace(name)) continue;
                try
                {
                    var h = Provider.Acquire(name);
                    Debug.Log("[Boot] Bundle geladen: " + name + " (" + h.GetAllAssetNames().Length + " Assets)");
                }
                catch (System.Exception e)
                {
                    Debug.LogError("[Boot] Bundle " + name + " nicht ladbar: " + e.Message);
                }
            }
            Debug.Log("[Boot] Fertig, " + Provider.LoadedBundleCount + " Bundles geladen");
        }

        static void LogStep(BootStep s)
        {
            var text = "[Boot] " + s.Name + ": " + s.Message;
            if (s.Status == BootStatus.Fail) Debug.LogError(text);
            else if (s.Status == BootStatus.Warn) Debug.LogWarning(text);
            else Debug.Log(text);
        }

        void OnDestroy() => Provider?.UnloadAll();
    }
}
