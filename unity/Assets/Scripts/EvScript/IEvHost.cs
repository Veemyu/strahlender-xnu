using System;
using System.Collections.Generic;
using Xnu.Data;

namespace Xnu.EvScript
{
    public sealed class EvScriptException : Exception
    {
        public EvScriptException(string message) : base(message) { }
    }

    // Anfrage für ein Textfenster (TALKMSG): Dateiname und Label der Message-Datei, Zusatzwerte aus Argument 2 und 3.
    public sealed class EvTalkRequest
    {
        public string Msbt = "";
        public string Label = "";
        public int Value;          // Argument 2 (Work oder Float), sonst 0; im Original Feld +0x290 der Fensterparameter
        public bool Flag;          // Argument 2 == 1 (TALKMSG)
    }

    // Ein Befehlsaufruf für den Host. Argumente werden ab 1 gezählt (0 ist die Befehlskennung).
    public sealed class EvCommandCall
    {
        internal EvInterpreter Owner;
        public int Id;
        public IReadOnlyList<EventArgument> Args = Array.Empty<EventArgument>();
        // Anzahl bisheriger Aufrufe dieses Befehls (0 beim ersten Aufruf). Der Host liefert true, wenn der Befehl fertig ist.
        public int Phase;
        public bool First => Phase == 0;
        public int ArgCount => Args.Count - 1;

        public int Type(int i) => Args[i].Type;
        public int Raw(int i) => Args[i].Data;
        public bool Has(int i) => i < Args.Count;

        // Wert wie im Original: Work -> aktueller Arbeitswert, Float -> abgeschnittene Ganzzahl, sonst 0.
        public int Int(int i) => Owner.ArgValue(Args, i);
        public float Float(int i) => Args[i].AsFloat();
        public string Str(int i) => Owner.ArgString(Args, i);
        public void SetWork(int i, int value) => Owner.Vars.SetWork(Args[i].Data, value);
        public void SetWorkIndex(int workIndex, int value) => Owner.Vars.SetWork(workIndex, value);
    }

    // Schnittstelle zur Spielwelt. Alle Methoden mit "...IsDone/TryGet..." werden einmal je Update abgefragt, bis sie true liefern.
    // Wartende Befehle verbrauchen dadurch genau wie im Original mindestens einen Frame.
    public interface IEvHost
    {
        // Textfenster
        void TalkBegin(EvTalkRequest request);
        bool TalkIsDone();
        void TalkClose(bool clear);

        // Auswahlfenster. YesNo: result 0 = erster Eintrag (Annahme: "Ja"), 1 = zweiter.
        void YesNoBegin(bool defaultYes);
        bool YesNoTryGetResult(out int index);
        // Eigenes Auswahlfenster; index = Position der gewählten Zeile (der Interpreter bildet auf den Rückgabewert ab).
        void CustomWindowBegin(string msbt, IReadOnlyList<string> labels);
        bool CustomWindowTryGetResult(out int index);

        // Spielwelt
        void StartTrainerBattle(int trainerId1, int trainerId2);
        bool BattleIsDone();
        void ChangeMap(string zoneName, int locator);
        bool MapChangeIsDone();
        // objectName == null: Objekt über objectIndex. actions = Befehle des Bewegungsskripts (AC_*, bis ACMD_END).
        void ObjectAnimate(string objectName, int objectIndex, string label, IReadOnlyList<EventCommand> actions, float speed);
        // objectName leer: alle Objekte.
        bool ObjectAnimationIsDone(string objectName);

        // Beutel und Geld
        void AddItem(int itemNo, int count);
        bool CanAddItem(int itemNo, int count);
        void SubItem(int itemNo, int count);
        int GetItemCount(int itemNo);
        int GetMoney();
        void AddMoney(int delta);

        // Abzeichenzahl neu setzen (SetSysFlag im Original zählt die Systemflags 0x7C..0x83).
        void SetBadgeCount(int count);

        // Hilfen
        int ResolveTrainerId(string name);   // TrainerID-Enum-Name ("LEADER3_01") -> Nummer; Rückgabe < 0 = unbekannt
        int RandomRange(int maxExclusive);   // UnityEngine.Random.Range(0, max)

        // Alle anderen Befehle (Darstellung, Kamera, Menüs, Namenswörter usw.): true = fertig. Für Befehle mit Wartezeit
        // wird der Aufruf mit steigendem Phase-Wert wiederholt.
        bool ExecuteCommand(EvCommandCall call);

        // Ereignis zu Ende (END, Skriptende, RET bei leerem Stapel).
        void EventEnded();
    }
}
