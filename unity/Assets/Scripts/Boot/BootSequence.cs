using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using Xnu.Core;

namespace Xnu.Boot
{
    public enum BootStatus { Ok, Warn, Fail }

    public sealed class BootStep
    {
        public string Name;
        public BootStatus Status;
        public string Message;
        public override string ToString() => "[" + Status + "] " + Name + ": " + Message;
    }

    public sealed class BootReport
    {
        public readonly List<BootStep> Steps = new List<BootStep>();
        public BundleCatalog Catalog;
        public BundleProvider Provider;
        public bool Success { get; internal set; }
    }

    // Boot-Schritte ohne Unity-Abhängigkeit außer GameDataPaths: Pfade prüfen, Katalog lesen,
    // Konsistenz prüfen, Provider anlegen. Jeder Schritt wird über onStep protokolliert.
    public static class BootSequence
    {
        public static BootReport Run(string assetAssistantDir, IBundleSource source, Action<BootStep> onStep = null)
        {
            var report = new BootReport();
            void Step(string name, BootStatus status, string msg)
            {
                var s = new BootStep { Name = name, Status = status, Message = msg };
                report.Steps.Add(s);
                onStep?.Invoke(s);
            }

            Step("GameData-Root", Directory.Exists(GameDataPaths.Root) ? BootStatus.Ok : BootStatus.Fail,
                GameDataPaths.Root + " (Quelle: " +
                (string.IsNullOrEmpty(Environment.GetEnvironmentVariable(GameDataPaths.EnvVar)) ? "persistentDataPath" : GameDataPaths.EnvVar) + ")");

            if (!Directory.Exists(assetAssistantDir))
            {
                Step("AssetAssistant", BootStatus.Fail, "Ordner fehlt: " + assetAssistantDir);
                return report;
            }
            Step("AssetAssistant", BootStatus.Ok, assetAssistantDir);

            var sw = Stopwatch.StartNew();
            var catalogPath = Path.Combine(assetAssistantDir, BundleCatalog.CatalogFileName);
            if (File.Exists(catalogPath))
            {
                try
                {
                    report.Catalog = BundleCatalog.FromFile(catalogPath);
                    Step("Katalog", BootStatus.Ok, BundleCatalog.CatalogFileName + ": " + report.Catalog.Records.Count + " Bundles, " +
                        report.Catalog.AssetCount + " Assets, Version " + report.Catalog.Version + " (" + sw.ElapsedMilliseconds + " ms)");
                }
                catch (Exception e)
                {
                    Step("Katalog", BootStatus.Warn, BundleCatalog.CatalogFileName + " nicht lesbar (" + e.Message + "), Verzeichnis-Scan als Ersatz");
                }
            }
            else Step("Katalog", BootStatus.Warn, BundleCatalog.CatalogFileName + " fehlt, Verzeichnis-Scan als Ersatz");

            if (report.Catalog == null)
            {
                try
                {
                    sw.Restart();
                    report.Catalog = BundleCatalog.FromDirectory(assetAssistantDir);
                    Step("Verzeichnis-Scan", BootStatus.Ok, report.Catalog.Records.Count + " Bundles (" + sw.ElapsedMilliseconds + " ms)");
                }
                catch (Exception e)
                {
                    Step("Verzeichnis-Scan", BootStatus.Fail, e.Message);
                    return report;
                }
            }

            if (report.Catalog.Records.Count == 0)
            {
                Step("Katalog-Inhalt", BootStatus.Fail, "keine Bundles gefunden");
                return report;
            }

            var provider = new BundleProvider(report.Catalog, assetAssistantDir, source);
            var missingFiles = 0;
            foreach (var r in report.Catalog.Records)
                if (!File.Exists(provider.GetBundlePath(r))) missingFiles++;
            var missingDeps = report.Catalog.CountMissingDependencies();
            Step("Konsistenz", missingFiles == 0 && missingDeps == 0 ? BootStatus.Ok : BootStatus.Warn,
                missingFiles + " Bundle-Dateien fehlen, " + missingDeps + " Abhängigkeiten ohne Eintrag, " +
                report.Catalog.AmbiguousLogicalKeyCount + " mehrdeutige Asset-Namen");

            report.Provider = provider;
            report.Success = true;
            Step("Provider", BootStatus.Ok, "bereit");
            return report;
        }
    }
}
