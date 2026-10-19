using System;
using System.Collections.Generic;
using System.IO;
using Xnu.Field;
using Xnu.Save;

namespace Xnu.Game.Unity
{
    // Ort des Spielers im Spielstand. Maßgeblich ist PLAYER_DATA (Rasterzelle gx, gy als Int32 bei 0x79BF4/0x79BF8, danach die Höhe als Float)
    // zusammen mit der Zone bei 0x5634; TownMapLocation (PLAYER_SAVE_DATA, Zone/x/z/Richtung) ist nur ein Rückfall. Belege: Der Stadt-Spielstand
    // (zoneID 24, PLAYER_DATA (57, 729), Höhe 1,0) hat eine veraltete TownMapLocation (Zone 416, 789/355); beim alten Stand (zoneID 167) steht in
    // PLAYER_DATA (852, 599) mit Höhe 6,0, was zur Höhe 6,00 im Bild der Zone 167 an Zeile 599 passt, TownMapLocation hat (842, 597).
    // [A: Bedeutung der PLAYER_DATA-Felder aus den Werten erschlossen, eine Richtung ist dort nicht gefunden: Richtung aus TownMapLocation, nur wenn deren Zone passt.]
    public readonly struct SavedPosition
    {
        public readonly int Zone;
        public readonly int GridX, GridY;
        public readonly int Direction;
        public readonly bool Valid;
        public readonly bool FromPlayerData;

        public SavedPosition(int zone, int gx, int gy, int dir, bool valid, bool fromPlayerData = false)
        {
            Zone = zone; GridX = gx; GridY = gy; Direction = dir; Valid = valid; FromPlayerData = fromPlayerData;
        }

        // Feldlage im Puffer: player_save_data bei 0x8FB04, TownMapLocation bei +0x54 (zone int, x/y/z float, dir int).
        public const int PlayerSaveDataOffset = 0x8FB04;
        public const int LocationOffset = PlayerSaveDataOffset + 0x54;
        public const int ZoneIdOffset = 0x5634;
        public const int PlayerDataGridXOffset = 0x79BF4;
        public const int PlayerDataGridYOffset = 0x79BF8;
        public const int PlayerDataHeightOffset = 0x79BFC;
        public const int MaxGrid = 4096;

        public static SavedPosition Read(SaveData save)
        {
            var b = save.Buffer;
            var zone = BitConverter.ToInt32(b, ZoneIdOffset);
            var locZone = BitConverter.ToInt32(b, LocationOffset);
            var x = BitConverter.ToSingle(b, LocationOffset + 4);
            var z = BitConverter.ToSingle(b, LocationOffset + 12);
            var dir = BitConverter.ToInt32(b, LocationOffset + 16);
            var locOk = !float.IsNaN(x) && !float.IsNaN(z) && Math.Abs(x) < 4000f && Math.Abs(z) < 4000f && (x != 0f || z != 0f);

            if (b.Length > PlayerDataHeightOffset)
            {
                var gx = BitConverter.ToInt32(b, PlayerDataGridXOffset);
                var gy = BitConverter.ToInt32(b, PlayerDataGridYOffset);
                if (zone > 0 && gx > 0 && gy > 0 && gx < MaxGrid && gy < MaxGrid)
                    return new SavedPosition(zone, gx, gy, locOk && locZone == zone ? dir : 0, true, true);
            }
            return new SavedPosition(zone, FieldCoords.GridX(x), FieldCoords.GridY(z), dir, locOk && locZone == zone);
        }

        // Schreibt Zone und Ort (Welt-Koordinaten wie im Original: x = -gx, z = gy) in beide Ablagen, damit Lesen die geschriebene Zelle zurückgibt;
        // die Höhe bleibt.
        public static void Write(SaveData save, int zone, int gx, int gy, MoveDir facing)
        {
            var b = save.Buffer;
            Put(b, ZoneIdOffset, zone);
            Put(b, LocationOffset, zone);
            Put(b, LocationOffset + 4, FieldCoords.WorldX(gx));
            Put(b, LocationOffset + 12, FieldCoords.WorldZ(gy));
            Put(b, LocationOffset + 16, (int)facing);
            Put(b, PlayerDataGridXOffset, gx);
            Put(b, PlayerDataGridYOffset, gy);
        }

        static void Put(byte[] b, int offset, int v) => Buffer.BlockCopy(BitConverter.GetBytes(v), 0, b, offset, 4);
        static void Put(byte[] b, int offset, float v) => Buffer.BlockCopy(BitConverter.GetBytes(v), 0, b, offset, 4);

        public static MoveDir ToFacing(int direction) => direction >= 1 && direction <= 4 ? (MoveDir)direction : MoveDir.Down;
    }

