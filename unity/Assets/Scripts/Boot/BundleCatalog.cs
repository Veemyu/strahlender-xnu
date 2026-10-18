using System;
using System.Collections.Generic;
using System.IO;

namespace Xnu.Boot
{
    public readonly struct AssetEntry
    {
        public readonly BundleRecord Bundle;
        public readonly string AssetPath;
        public AssetEntry(BundleRecord bundle, string assetPath) { Bundle = bundle; AssetPath = assetPath; }
    }

    // Katalog aller Bundles: Name -> Datei/Größe/Hash/Abhängigkeiten/enthaltene Asset-Pfade.
    // Quelle ist bevorzugt Dpr.bin (BinaryFormatter-Manifest), ersatzweise ein Verzeichnis-Scan
    // (dann ohne Abhängigkeiten und Asset-Pfade).
    public sealed class BundleCatalog
    {
        public const int SupportedVersion = 6;
        public const string CatalogFileName = "Dpr.bin";
        const string ManifestClassSuffix = "AssetBundleDownloadManifest";

        public int Version { get; }
        public string ProjectName { get; }
        public bool FromManifest { get; }
        public IReadOnlyList<BundleRecord> Records => _records;
        public IReadOnlyList<string> Variants => _variants;
        public int AssetCount { get; private set; }
        public int AmbiguousLogicalKeyCount => _collisions.Count;

        readonly BundleRecord[] _records;
        readonly string[] _variants;
        readonly Dictionary<string, BundleRecord> _byFullName = new Dictionary<string, BundleRecord>(StringComparer.OrdinalIgnoreCase);
        readonly Dictionary<string, BundleRecord> _byName = new Dictionary<string, BundleRecord>(StringComparer.OrdinalIgnoreCase);
        readonly Dictionary<string, AssetEntry> _byPath = new Dictionary<string, AssetEntry>(StringComparer.Ordinal);
        readonly Dictionary<string, AssetEntry> _byLogical = new Dictionary<string, AssetEntry>(StringComparer.Ordinal);
        readonly Dictionary<string, List<AssetEntry>> _collisions = new Dictionary<string, List<AssetEntry>>(StringComparer.Ordinal);

        public BundleCatalog(IEnumerable<BundleRecord> records, int version = SupportedVersion,
            string projectName = "", IEnumerable<string> variants = null, bool fromManifest = true)
        {
            Version = version;
            ProjectName = projectName ?? "";
            FromManifest = fromManifest;
            _records = new List<BundleRecord>(records).ToArray();
            _variants = variants == null ? Array.Empty<string>() : new List<string>(variants).ToArray();

            foreach (var r in _records)
            {
                if (string.IsNullOrEmpty(r.Name)) throw new InvalidDataException("Katalogeintrag ohne Namen");
                if (_byFullName.ContainsKey(r.FullName))
                    throw new InvalidDataException("Doppelter Katalogeintrag: " + r.FullName);
                _byFullName.Add(r.FullName, r);
                if (!_byName.ContainsKey(r.Name)) _byName.Add(r.Name, r);

                foreach (var raw in r.AssetPaths)
                {
                    var path = AssetKey.NormalizePath(raw);
                    var entry = new AssetEntry(r, path);
                    if (_byPath.ContainsKey(path)) continue;
                    _byPath.Add(path, entry);
                    AssetCount++;

                    var logical = AssetKey.ToLogicalKey(path);
                    if (!_byLogical.TryGetValue(logical, out var first)) _byLogical.Add(logical, entry);
                    else
                    {
                        if (!_collisions.TryGetValue(logical, out var list))
                            _collisions[logical] = list = new List<AssetEntry> { first };
                        list.Add(entry);
                    }
                }
            }
        }

        public static BundleCatalog FromBytes(byte[] data)
        {
            var graph = NrbfReader.Read(data);
            if (!(graph.Root is NrbfClass root) || !root.Name.EndsWith(ManifestClassSuffix, StringComparison.Ordinal))
                throw new InvalidDataException("Dpr.bin enthält kein " + ManifestClassSuffix);

            var version = (int)root.Get("_version");
            if (version != SupportedVersion)
                throw new InvalidDataException("Nicht unterstützte Katalogversion " + version + " (erwartet " + SupportedVersion + ")");

            var project = (string)graph.Resolve(root.Get("_projectName")) ?? "";
            var recArray = (object[])graph.Resolve(root.Get("_records")) ?? Array.Empty<object>();
            var records = new List<BundleRecord>(recArray.Length);
            foreach (var item in recArray)
                records.Add(ReadRecord(graph, (NrbfClass)graph.Resolve(item)));

            var variants = new List<string>();
            if (graph.Resolve(root.Get("_assetBundleNamesWithVariant")) is object[] va)
                foreach (var v in va) variants.Add((string)graph.Resolve(v));

            return new BundleCatalog(records, version, project, variants, true);
        }

        public static BundleCatalog FromFile(string path) => FromBytes(File.ReadAllBytes(path));

        static string[] ReadStrings(NrbfGraph g, object value)
        {
            if (!(g.Resolve(value) is object[] arr)) return Array.Empty<string>();
            var res = new string[arr.Length];
            for (var i = 0; i < arr.Length; i++) res[i] = (string)g.Resolve(arr[i]);
            return res;
        }

