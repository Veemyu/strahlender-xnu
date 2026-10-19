using System;
using System.Collections.Generic;

namespace Xnu.Game
{
    // Ereignis des Hosts für die Darstellung (Kamera, Warten, Effekte, Menüs): nur Daten, mit Dauer in Frames (30 Hz wie TIME_WAIT).
    public sealed class HostEvent
    {
        public int Id;
        public string Name;
        public int[] Args;
        public string[] Strings;
        public int DurationFrames;     // 0 = sofort fertig, sonst mindestens so viele Frames
        public int Tick;
    }

    // Laufzeitzustand der Spielwelt, den das Original außerhalb des Save-Puffers hält (oder dessen Ort im Save noch nicht belegt ist).
    // Alles hier ist Sitzungszustand; die Prüfstufe der zugehörigen Befehle steht in HostCommandsMore.cs.
    public sealed class WorldState
    {
        public const int ClockWork = 0x1A2;          // CHK_WEEK/GET_NOW_HOUR lesen diesen Arbeitswert [P]
        public const int PoketchFlag = 0xCB;         // GET_POKETCH setzt Flag 0xCB [P]
        public const int ZukanFlag = 0x69;           // SYS_FLAG_ZUKAN_SET [P]
        public const int ShoesFlag = 0x4A;           // SYS_FLAG_SHOES_SET [P]
        public const int ReturnScriptWork = 0xCD;    // RETURN_SCRIPT_WK_SET [P]

        // Uhr: Aufrufer (Feldschicht) setzt sie; Standard ist die Systemzeit.
        public Func<DateTime> Clock = () => DateTime.Now;

        // Fortbewegung
        public bool Bicycle;
        public bool Swimming;
        public int BicycleColor;
        public bool FlashActive;
        public bool MistCleared;
        public bool Darkness;
        public bool HeightValid;                     // PLAYER_HEGIHT_VALID

        // Poketch (verfügbare Apps)
        public readonly HashSet<int> PoketchApps = new HashSet<int>();

        // Sichttrainer: Liste der Trainer-IDs, die den Spieler gerade sehen (setzt die Feldschicht; EYE_TRAINER_*, TRAINER_ID_GET)
        public readonly List<int> EyeTrainerIds = new List<int>();
        public readonly List<int> EyeTrainerTypes = new List<int>();

        // Objekte: Sichtbarkeit und Bewegungscode je Name
        public readonly Dictionary<string, bool> ObjectVisible = new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);
        public readonly Dictionary<string, int> ObjectMoveCode = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        // letzte per Skript gesetzte Gitterposition je Objekt (SXY_POS_CHANGE usw.); unbekannt, solange das Skript sie nicht gesetzt hat
        public readonly Dictionary<string, int[]> ObjectGrid = new Dictionary<string, int[]>(StringComparer.OrdinalIgnoreCase);
        public readonly Dictionary<int, int[]> ExitPositions = new Dictionary<int, int[]>();   // SXY_EXIT_POS_CHANGE: Ausgang (Warp-Index) -> x, z
        public string PartnerObject = "";            // PAIR_OBJID_SET

        // Warp
        public int TeleportZone = -1;
        public int TeleportLocator;
        public string DoorZoneFrom = "";
        public string DoorZoneTo = "";

        // Zähler und Sammlungen
        public readonly Dictionary<int, int> Records = new Dictionary<int, int>();        // RecordWork
        public readonly Dictionary<int, int> BallSeals = new Dictionary<int, int>();      // BallDecoWork (CB_ITEM_*)
        public readonly Dictionary<int, int> UndergroundItems = new Dictionary<int, int>();
        public int BattlePoints;

        // Pokécenter-Animation: Bälle der Teammitglieder (POKECEN_PUT_BALL); geheilt wird mit PC_KAIFUKU
        public readonly List<int> PokecenterBalls = new List<int>();
        public int HealEffectCalls;
        public int LastHealZone = -1;                // Zone des zuletzt benutzten Pokécenters (PC_KAIFUKU) = Rücksetzzone nach Niederlage [A]

        // Ereigniskamera (EVENT_CAMERA_INDEX/END_WAIT): Index der Kamerafahrt (EventCameraTable) und ob sie noch läuft
        public int CameraIndex = -1;
        public bool CameraBusy;
        public int SaveRequests;                     // AUTO_SAVE/REPORT_SAVE: Anfragen an die Oberfläche

        // Namen und Arten, die das Original anderswo hält
        public string MonumentName = "";
        public int RivalPokeNo;                      // 0 = aus der Startwahl abgeleitet
        public int SupportPokeNo;

        // Kassette (PM_VERSION_GET, LDVAL_VERSION): [A] 10 = Strahlender Diamant (Wert 10 wählt in LDVAL_VERSION das erste Argument [P])
        public int CassetteVersion = 10;

        // TV-Themen (TvWork.GetRecordTvIntData/GetTvBranchData/Texte): leer, bis eine Sendung entsteht [A]
        public readonly Dictionary<int, int> TvInts = new Dictionary<int, int>();
        public readonly Dictionary<int, int> TvBranch = new Dictionary<int, int>();
        public readonly Dictionary<int, string> TvStrings = new Dictionary<int, string>();

        public int RecordGet(int id) => Records.TryGetValue(id, out var v) ? v : 0;

        public void RecordAdd(int id, int delta)
        {
            Records.TryGetValue(id, out var v);
            Records[id] = Math.Max(0, v + delta);
        }
    }
}
