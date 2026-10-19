using Xnu.Battle.Flow;

namespace Xnu.Game
{
    // Zustände der Spielschleife (docs/spielkern-1.md, Abschnitt 3).
    public enum GameState
    {
        Field,
        Event,
        Battle,
        Menu,
    }

    // Eingabe als Daten: ein Tick bekommt genau eine solche Momentaufnahme (Tasten gelten als "gerade gedrückt").
    public struct GameInput
    {
        public bool Confirm;
        public bool Cancel;
        public bool Menu;
        public bool Up, Down, Left, Right;
        // Kampf: Befehl des Spielers (nur wirksam in AwaitCommands) und Ersatz nach Besiegt (Party-Index, -1 = keiner).
        public BattleCommand? Battle;
        public int Replacement;
        // Startwahl (FIRST_POKE_SELECT_PROC): Index 0..2 der drei Starter, -1 = keine Wahl.
        public int StarterChoice;
        // Texteingabe (Namenseingabe, NAMEIN_*): null = nichts eingegeben, "" = leer bestätigt.
        public string Text;

        public static GameInput None => new GameInput { Replacement = -1, StarterChoice = -1 };
        public static GameInput Press() => new GameInput { Confirm = true, Replacement = -1, StarterChoice = -1 };
        public static GameInput Fight(int slot) => new GameInput { Battle = BattleCommand.Fight(slot), Replacement = -1, StarterChoice = -1 };
        public static GameInput Starter(int index) => new GameInput { Confirm = true, Replacement = -1, StarterChoice = index };
        public static GameInput Replace(int partyIndex) => new GameInput { Replacement = partyIndex, StarterChoice = -1 };
    }

    public enum FieldSignalKind
    {
        None,
        Talk,          // Spieler spricht ein Objekt an: Label = PlaceData.TalkLabel
        Contact,       // Kontaktfeld (StopData.ContactLabel) oder Sichtfeld eines Trainers: Label = Skript-Label
        Warp,          // Spieler betritt eine Warpzelle: A = Zielzone, B = Locator
        Step,          // Spieler betritt eine Zelle mit Begegnungsattribut: A = Zone, Kind = EncounterKind
    }

    // Meldung der Feldschicht an den Spielkern (statt direkter Aufrufe): nur Daten.
    public struct FieldSignal
    {
        public FieldSignalKind Kind;
        public string Label;
        public int A;
        public int B;
        public EncounterKind Encounter;

        public static FieldSignal Talk(string label) => new FieldSignal { Kind = FieldSignalKind.Talk, Label = label };
        public static FieldSignal Contact(string label) => new FieldSignal { Kind = FieldSignalKind.Contact, Label = label };
        public static FieldSignal Warp(int zone, int locator) => new FieldSignal { Kind = FieldSignalKind.Warp, A = zone, B = locator };
        public static FieldSignal Step(int zone, EncounterKind kind) => new FieldSignal { Kind = FieldSignalKind.Step, A = zone, Encounter = kind };
    }

    public enum EncounterKind
    {
        Grass,
        Water,
        OldRod,
        GoodRod,
        SuperRod,
    }

    public enum BattleRequestKind
    {
        Trainer,
        Wild,
    }

    // Wunsch nach einem Kampf, vom Ereignis-Host oder der Begegnungslogik gestellt.
    public sealed class BattleRequest
    {
        public BattleRequestKind Kind;
        public int TrainerId;
        public int TrainerId2;      // Doppelkampf-Partner (noch nicht umgesetzt)
        public int MonsNo;
        public int FormNo;
        public int Level;
        public bool Tutorial;       // FIRST_BTL_SET
        public bool FromEvent;      // Ereignis wartet auf das Kampfende

        public static BattleRequest Trainer(int id, int id2 = 0) => new BattleRequest { Kind = BattleRequestKind.Trainer, TrainerId = id, TrainerId2 = id2, FromEvent = true };
        public static BattleRequest Wild(int monsNo, int level, int form = 0) => new BattleRequest { Kind = BattleRequestKind.Wild, MonsNo = monsNo, Level = level, FormNo = form };
    }
}