        static BundleRecord ReadRecord(NrbfGraph g, NrbfClass c)
        {
            var hash = (NrbfClass)g.Resolve(c.Get("hash"));
            return new BundleRecord
            {
                Project = (string)g.Resolve(c.Get("projectName")) ?? "",
                Name = (string)g.Resolve(c.Get("assetBundleName")),
                Hash = new BundleHash((uint)hash.Get("u0"), (uint)hash.Get("u1"), (uint)hash.Get("u2"), (uint)hash.Get("u3")),
                LastWriteTimeRaw = (long)c.Get("lastWriteTime"),
                IsStreamedScene = (bool)c.Get("isStreamingSceneAssetBundle"),
                Dependencies = ReadStrings(g, c.Get("allDependencies")),
                AssetPaths = ReadStrings(g, c.Get("assetPaths")),
                Size = (long)c.Get("size"),
            };
        }

        // Ersatz ohne Dpr.bin: jede Datei unter root mit UnityFS-Kopf ist ein Bundle,
        // Projekt = erstes Pfadsegment, Name = Rest. Abhängigkeiten/Assets bleiben leer.
        public static BundleCatalog FromDirectory(string root)
        {
            if (!Directory.Exists(root)) throw new DirectoryNotFoundException(root);
            var records = new List<BundleRecord>();
            var magic = new byte[7];
            foreach (var file in Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories))
            {
                var fi = new FileInfo(file);
                if (fi.Length < magic.Length) continue;
                using (var fs = fi.OpenRead())
                    if (fs.Read(magic, 0, magic.Length) != magic.Length) continue;
                if (magic[0] != 'U' || magic[1] != 'n' || magic[2] != 'i' || magic[3] != 't' ||
                    magic[4] != 'y' || magic[5] != 'F' || magic[6] != 'S') continue;

                var rel = file.Substring(root.Length).TrimStart('/', '\\').Replace('\\', '/');
                var slash = rel.IndexOf('/');
                if (slash <= 0) continue;
                records.Add(new BundleRecord { Project = rel.Substring(0, slash), Name = rel.Substring(slash + 1), Size = fi.Length });
            }
            records.Sort((a, b) => string.CompareOrdinal(a.FullName, b.FullName));
            return new BundleCatalog(records, SupportedVersion, "", null, false);
        }

        // Akzeptiert "Projekt/Name" (exakter Dateipfad im Katalog) oder den reinen Bundle-Namen.
        public bool TryGetBundle(string name, out BundleRecord record)
        {
            record = null;
            if (string.IsNullOrEmpty(name)) return false;
            var n = name.Replace('\\', '/');
            return _byFullName.TryGetValue(n, out record) || _byName.TryGetValue(n, out record);
        }

        public BundleRecord GetBundle(string name)
        {
            if (!TryGetBundle(name, out var r)) throw new KeyNotFoundException("Bundle nicht im Katalog: " + name);
            return r;
        }

        // Transitive Abhängigkeiten (ohne das Bundle selbst), in stabiler Reihenfolge.
        public List<BundleRecord> GetDependencyClosure(BundleRecord record)
        {
            var result = new List<BundleRecord>();
            var seen = new HashSet<BundleRecord> { record };
            var stack = new Stack<BundleRecord>();
            stack.Push(record);
            while (stack.Count > 0)
            {
                var cur = stack.Pop();
                foreach (var depName in cur.Dependencies)
                {
                    if (!TryGetBundle(depName, out var dep))
                        throw new InvalidDataException("Abhängigkeit " + depName + " von " + cur.FullName + " fehlt im Katalog");
                    if (seen.Add(dep)) { result.Add(dep); stack.Push(dep); }
                }
            }
            return result;
        }

        // Abhängigkeiten, die keinen Katalogeintrag haben (sollte 0 sein).
        public int CountMissingDependencies()
        {
            var missing = 0;
            foreach (var r in _records)
                foreach (var d in r.Dependencies)
                    if (!TryGetBundle(d, out _)) missing++;
            return missing;
        }

        // Logischer Name oder Asset-Pfad -> Bundle + Asset-Pfad. false bei unbekannt oder mehrdeutig
        // (gleicher Name mit verschiedenen Endungen, z. B. .asset/.xlsx); dann mit Endung anfragen.
        public bool TryResolveAsset(string key, out AssetEntry entry)
        {
            entry = default;
            if (string.IsNullOrEmpty(key)) return false;
            var n = AssetKey.NormalizePath(key);
            if (_byPath.TryGetValue(n, out entry)) return true;
            if (_byPath.TryGetValue("assets/" + n, out entry)) return true;

            var bare = AssetKey.StripAssetsPrefix(n);
            if (_collisions.ContainsKey(bare) || _collisions.ContainsKey(AssetKey.StripExtension(bare))) return false;
            if (_byLogical.TryGetValue(bare, out entry)) return true;
            return _byLogical.TryGetValue(AssetKey.StripExtension(bare), out entry);
        }

        public IReadOnlyList<AssetEntry> GetAssetCandidates(string key)
        {
            var n = AssetKey.StripAssetsPrefix(AssetKey.NormalizePath(key));
            if (_collisions.TryGetValue(n, out var list)) return list;
            if (_byLogical.TryGetValue(n, out var e)) return new[] { e };
            return Array.Empty<AssetEntry>();
        }
    }
}