    // Spielstand-Ablage des Players: eigener Slot im Save-Ordner der App (SaveStore), Backup vor jedem Überschreiben.
    // Der echte Spielstand (Ryujinx-Ordner o. Ä.) wird nur gelesen (Import beim ersten „Weiter“), nie beschrieben.
    // Ein Slot gilt nur, wenn SaveData.bin oder Backup.bin dort liegt und gültig ist (Größe, Version, Hash); ein leerer Ordner
    // oder eine abgeschnittene Datei (halb übertragen) zählt nicht, sondern erscheint mit Grund in Diagnose().
    public sealed class SaveSlotService
    {
        public const string SlotName = "main";
        // Unterordner im Ablageordner der App, in dem der Slot liegt (<Ablage>/Saves/<Slot>/SaveData.bin).
        public const string SlotsFolder = "Saves";

        readonly string[] _sources;
        readonly string[] _dropIns;
        bool _stateKnown;
        bool _slotUsable;
        string _slotProblem = "";
        string _usableSource;
        string _usableDrop;
        string _pendingDrop;
        string _pendingDropHash;
        readonly List<string> _sourceProblems = new List<string>();

        public SaveStore Store { get; }
        // Erste Importquelle, die gültig ist; sonst die erste angegebene (für Meldungen).
        public string ImportSource { get { EnsureState(); return _usableSource ?? (_sources.Length > 0 ? _sources[0] : ""); } }
        public string Note { get; private set; } = "";
        public int Writes { get; private set; }
        public string LastBackup { get; private set; } = "";
        // Warum es nichts zum Weiterspielen gibt (leer, wenn CanContinue).
        public string Problem { get { EnsureState(); return CanContinue ? "" : (_slotProblem + (_sourceProblems.Count > 0 ? "; " + string.Join("; ", _sourceProblems) : "")).Trim(' ', ';'); } }
        // Datei, mit der „Weiter“ den Slot beim nächsten Laden ersetzt (neue lose SaveData.bin), sonst leer.
        public string PendingDropIn { get { EnsureState(); return _pendingDrop ?? ""; } }

        // importSource: Quelle für den ersten Import, nur wenn es keinen gültigen Slot gibt (z. B. Ryujinx-Ordner).
        // dropIns: lose Dateien, die der Nutzer ablegt (siehe DropInSources). Eine gültige Datei, deren SHA-256 vom zuletzt importierten Stand abweicht,
        // ersetzt den Slot beim nächsten Laden (Backup vorher); danach merkt sich ImportedMarkerPath den Hash, bis die Datei wechselt.
        public SaveSlotService(string root, string importSource, params string[] dropIns)
        {
            Store = new SaveStore(root);
            _sources = string.IsNullOrEmpty(importSource) ? new string[0] : new[] { importSource };
            var list = new List<string>();
            if (dropIns != null) foreach (var s in dropIns) if (!string.IsNullOrEmpty(s) && !list.Contains(s)) list.Add(s);
            _dropIns = list.ToArray();
        }

        public string ImportedMarkerPath => Path.Combine(Store.Root, "ImportedDropIn.sha256");

        // Ablageordner der App: -xnuSaveRoot, sonst persistentDataPath (iPadOS: Documents, sichtbar in der Dateien-App und im Finder → <Documents>/Saves/main).
        // Ältere macOS-Läufe legten den Slot unter <persistentDataPath>/Saves/Saves/main an; ist dieser Ordner da, bleibt er maßgebend.
        public static string ResolveRoot(string explicitRoot, string persistentDataPath)
        {
            if (!string.IsNullOrEmpty(explicitRoot)) return explicitRoot;
            if (string.IsNullOrEmpty(persistentDataPath)) throw new ArgumentException("persistentDataPath fehlt", nameof(persistentDataPath));
            var legacy = Path.Combine(persistentDataPath, SlotsFolder);
            return Directory.Exists(Path.Combine(legacy, SlotsFolder)) ? legacy : persistentDataPath;
        }

