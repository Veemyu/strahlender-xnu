using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using Xnu.Battle.Flow;

namespace Xnu.Tests
{
    // Vergleicht die in C# umgesetzten KI-Skriptfunktionen mit den ECHTEN ARM64-Funktionen (scripts/battle_oracle_ai.py, Unicorn).
    // Beide laufen gegen dieselbe Pseudo-Welt (SplitMix64-Antworten je Seed/Aufrufnummer/Befehl) und muessen dieselbe Aufruffolge
    // (Befehl + Argumente), dieselbe Rueckgabe und dieselbe Endwertung liefern.
    public class BattleAiScriptOracleTests
    {
        sealed class HashWorld : IAiHost
        {
            readonly ulong _seed;
            readonly long[] _big;
            readonly Dictionary<int, long> _override;
            public int Calls;
            public ulong Hash = 0xCBF29CE484222325UL;
            public readonly List<string> Trace = new List<string>();

            public HashWorld(ulong seed, long[] big, Dictionary<int, long> fixedAnswers)
            {
                _seed = seed;
                _big = big;
                _override = fixedAnswers;
            }

            static ulong SplitMix(ulong x)
            {
                unchecked
                {
                    x += 0x9E3779B97F4A7C15UL;
                    ulong z = x;
                    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9UL;
                    z = (z ^ (z >> 27)) * 0x94D049BB133111EBUL;
                    return z ^ (z >> 31);
                }
            }

            void Mix(long v)
            {
                unchecked
                {
                    Hash ^= (ulong)v;
                    Hash *= 0x100000001B3UL;
                }
            }

            public long Call(int cmd, long[] args)
            {
                ulong h;
                unchecked { h = SplitMix(_seed * 0x9E3779B97F4A7C15UL + (ulong)Calls * 0xD1B54A32D192ED03UL + (ulong)cmd * 0x94D049BB133111EBUL); }
                ulong sel = h % 32;
                long ans = sel < 20 ? (long)((h >> 8) % 14) : sel < 26 ? _big[(int)((h >> 8) % (ulong)_big.Length)] : sel < 29 ? 1 : 0;
                if (_override != null && _override.TryGetValue(cmd, out long fixedAnswer)) ans = fixedAnswer;
                Mix(cmd);
                Mix(args.Length);
                foreach (long a in args) Mix(a);
                Trace.Add(cmd + "(" + string.Join(",", args) + ")=" + ans);
                Calls++;
                return ans;
            }
        }

        static List<Dictionary<string, object>> Functions(Dictionary<string, object> root, string cls)
        {
            var classes = (Dictionary<string, object>)root["classes"];
            var list = new List<Dictionary<string, object>>();
            if (!classes.TryGetValue(cls, out var funcs)) return list;
            foreach (var f in (List<object>)funcs) list.Add((Dictionary<string, object>)f);
            return list;
        }

        // Die in den Code eingebettete Verteilertabelle (KI-Nummer -> Seq-Funktion) muss der aus Calc_BasicAll gemessenen entsprechen.
        static void CheckDispatch()
        {
            var disp = (Dictionary<string, object>)BattleFixtures.Load("BattleAiDispatch.json")["BtlAiBasic"];
            Assert.AreEqual(disp.Count, AiScriptBasic.SeqDispatch.Count);
            foreach (var kv in disp)
                Assert.AreEqual(int.Parse(((string)kv.Value).Substring("BaciAI_Seq_".Length)), AiScriptBasic.SeqDispatch[int.Parse(kv.Key)], "KI-Nummer " + kv.Key);
        }

