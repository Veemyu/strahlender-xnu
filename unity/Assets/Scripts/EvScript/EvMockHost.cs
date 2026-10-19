using System;
using System.Collections.Generic;
using Xnu.Data;

namespace Xnu.EvScript
{
    // Einfacher Host ohne Spielwelt: jede Abfrage ist sofort fertig, Aufrufe werden gezählt und optional protokolliert.
    // Für Tests und Massenläufe über alle Skripte. WaitPolls > 0 lässt jede "IsDone"-Abfrage so oft false liefern.
    public class EvMockHost : IEvHost
    {
        public readonly List<string> Log = new List<string>();
        public bool Record = true;
        public int WaitPolls;
        public int YesNoAnswer;
        public int CustomAnswer;
        public int Money = 3000;
        public int BadgeCount;
        public readonly Dictionary<int, int> Items = new Dictionary<int, int>();
        public readonly Dictionary<string, int> TrainerIds = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        public int HostCommandCalls;
        public int EventEndCount;
        public int Seed = 1;

        int _polls;

        void Add(string s)
        {
            if (Record) Log.Add(s);
        }

        bool Poll()
        {
            if (_polls < WaitPolls)
            {
                _polls++;
                return false;
            }
            _polls = 0;
            return true;
        }

        public virtual void TalkBegin(EvTalkRequest request) => Add("talk " + request.Msbt + "%" + request.Label + (request.Flag ? " flag" : ""));
        public virtual bool TalkIsDone() => Poll();
        public virtual void TalkClose(bool clear) => Add(clear ? "talkclose" : "talkclose-noclear");

        public virtual void YesNoBegin(bool defaultYes) => Add("yesno");
        public virtual bool YesNoTryGetResult(out int index)
        {
            index = YesNoAnswer;
            return Poll();
        }

        public virtual void CustomWindowBegin(string msbt, IReadOnlyList<string> labels) => Add("custom " + msbt + " " + labels.Count);
        public virtual bool CustomWindowTryGetResult(out int index)
        {
            index = CustomAnswer;
            return Poll();
        }

        public virtual void StartTrainerBattle(int trainerId1, int trainerId2) => Add("battle " + trainerId1 + "," + trainerId2);
        public virtual bool BattleIsDone() => Poll();
        public virtual void ChangeMap(string zoneName, int locator) => Add("map " + zoneName + " " + locator);
        public virtual bool MapChangeIsDone() => Poll();

        public virtual void ObjectAnimate(string objectName, int objectIndex, string label, IReadOnlyList<EventCommand> actions, float speed) =>
            Add("anim " + (objectName ?? "#" + objectIndex) + " " + label + " " + actions.Count);

        public virtual bool ObjectAnimationIsDone(string objectName) => Poll();

        public virtual void AddItem(int itemNo, int count)
        {
            Items.TryGetValue(itemNo, out var n);
            Items[itemNo] = n + count;
            Add("additem " + itemNo + " " + count);
        }

        public virtual bool CanAddItem(int itemNo, int count)
        {
            Items.TryGetValue(itemNo, out var n);
            return n + count <= 999;
        }

        public virtual void SubItem(int itemNo, int count)
        {
            Items.TryGetValue(itemNo, out var n);
            Items[itemNo] = Math.Max(0, n - count);
            Add("subitem " + itemNo + " " + count);
        }

        public virtual int GetItemCount(int itemNo)
        {
            Items.TryGetValue(itemNo, out var n);
            return n;
        }

        public virtual int GetMoney() => Money;

        // MoneyWork.Add: Ergebnis auf 0..999999 begrenzt.
        public virtual void AddMoney(int delta)
        {
            Money = Math.Max(0, Math.Min(999999, Money + delta));
            Add("money " + delta);
        }

        public virtual void SetBadgeCount(int count) => BadgeCount = count;

        public virtual int ResolveTrainerId(string name) => TrainerIds.TryGetValue(name, out var id) ? id : -1;

        public virtual int RandomRange(int maxExclusive)
        {
            Seed = unchecked(Seed * 1103515245 + 12345);
            return maxExclusive <= 0 ? 0 : (int)((uint)Seed >> 8) % maxExclusive;
        }

        public virtual bool ExecuteCommand(EvCommandCall call)
        {
            HostCommandCalls++;
            if (call.First) Add("host " + call.Id);
            return Poll();
        }

        public virtual void EventEnded()
        {
            EventEndCount++;
            Add("end");
        }
    }
}
