using System;
using System.Collections.Generic;

namespace Xnu.Battle.Flow
{
    public enum BattleCompetitor
    {
        Wild = 0,
        Trainer = 1,
    }

    // BtlResult des Originals (Einzelkampf).
    public enum BattleResult
    {
        Lose = 0,
        Win = 1,
        Draw = 2,
        Run = 3,
        RunEnemy = 4,
        Capture = 5,
        None = -1,
    }

    public enum BattlePhase
    {
        NotStarted,
        AwaitCommands,
        AwaitReplacement,
        Finished,
    }

    public enum CommandKind
    {
        Fight,
        Item,
        Change,
        Run,
    }

    // Befehlsphase als Daten: was die Seite in dieser Runde tun will.
    public struct BattleCommand
    {
        public CommandKind Kind;
        public int MoveSlot;     // Fight: 0..3
        public int ItemId;       // Item: Item-Nr.
        public int ItemTarget;   // Item: Party-Index des Ziels (-1 = aktives Pokemon)
        public int PartyIndex;   // Change: Party-Index des neuen Pokemon

        public static BattleCommand Fight(int slot) => new BattleCommand { Kind = CommandKind.Fight, MoveSlot = slot };

        public static BattleCommand Item(int itemId, int target = -1) => new BattleCommand { Kind = CommandKind.Item, ItemId = itemId, ItemTarget = target };

        public static BattleCommand Change(int partyIndex) => new BattleCommand { Kind = CommandKind.Change, PartyIndex = partyIndex };

        public static BattleCommand Run() => new BattleCommand { Kind = CommandKind.Run };
    }

    public enum LogKind
    {
        BattleStart,
        SendOut,            // Poke = ID, Id = Art, Value = Stufe, Value2 = KP
        TurnStart,          // Value = Rundennummer
        ActionOrder,        // Poke = zuerst, Target = danach, Value/Value2 = Sortierschluessel
        MoveUsed,           // Poke, Id = Attacke
        MoveFailed,         // Poke, Id = Attacke, Value = Fehlschlag-Ursache (FailCause)
        MoveMissed,         // Poke = Angreifer, Target, Id = Attacke
        NoEffect,           // Poke = Ziel, Id = Attacke
        Critical,           // Poke = Ziel
        Effectiveness,      // Poke = Ziel, Value = Typenwirkung (Affinitaets-ID)
        Damage,             // Poke = Ziel, Target = Angreifer, Value = Schaden, Value2 = Rest-KP
        HitCount,           // Poke = Angreifer, Value = Zahl der Treffer
        Recover,            // Poke, Value = geheilte KP, Value2 = KP danach
        Drain,              // Poke = Heilender, Target = Opfer, Value = KP
        Recoil,             // Poke, Value = Schaden, Value2 = Rest-KP
        StatChange,         // Poke, Id = Wert (1 Angriff .. 7 Fluchtwert), Value = Aenderung, Value2 = neue Stufe (0..12)
        StatChangeBlocked,  // Poke, Id, Value = Richtung (+1/-1): Grenze erreicht
        SickAdded,          // Poke, Id = Zustand
        SickFailed,         // Poke, Id = Zustand
        SickCured,          // Poke, Id = Zustand
        SickDamage,         // Poke, Id = Zustand, Value = Schaden, Value2 = Rest-KP
        ConfusionDamage,    // Poke, Value = Schaden, Value2 = Rest-KP
        WeatherStart,       // Id = Wetter, Value = Runden (255 = dauerhaft)
        WeatherEnd,         // Id = Wetter
        WeatherDamage,      // Poke, Id = Wetter, Value = Schaden, Value2 = Rest-KP
        Faint,              // Poke
        ExpGained,          // Poke, Value = Erfahrung, Value2 = 1 bei Bonus
        LevelUp,            // Poke, Value = neue Stufe
        EvGained,           // Poke, Id = Wert (0 KP, 1 Angriff, 2 Abwehr, 3 Sp.-Angriff, 4 Sp.-Abwehr, 5 Initiative), Value = Punkte
        Switch,             // Poke = ausgewechselt, Target = neu
        ItemUsed,           // Poke = Ziel, Id = Item, Value = Wirkung
        RunAttempt,         // Poke
        RunSuccess,         // Poke
        RunFailed,          // Poke
        TurnEnd,            // Value = Rundennummer
        BattleEnd,          // Value = BattleResult
        PrizeMoney,         // Value = Preisgeld (Sieg gegen Trainer)
        MoneyLost,          // Value = Abzug bei Niederlage
        AbilityActivated,   // Poke, Id = Faehigkeit
        ItemActivated,      // Poke, Id = Item (Value = Wirkung, z. B. geheilte KP)
        ItemConsumed,       // Poke, Id = Item
        SideEffectStart,    // Poke = Anwender, Id = Seiteneffekt (SideEffect), Value = Seite, Value2 = Dauer
        SideEffectEnd,      // Id = Seiteneffekt, Value = Seite
        HazardDamage,       // Poke, Id = Seiteneffekt, Value = Schaden, Value2 = Rest-KP
        Protected,          // Poke = Ziel, Target = Angreifer, Id = Attacke
        Forced,             // Poke = Ziel: Wechsel erzwungen (Id = Attacke); bei Wildkampf-Gegner endet der Kampf
        FieldEffectStart,   // Id = Feldeffekt (FieldEffect), Value = Runden
        FieldEffectEnd,     // Id = Feldeffekt
        Fainted,            // reserviert
    }

    // Seiteneffekte (Handler.Side-Nummern des Originals).
    public static class SideEffect
    {
        public const int Reflect = 0;
        public const int LightScreen = 1;
        public const int Safeguard = 2;
        public const int Mist = 3;
        public const int Tailwind = 4;
        public const int Spikes = 6;
        public const int ToxicSpikes = 7;
        public const int StealthRock = 8;
        public const int StickyWeb = 14;
        public const int AuroraVeil = 17;
    }

    public static class FieldEffectNo
    {
        public const int TrickRoom = 1;
        public const int Gravity = 2;
    }

    // Ursachen eines Attacken-Fehlschlags in der ersten Pruefung (CheckFail_1st des Originals).
    public static class FailCause
    {
        public const int NoPp = 1;
        public const int Sleep = 2;
        public const int Paralysis = 3;
        public const int Freeze = 4;
        public const int Confusion = 5;
        public const int Flinch = 6;
        public const int Infatuation = 8;
        public const int Missed = 100;       // nicht im Original: Genauigkeit (zweite Pruefung)
        public const int NotImplemented = 101;   // Attacke braucht Handler/Sections, die noch fehlen (Seiteneffekte, Sonderattacken)
        public const int NothingHappened = 102;  // z. B. Heilung bei vollen KP, gleiches Wetter
        public const int NoTarget = 103;         // Attacke braucht ein Ziel/Partner, den es im Einzelkampf nicht gibt
        public const int Disabled = 9;           // Aussetzer (Zustand 13)
        public const int Taunted = 10;           // Verhoehner (Zustand 11): Status-Attacke gesperrt
        public const int Unsupported = NotImplemented;
    }

    // Strukturiertes Ereignis des Ablaufprotokolls (statt Text).
    public sealed class LogEvent
    {
        public LogKind Kind;
        public int Turn;
        public int Poke = -1;
        public int Target = -1;
        public int Id;
        public int Value;
        public int Value2;

        public override string ToString() => $"{Kind}(t{Turn} poke={Poke} target={Target} id={Id} v={Value} v2={Value2})";
    }
}