        // Stellen, an die man eine Datei ohne Ordnerstruktur legt (Dateien-App, Finder-Dateifreigabe, scripts/ios_push_save.sh): Documents/SaveData.bin, Documents/Import/SaveData.bin.
        // Wichtig: devicectl legt fehlende Ordner mit Besitzer root an; die App darf dort nichts anlegen. Documents selbst gehört der App, daher kein Unterordner nötig.
        public static string[] DropInSources(string persistentDataPath)
        {
            if (string.IsNullOrEmpty(persistentDataPath)) return new string[0];
            return new[] { Path.Combine(persistentDataPath, SaveFileIO.MainFileName), Path.Combine(persistentDataPath, "Import", SaveFileIO.MainFileName) };
        }

        public string SlotPath => Store.SlotDirectory(SlotName);

        // Zustand neu lesen (nach Dateiänderungen von außen).
        public void Refresh() => _stateKnown = false;

        void EnsureState()
        {
            if (_stateKnown) return;
            _stateKnown = true;
            _slotUsable = false;
            _slotProblem = "";
            _usableSource = null;
            _usableDrop = null;
            _pendingDrop = null;
            _pendingDropHash = null;
            _sourceProblems.Clear();
            var dir = SlotPath;
            if (!Directory.Exists(dir)) _slotProblem = "Slot-Ordner fehlt: " + dir;
            else
            {
                var ins = Store.Inspect(SlotName);
                _slotUsable = ins.HasUsableSave;
                if (!_slotUsable) _slotProblem = "Slot ohne gültige Datei: " + Describe(ins);
                else if (!DirectoryWritable(dir)) _sourceProblems.Add("Slot-Ordner nicht beschreibbar (Besitzer root, z. B. von devicectl angelegt): Speichern schlägt fehl; Ordner löschen oder App neu installieren und die Datei als Documents/SaveData.bin ablegen");
            }
            var marker = ReadMarker();
            foreach (var s in _sources) Probe(s, false, marker);
            foreach (var s in _dropIns) Probe(s, true, marker);
        }

        void Probe(string s, bool dropIn, string marker)
        {
            if (!File.Exists(s) && !Directory.Exists(s)) { _sourceProblems.Add("Quelle fehlt: " + s); return; }
            try
            {
                var ins = SaveInspector.Inspect(s, Store.Root);
                if (!ins.HasUsableSave) { _sourceProblems.Add("Quelle ungültig: " + s + " (" + Describe(ins) + ")"); return; }
                if (!dropIn) { if (_usableSource == null) _usableSource = s; return; }
                if (_usableDrop == null) _usableDrop = s;
                if (_pendingDrop == null)
                {
                    var hash = FullHash(s);
                    if (hash != null && hash != marker) { _pendingDrop = s; _pendingDropHash = hash; }
                }
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException || e is InvalidDataException)
            {
                _sourceProblems.Add("Quelle nicht lesbar: " + s + " (" + e.GetType().Name + ")");
            }
        }

        string ReadMarker()
        {
            try { return File.Exists(ImportedMarkerPath) ? File.ReadAllText(ImportedMarkerPath).Trim() : ""; }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException) { return ""; }
        }

        static bool DirectoryWritable(string dir)
        {
            var probe = Path.Combine(dir, ".schreibtest-" + Guid.NewGuid().ToString("N").Substring(0, 8));
            try
            {
                File.WriteAllBytes(probe, new byte[1]);
                File.Delete(probe);
                return true;
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException) { return false; }
        }

        static string FullHash(string path)
        {
            try
            {
                using (var sha = System.Security.Cryptography.SHA256.Create())
                using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
                {
                    var h = sha.ComputeHash(fs);
                    var sb = new System.Text.StringBuilder();
                    foreach (var b in h) sb.Append(b.ToString("x2"));
                    return sb.ToString();
                }
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException) { return null; }
        }

