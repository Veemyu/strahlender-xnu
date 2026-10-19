using System;
using System.Collections.Generic;
using UnityEngine;
using Xnu.Boot;
using Xnu.Core;

namespace Xnu.UI
{
    // Lädt Original-UI-Bundles (Prefabs, Sprites) für die Fenster. Original-Shader-Bundles werden nie geladen;
    // von den Sprachvarianten (.en .fr …) kommt nur die deutsche (.ge), sonst lehnt Unity doppelte Dateinamen ab (docs/ui-spezifikation-2.md 2.3).
    // Nur Hauptthread. Bundles bleiben für die Laufzeit geladen (residente Fenster), Objekte werden nicht entladen.
    public static class UiBundles
    {
        public const string WindowBundle = "UIs/ui/uiresidentwindow";

        static BundleProvider _provider;
        static string _error;
        static readonly Dictionary<string, Sprite> IconCache = new Dictionary<string, Sprite>();
        static readonly Dictionary<string, GameObject> PrefabCache = new Dictionary<string, GameObject>();

        public static string Error => _error;
        public static bool IsReady => _provider != null;
        public static int LoadedBundles => _provider?.LoadedBundleCount ?? 0;
        public static BundleProvider Provider => _provider;

        // true für Bundles, die nicht geladen werden dürfen: Shader (Originalshader) und fremde Sprachvarianten.
        public static bool IsExcluded(BundleRecord r)
        {
            if (r.Name == "shaders" || r.Name.EndsWith("/shaders", StringComparison.Ordinal)) return true;
            foreach (var p in r.AssetPaths)
                if (p.EndsWith(".shader", StringComparison.OrdinalIgnoreCase) || p.EndsWith(".shadervariants", StringComparison.OrdinalIgnoreCase)) return true;
            return IsForeignLanguageVariant(r.Name);
        }

        public static bool IsForeignLanguageVariant(string bundleName) =>
            bundleName.Length > 3 && bundleName[bundleName.Length - 3] == '.' && !bundleName.EndsWith(".ge", StringComparison.Ordinal);

        // Katalog und Provider einmalig anlegen. false: keine Spieldaten (dann bleiben die eigenen Fenster).
        public static bool EnsureProvider()
        {
            if (_provider != null) return true;
            if (_error != null) return false;
            try
            {
                var report = BootSequence.Run(GameDataPaths.AssetAssistant, new UnityBundleSource());
                if (!report.Success) { _error = "Katalog nicht nutzbar"; return false; }
                _provider = report.Provider;
                _provider.UnloadAllLoadedObjects = false;
                _provider.DependencyFilter = r => !IsExcluded(r);
                if (!_atlasHooked)
                {
                    UnityEngine.U2D.SpriteAtlasManager.atlasRequested += OnAtlasRequested;
                    _atlasHooked = true;
                }
                return true;
            }
            catch (Exception e)
            {
                _error = e.GetType().Name + ": " + e.Message;
                return false;
            }
        }

        // Asset über den logischen Schlüssel; bei Sprachvarianten (mehrere Bundles, gleicher Schlüssel) die deutsche.
        public static T LoadAsset<T>(string key) where T : UnityEngine.Object
        {
            if (!EnsureProvider()) return null;
            if (_provider.Catalog.TryResolveAsset(key, out _)) return _provider.LoadAsset<T>(key, out _);
            foreach (var c in _provider.Catalog.GetAssetCandidates(key))
            {
                if (IsForeignLanguageVariant(c.Bundle.Name)) continue;
                var handle = _provider.Acquire(c.Bundle.FullName);
                var asset = handle.LoadAsset(c.AssetPath, typeof(T)) as T;
                if (asset != null) return asset;
                _provider.Release(c.Bundle.FullName);
            }
            return null;
        }

        static Dictionary<string, string> _atlasKeys;
        public static int AtlasRequests { get; private set; }
        public static int AtlasDelivered { get; private set; }

        // Sprite-Atlanten, die das Original zur Laufzeit nachreicht (SpriteAtlasManager.atlasRequested): Tag = Atlasname.
        static void OnAtlasRequested(string tag, Action<UnityEngine.U2D.SpriteAtlas> deliver)
        {
            AtlasRequests++;
            if (_provider == null) return;
            if (_atlasKeys == null)
            {
                _atlasKeys = new Dictionary<string, string>();
                foreach (var r in _provider.Catalog.Records)
                {
                    if (r.Project != "UIs" || IsForeignLanguageVariant(r.Name)) continue;
                    foreach (var p in r.AssetPaths)
                        if (p.EndsWith(".spriteatlas", StringComparison.OrdinalIgnoreCase))
                            _atlasKeys[System.IO.Path.GetFileNameWithoutExtension(p).ToLowerInvariant()] = AssetKey.ToLogicalKey(p);
                }
            }
            if (!_atlasKeys.TryGetValue(tag.ToLowerInvariant(), out var key)) { Debug.LogWarning("[UI] Atlas nicht gefunden: " + tag); return; }
            var atlas = LoadAsset<UnityEngine.U2D.SpriteAtlas>(key);
            if (atlas == null) { Debug.LogWarning("[UI] Atlas nicht ladbar: " + tag); return; }
            AtlasDelivered++;
            deliver(atlas);
        }

        static bool _atlasHooked;

        // Prefab über den logischen Schlüssel (z. B. "ui/prefab/xmenu"). null, wenn nicht ladbar.
        public static GameObject LoadPrefab(string key)
        {
            if (PrefabCache.TryGetValue(key, out var cached) && cached != null) return cached;
            if (!EnsureProvider()) return null;
            try
            {
                var go = LoadAsset<GameObject>(key);
                if (go == null) { _error = "Prefab nicht gefunden: " + key; return null; }
                PrefabCache[key] = go;
                return go;
            }
            catch (Exception e)
            {
                _error = key + ": " + e.GetType().Name + ": " + e.Message;
                return null;
            }
        }

        // Pokémon-Icon (Stil „dp“, 1.302 Texturen): Schlüssel pm{Art:0000}_{Form:00}_00_00_dp. null, wenn nicht vorhanden.
        public static Sprite LoadPokemonIcon(int monsNo, int form)
        {
            var key = "textures_mass/pokemon_dp/pm" + monsNo.ToString("0000") + "_" + form.ToString("00") + "_00_00_dp";
            if (IconCache.TryGetValue(key, out var s)) return s;
            Sprite sprite = null;
            if (EnsureProvider())
            {
                try
                {
                    var tex = LoadAsset<Texture2D>(key);
                    if (tex != null)
                        sprite = Sprite.Create(tex, new Rect(0, 0, tex.width, tex.height), new Vector2(0.5f, 0.5f), 100f);
                }
                catch (Exception e) { _error = key + ": " + e.Message; }
            }
            IconCache[key] = sprite;
            return sprite;
        }

        public static void Shutdown()
        {
            PrefabCache.Clear();
            IconCache.Clear();
            _provider?.UnloadAll();
            _provider = null;
            _error = null;
            _atlasKeys = null;
        }
    }
}
