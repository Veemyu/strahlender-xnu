using System;
using UnityEngine;

namespace Xnu.Boot
{
    public sealed class BundleLoadException : Exception
    {
        public BundleLoadException(string message) : base(message) { }
        public BundleLoadException(string message, Exception inner) : base(message, inner) { }
    }

    // Geladenes Bundle (abstrahiert, damit der Provider ohne Unity-Bundles testbar ist).
    public interface IBundleHandle
    {
        string[] GetAllAssetNames();
        bool IsStreamedSceneBundle { get; }
        UnityEngine.Object LoadAsset(string assetName, Type type);
        void Unload(bool unloadAllLoadedObjects);
    }

    public interface IBundleSource
    {
        // Wirft BundleLoadException, wenn die Datei fehlt oder nicht ladbar ist.
        IBundleHandle Load(string path);
    }

    // Echte Quelle: AssetBundle.LoadFromFile (synchron, Hauptthread).
    public sealed class UnityBundleSource : IBundleSource
    {
        sealed class Handle : IBundleHandle
        {
            readonly AssetBundle _bundle;
            public Handle(AssetBundle b) { _bundle = b; }
            public string[] GetAllAssetNames() => _bundle.GetAllAssetNames();
            public bool IsStreamedSceneBundle => _bundle.isStreamedSceneAssetBundle;
            public UnityEngine.Object LoadAsset(string assetName, Type type) => _bundle.LoadAsset(assetName, type);
            public void Unload(bool unloadAll) => _bundle.Unload(unloadAll);
        }

        public IBundleHandle Load(string path)
        {
            if (!System.IO.File.Exists(path)) throw new BundleLoadException("Bundle-Datei fehlt: " + path);
            var b = AssetBundle.LoadFromFile(path);
            if (b == null) throw new BundleLoadException("AssetBundle.LoadFromFile lieferte null: " + path);
            var i = path.IndexOf("AssetAssistant", StringComparison.Ordinal);
            Debug.Log("[Boot] Bundle geladen: " + (i >= 0 ? path.Substring(i + "AssetAssistant".Length).TrimStart('/') : path)
                      + " (" + new System.IO.FileInfo(path).Length + " Byte)");
            return new Handle(b);
        }
    }
}