        static string Describe(SaveInspection ins)
        {
            var parts = new List<string>();
            foreach (var f in ins.Files)
                parts.Add(f.Name + " " + f.Size + " Byte" + (f.IsValid ? " gültig" : f.Validation == null ? " unlesbar" : " ungültig: " + string.Join(", ", f.Validation.Problems)));
            foreach (var n in ins.Notes) parts.Add(n);
            return parts.Count == 0 ? "leer" : string.Join("; ", parts);
        }

        public bool HasSlot { get { EnsureState(); return _slotUsable; } }

        // Es gibt etwas zum Weiterspielen: gültiger eigener Slot, gültige Importquelle oder gültige abgelegte Datei.
        public bool CanContinue { get { EnsureState(); return _slotUsable || _usableSource != null || _usableDrop != null; } }

        // Mehrzeiliger Befund für das Log: Ablageordner, Slot, Quellen (Pfade, Größen, Gültigkeit, Kurzhash; nie Inhalte).
        public IReadOnlyList<string> Diagnose()
        {
            EnsureState();
            var lines = new List<string> { "Ablage " + Store.Root, "Slot " + SlotPath + (HasSlot ? " gültig" : " unbrauchbar") };
            if (!_slotUsable && _slotProblem.Length > 0) lines.Add("  " + _slotProblem);
            if (Directory.Exists(SlotPath))
                foreach (var f in Directory.GetFiles(SlotPath)) lines.Add("  Datei " + Path.GetFileName(f) + " " + new FileInfo(f).Length + " Byte " + ShortHash(f));
            foreach (var s in _sources) lines.Add("Quelle " + s + (s == _usableSource ? " gültig" : File.Exists(s) || Directory.Exists(s) ? " unbrauchbar" : " fehlt"));
            foreach (var s in _dropIns)
                lines.Add("Ablage-Datei " + s + (s == _pendingDrop ? " gültig, neu (ersetzt den Slot beim Laden)" : s == _usableDrop ? " gültig, bereits importiert" : File.Exists(s) ? " unbrauchbar" : " fehlt") + (File.Exists(s) ? " " + new FileInfo(s).Length + " Byte " + ShortHash(s) : ""));
            foreach (var p in _sourceProblems) lines.Add("  " + p);
            return lines;
        }

        static string ShortHash(string path)
        {
            var h = FullHash(path);
            return h == null ? "unlesbar" : "sha256:" + h.Substring(0, 12);
        }

        public SaveData Load()
        {
            EnsureState();
            var src = _pendingDrop ?? (_slotUsable ? null : _usableDrop ?? _usableSource);
            if (src != null)
            {
                var r = Store.Import(src, SlotName);
                var isDrop = Array.IndexOf(_dropIns, src) >= 0;
                Note = "Spielstand aus " + (isDrop ? "abgelegter Datei " + Path.GetFileName(src) : Path.GetFileName(Path.GetDirectoryName(src.TrimEnd('/', '\\')))) + " importiert (" + r.Bytes + " Byte, Quelle nur gelesen"
                       + (r.BackupPath != null ? ", vorheriger Slot gesichert" : "") + ")";
                if (isDrop)
                {
                    var hash = src == _pendingDrop ? _pendingDropHash : FullHash(src);
                    try { if (hash != null) File.WriteAllText(ImportedMarkerPath, hash); }
                    catch (Exception e) when (e is IOException || e is UnauthorizedAccessException) { Note += "; Merkdatei nicht schreibbar"; }
                }
            }
            else if (_slotUsable) Note = "Spielstand aus dem eigenen Slot";
            else throw new FileNotFoundException("Kein gültiger Spielstand: " + Problem);
            Refresh();
            return Store.Load(SlotName);
        }

        // Speichern: Hash neu, atomar schreiben, vorherigen Stand ins Backup-Verzeichnis des Slots.
        public SaveWriteResult Write(SaveData save)
        {
            var r = Store.Write(SlotName, save, true);
            Writes++;
            LastBackup = r.BackupPath ?? "";
            Refresh();
            return r;
        }
    }
}
