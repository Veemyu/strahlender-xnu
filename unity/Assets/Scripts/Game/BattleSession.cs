using System;
using System.Collections.Generic;
using Xnu.Battle;
using Xnu.Battle.Flow;
using Xnu.PokePara;

namespace Xnu.Game
{
    public sealed class BattleOutcome
    {
        public BattleResult Result = BattleResult.None;
        public int PrizeMoney;
        public int MoneyLost;
        public bool PlayerLost => Result == BattleResult.Lose;
        public bool Skipped;       // Kampf konnte nicht gebaut werden (Trainer/Art unbekannt); der Wunsch gilt als erledigt
        public string Error = "";
        public int Turns;
    }

    // Ein laufender Kampf der Spielschleife: baut BattleSetup aus Sitzung und Wunsch, nimmt Eingaben als Daten entgegen und schreibt das Ergebnis zurück.
    public sealed class BattleSession
    {
        public BattleEngine Engine { get; private set; }
        public BattleRequest Request { get; }
        public GameSession Session { get; }
        public BattleOutcome Outcome { get; private set; }
        public int InvalidCommands { get; private set; }
        List<PokemonParam> _party;
        Dictionary<int, int> _bagBefore;

        public BattleSession(GameSession session, BattleRequest request)
        {
            Session = session ?? throw new ArgumentNullException(nameof(session));
            Request = request ?? throw new ArgumentNullException(nameof(request));
        }

        public bool IsFinished => Outcome != null;

        // Baut den Kampf. false: nicht möglich (Outcome.Skipped).
        public bool Start()
        {
            try
            {
                var setup = BuildSetup();
                Engine = new BattleEngine(setup);
                Engine.Start();
                return true;
            }
            catch (Exception ex) when (ex is KeyNotFoundException || ex is ArgumentException || ex is InvalidOperationException)
            {
                Outcome = new BattleOutcome { Skipped = true, Error = ex.Message };
                return false;
            }
        }

        BattleSetup BuildSetup()
        {
            var data = Session.Data.Battle;
            var setup = new BattleSetup
            {
                Data = data,
                Seed = Session.NextSeed(),
                PlayerBadges = Math.Min(Session.BadgeCount, 8),
                PlayerMoney = (uint)Session.Money,
            };
            _party = Session.GetParty();
            setup.PlayerParty = new List<PokemonParam>(_party);
            if (Request.Kind == BattleRequestKind.Wild)
            {
                setup.Competitor = BattleCompetitor.Wild;
                setup.EnemyParty.Add(PokemonFactory.CreateWild(data, Request.MonsNo, Request.FormNo, Request.Level, new BattleRandom(setup.Seed ^ 0xC0FFEEUL)));
            }
            else
            {
                var trainer = Session.Data.GetTrainer(Request.TrainerId);
                if (trainer == null || trainer.Party == null || trainer.Party.Members.Count == 0)
                    throw new KeyNotFoundException("Trainer " + Request.TrainerId + " ohne Team");
                setup.Competitor = BattleCompetitor.Trainer;
                setup.TrainerGold = trainer.Gold;
                foreach (var m in trainer.Party.Members) setup.EnemyParty.Add(PokemonFactory.FromTrainerPokemon(data, m));
            }
            _bagBefore = new Dictionary<int, int>();
            for (var item = 1; item < Xnu.Save.SavePlayerLayout.ItemSlotCount; item++)
            {
                var n = Session.Save.GetItemCount(item);
                if (n > 0) _bagBefore[item] = n;
            }
            setup.Bag = new Dictionary<int, int>(_bagBefore);
            return setup;
        }

        // Ein Schritt: Eingabe (Befehl oder Ersatz) an die Engine geben; bei Ende Ergebnis zurückschreiben.
        public void Step(GameInput input)
        {
            if (Outcome != null || Engine == null) return;
            try
            {
                if (Engine.Phase == BattlePhase.AwaitCommands && input.Battle.HasValue)
                    Engine.Submit(input.Battle.Value);
                else if (Engine.Phase == BattlePhase.AwaitReplacement && input.Replacement >= 0)
                    Engine.SubmitReplacement(input.Replacement);
            }
            catch (ArgumentException)
            {
                InvalidCommands++;
            }
            if (Engine.Phase == BattlePhase.Finished) Finish();
        }

        void Finish()
        {
            var o = new BattleOutcome { Result = Engine.Result, Turns = Engine.Turn };
            // WriteBack hat die Engine schon an den Quell-Objekten erledigt; jetzt in den Spielstand schreiben.
            Session.Save.SetParty(_party);
            foreach (var kv in _bagBefore)
            {
                Engine.Bag.TryGetValue(kv.Key, out var now);
                if (now != kv.Value) Session.Save.SetItemCount(kv.Key, now);
            }
            if (Engine.Result == BattleResult.Win && Request.Kind == BattleRequestKind.Trainer)
            {
                o.PrizeMoney = Engine.PrizeMoney;
                Session.AddMoney(o.PrizeMoney);
            }
            else if (Engine.Result == BattleResult.Lose)
            {
                o.MoneyLost = (int)Engine.PenaltyMoney;
                Session.AddMoney(-o.MoneyLost);
            }
            Outcome = o;
        }
    }
}