        internal static void Check(string cls, AiScriptBase script, string fixture = "BattleAiScripts.json")
        {
            var root = BattleFixtures.Load(fixture);
            var funcs = Functions(root, cls);
            int checkedFunctions = 0, checkedCases = 0, skipped = 0;
            var failures = new List<string>();
            foreach (var f in funcs)
            {
                string name = (string)f["name"];
                if (!script.Functions.Contains(name)) continue;
                var big = ((List<object>)f["big"]).Select(Convert.ToInt64).ToArray();
                Dictionary<int, long> fixedAnswers = null;
                if (f.TryGetValue("override", out var ov))
                {
                    fixedAnswers = new Dictionary<int, long>();
                    foreach (var kv in (Dictionary<string, object>)ov) fixedAnswers[int.Parse(kv.Key)] = Convert.ToInt64(kv.Value);
                }
                checkedFunctions++;
                foreach (var c in (List<object>)f["cases"])
                {
                    var row = ((List<object>)c).Select(x => x is string s ? s : (object)Convert.ToInt64(x)).ToList();
                    ulong seed = (ulong)(long)row[0];
                    long expRet = (long)row[1];
                    int expScore = (int)(long)row[2];
                    int expCalls = (int)(long)row[4];
                    string expHash = (string)row[5];
                    int enteredSeq = row.Count > 6 ? (int)(long)row[6] : 0;
                    // Laeuft der echte Ablauf in eine (noch) nicht umgesetzte Seq-Funktion, ist der Fall nicht vergleichbar.
                    if (enteredSeq != 0 && !AiScriptBasic.ImplementedSeq.Contains(enteredSeq) && cls == "BtlAiBasic") { skipped++; continue; }
                    var world = new HashWorld(seed, big, fixedAnswers);
                    script.Host = world;
                    script.Score = 0;
                    long ret = script.Run(name);
                    string hash = world.Hash.ToString("x16");
                    checkedCases++;
                    bool ok = hash == expHash && world.Calls == expCalls && script.Score == expScore && (expRet < 0 || (ret & 1) == expRet);
                    if (!ok && failures.Count < 40)
                        failures.Add($"{cls}.{name} seed {seed}: erwartet score {expScore} calls {expCalls} ret {expRet} hash {expHash}; war score {script.Score} calls {world.Calls} ret {(ret & 1)} hash {hash}; Folge: {string.Join(" ", world.Trace)}");
                }
            }
            TestContext.Out.WriteLine($"{cls}: {checkedFunctions} Funktionen, {checkedCases} Faelle gegen das Orakel geprueft, {skipped} uebersprungen (Ablauf erreicht nicht umgesetzte Seq-Funktion)");
            var byName = failures.Select(x => x.Substring(0, x.IndexOf(" seed"))).Distinct().ToList();
            Assert.AreEqual(0, failures.Count, "Abweichende Funktionen: " + string.Join(", ", byName) + "\n" + string.Join("\n", failures.GroupBy(x => x.Substring(0, x.IndexOf(" seed"))).Select(g => g.First())));
            Assert.Greater(checkedFunctions, 0);
        }

        [Test]
        public void DoubleScriptMatchesOracle() => Check("BtlAiDouble", Gen("AiScriptDouble"), "BattleAiScriptsDouble.json");

        [Test]
        public void ExpertScriptMatchesOracle() => Check("BtlAiExpert", Gen("AiScriptExpert"), "BattleAiScriptsExpert.json");

        [Test]
        public void StrongFullScriptMatchesOracle() => Check("BtlAiStrong", Gen("AiScriptStrongFull"), "BattleAiScriptsStrongFull.json");

        // Die Klassen entstehen beim Bauen aus dem eigenen Dump (scripts/ai_translate); ohne sie wird übersprungen.
        static AiScriptBase Gen(string className)
        {
            var s = AiGenerated.Create(className);
            if (s == null) Assert.Ignore("Erzeugte KI-Klasse " + className + " fehlt (Build-Stufe ai_translate nicht gelaufen).");
            return s;
        }

        // Die übrigen BaciAI_Seq_*-Funktionen (aus dem Pseudocode übersetzt) und die von Hand umgesetzten gemeinsam, ohne den Verteiler-Überspringer.
        [Test]
        public void BasicSeqScriptsMatchOracle() => Check("BtlAiBasic", new AiScriptBasic(), "BattleAiScriptsBasicSeq.json");

        [Test]
        public void StrongScriptMatchesOracle() => Check("BtlAiStrong", new AiScriptStrong());

        [Test]
        public void AllowanceScriptMatchesOracle() => Check("BtlAiAllowance", new AiScriptAllowance());

        [Test]
        public void PokeChangeScriptMatchesOracle() => Check("BtlAiPokeChange", new AiScriptPokeChange());

        [Test]
        public void ItemScriptMatchesOracle() => Check("BtlAiItem", new AiScriptItem());

        [Test]
        public void BasicScriptMatchesOracle()
        {
            CheckDispatch();
            Check("BtlAiBasic", new AiScriptBasic());
        }

        [Test]
        public void ImplementedSeqFunctionsAreDispatched()
        {
            new AiScriptBasic();     // die Konstruktion trägt die erzeugten Seq-Funktionen in ImplementedSeq ein
            var targets = new HashSet<int>(AiScriptBasic.SeqDispatch.Values);
            foreach (int n in targets) Assert.IsTrue(AiScriptBasic.ImplementedSeq.Contains(n), "Seq " + n + " ist nicht umgesetzt");
        }
    }
}
