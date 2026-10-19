using System;
using System.Collections.Generic;
using System.IO;

namespace Xnu.Boot
{
    // Lädt Bundles samt Abhängigkeiten mit Referenzzähler. Nur Hauptthread.
    // Acquire(X) erhöht den Zähler von X und aller (transitiven) Abhängigkeiten um 1;
    // Release(X) senkt sie wieder. Bei 0 wird das Bundle entladen.
    public sealed class BundleProvider : IDisposable
    {
        sealed class Loaded
        {
            public IBundleHandle Handle;
            public int RefCount;
        }

        readonly BundleCatalog _catalog;
        readonly string _root;
        readonly IBundleSource _source;
        readonly Dictionary<BundleRecord, Loaded> _loaded = new Dictionary<BundleRecord, Loaded>();

        public bool UnloadAllLoadedObjects { get; set; } = true;

        // Optional: Abhängigkeiten, für die der Filter false liefert, werden nicht geladen
        // (z. B. das Shader-Bundle der Originalspiel-Shader, die nicht gerendert werden dürfen).
        public Func<BundleRecord, bool> DependencyFilter { get; set; }

        List<BundleRecord> Closure(BundleRecord record)
        {
            var chain = _catalog.GetDependencyClosure(record);
            if (DependencyFilter != null) chain.RemoveAll(r => !DependencyFilter(r));
            return chain;
        }
        public BundleCatalog Catalog => _catalog;
        public int LoadedBundleCount => _loaded.Count;

        public BundleProvider(BundleCatalog catalog, string rootDirectory, IBundleSource source)
        {
            _catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
            _root = rootDirectory ?? throw new ArgumentNullException(nameof(rootDirectory));
            _source = source ?? throw new ArgumentNullException(nameof(source));
        }

        public string GetBundlePath(BundleRecord record) =>
            Path.Combine(_root, record.Project ?? "", record.Name.Replace('/', Path.DirectorySeparatorChar));

        public bool IsLoaded(string bundleName) =>
            _catalog.TryGetBundle(bundleName, out var r) && _loaded.ContainsKey(r);

        public int GetRefCount(string bundleName) =>
            _catalog.TryGetBundle(bundleName, out var r) && _loaded.TryGetValue(r, out var l) ? l.RefCount : 0;

        public IBundleHandle GetHandle(string bundleName) =>
            _catalog.TryGetBundle(bundleName, out var r) && _loaded.TryGetValue(r, out var l) ? l.Handle : null;

        // Lädt das Bundle und seine Abhängigkeiten (Abhängigkeiten zuerst). Bei Fehlern wird zurückgerollt.
        public IBundleHandle Acquire(string bundleName)
        {
            var record = _catalog.GetBundle(bundleName);
            var chain = Closure(record);
            chain.Add(record);

            var acquired = new List<BundleRecord>(chain.Count);
            try
            {
                for (var i = 0; i < chain.Count; i++)
                {
                    Increment(chain[i]);
                    acquired.Add(chain[i]);
                }
            }
            catch
            {
                for (var i = acquired.Count - 1; i >= 0; i--) Decrement(acquired[i]);
                throw;
            }
            return _loaded[record].Handle;
        }

        void Increment(BundleRecord r)
        {
            if (_loaded.TryGetValue(r, out var l)) { l.RefCount++; return; }
            var handle = _source.Load(GetBundlePath(r));
            _loaded[r] = new Loaded { Handle = handle, RefCount = 1 };
        }

        void Decrement(BundleRecord r)
        {
            var l = _loaded[r];
            if (--l.RefCount > 0) return;
            _loaded.Remove(r);
            l.Handle.Unload(UnloadAllLoadedObjects);
        }

        // Gegenstück zu Acquire. true, wenn das Bundle selbst entladen wurde.
        public bool Release(string bundleName)
        {
            var record = _catalog.GetBundle(bundleName);
            if (!_loaded.ContainsKey(record))
                throw new InvalidOperationException("Bundle ist nicht geladen: " + record.FullName);
            var chain = Closure(record);
            Decrement(record);
            var unloaded = !_loaded.ContainsKey(record);
            foreach (var dep in chain) Decrement(dep);
            return unloaded;
        }

        // Lädt ein Asset über logischen Namen. Das Bundle bleibt (Zähler +1) geladen,
        // bis der Aufrufer Release(bundle.FullName) ruft. Bei null wird der Zähler zurückgenommen.
        public T LoadAsset<T>(string key, out BundleRecord bundle) where T : UnityEngine.Object
        {
            bundle = null;
            if (!_catalog.TryResolveAsset(key, out var entry)) return null;
            var handle = Acquire(entry.Bundle.FullName);
            var asset = handle.LoadAsset(entry.AssetPath, typeof(T)) as T;
            if (asset == null) { Release(entry.Bundle.FullName); return null; }
            bundle = entry.Bundle;
            return asset;
        }

        public void UnloadAll()
        {
            var all = new List<Loaded>(_loaded.Values);
            _loaded.Clear();
            foreach (var l in all) l.Handle.Unload(UnloadAllLoadedObjects);
        }

        public void Dispose() => UnloadAll();
    }
}
