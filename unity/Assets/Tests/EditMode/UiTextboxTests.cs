using System.Collections.Generic;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.UI;
using Xnu.Text;
using Xnu.UI;

namespace Xnu.Tests
{
    // Ausschließlich erfundene Texte; keine Spieldaten.
    public class UiTextboxTests
    {
        static UiInputState Confirm() => new UiInputState(true, false, true, false);
        static UiInputState Cancel() => new UiInputState(false, true, false, true);
        static UiInputState Hold() => new UiInputState(false, false, true, false);
        static UiInputState Idle() => UiInputState.None;

        static ComposedMessage Msg(params (string text, MessageEvent ev, float value)[] lines)
        {
            var m = new ComposedMessage();
            foreach (var l in lines) m.Lines.Add(new ComposedLine { Text = l.text, EndEvent = l.ev, EventValue = l.value });
            return m;
        }

        static TextboxFlow OpenInstant(ComposedMessage m, MessageSpeed speed = MessageSpeed.Normal)
        {
            var f = new TextboxFlow(m, speed) { OpenDuration = 0f, CloseDuration = 0f };
            f.Open();
            return f;
        }

        // Läuft Bild für Bild bis zum Zustand (oder der Obergrenze) und liefert die Anzahl Bilder.
        static int RunUntil(TextboxFlow f, TextboxState state, float dt = 1f / 60f, int max = 5000)
        {
            var n = 0;
            while (f.State != state && n < max) { f.Update(dt, Idle()); n++; }
            return n;
        }

        // Spielt die Zeit in Schritten von 1/60 s ab (ein Update behandelt höchstens einen Abschnittswechsel).
        static void Run(TextboxFlow f, float seconds)
        {
            for (var t = 0f; t < seconds; t += 1f / 60f) f.Update(1f / 60f, Idle());
        }

        static void Run(TextboxView v, float seconds)
        {
            for (var t = 0f; t < seconds; t += 1f / 60f) v.Tick(1f / 60f, UiInputState.None);
        }

        // --- Schreibmaschine ---

        [Test]
        public void TypewriterNormalShowsOneGlyphPer30Ms()
        {
            var f = OpenInstant(Msg(("Hallo", MessageEvent.End, 0)));
            Assert.AreEqual(TextboxState.Typing, f.State);
            Assert.AreEqual("", f.DisplayText);
            f.Update(0.031f, Idle());
            Assert.AreEqual("H", f.DisplayText);
            f.Update(0.060f, Idle());
            Assert.AreEqual("Hal", f.DisplayText);
        }

        [TestCase(MessageSpeed.Slow, 0.06f)]
        [TestCase(MessageSpeed.Normal, 0.03f)]
        [TestCase(MessageSpeed.Fast, 0.01f)]
        public void TypewriterSpeedsMatchMeasuredValues(MessageSpeed speed, float perChar)
        {
            var f = OpenInstant(Msg(("abcdefghij", MessageEvent.End, 0)), speed);
            f.Update(perChar * 5 + 0.001f, Idle());
            Assert.AreEqual("abcde", f.DisplayText);
        }

        [Test]
        public void HoldingConfirmFastForwardsByFactorFive()
        {
            var f = OpenInstant(Msg(("abcdefghijklmnopqrst", MessageEvent.End, 0)));
            f.Update(0.06f, Hold());
            Assert.AreEqual(10, f.DisplayText.Length);
        }

        [Test]
        public void SinglePressDoesNotSkipTyping()
        {
            var f = OpenInstant(Msg(("abcdefghij", MessageEvent.End, 0)));
            f.Update(0.001f, Confirm());
            Assert.AreEqual(TextboxState.Typing, f.State);
            Assert.AreEqual("", f.DisplayText);
        }

        [Test]
        public void RichTextMarkupDoesNotCountAsGlyphs()
        {
            var f = OpenInstant(Msg(("<color=#ff0000>Rot</color>!", MessageEvent.End, 0)));
            f.Update(0.031f, Idle());
            Assert.AreEqual("<color=#ff0000>R", f.DisplayText);
            f.Update(0.5f, Idle());
            Assert.AreEqual("<color=#ff0000>Rot</color>!", f.DisplayText);
        }

        // --- Ablauf und Tastenwarten ---

        [Test]
        public void EndWaitsForKeyAfterGraceFramesThenCloses()
        {
            var f = OpenInstant(Msg(("Ok", MessageEvent.End, 0)));
            f.Update(1f, Idle());
            Assert.AreEqual(TextboxState.WaitKey, f.State);
            Assert.IsTrue(f.KeyIconVisible);
            // Die ersten Bilder (waitAfterFinishMsgFrame = 4) ignorieren Eingaben.
            for (var i = 0; i < 4; i++) f.Update(0f, Confirm());
            Assert.AreEqual(TextboxState.WaitKey, f.State);
            f.Update(0f, Confirm());
            Assert.IsTrue(f.IsClosed);
        }

        [Test]
        public void CancelAlsoAdvances()
        {
            var f = OpenInstant(Msg(("Ok", MessageEvent.End, 0)));
            f.Update(1f, Idle());
            for (var i = 0; i < 10; i++) f.Update(0f, Idle());
            f.Update(0f, Cancel());
            Assert.IsTrue(f.IsClosed);
        }

        [Test]
        public void NewLineContinuesWithoutKey()
        {
            var f = OpenInstant(Msg(("Eins", MessageEvent.NewLine, 0), ("Zwei", MessageEvent.End, 0)));
            Run(f, 1f);
            Assert.AreEqual(TextboxState.WaitKey, f.State);
            Assert.AreEqual("Eins\nZwei", f.DisplayText);
        }

        [Test]
        public void TimedWaitHoldsForTheGivenSeconds()
        {
            var f = OpenInstant(Msg(("A", MessageEvent.Wait, 0.5f), ("B", MessageEvent.End, 0)));
            f.Update(0.04f, Idle());
            Assert.AreEqual(TextboxState.TimedWait, f.State);
            f.Update(0.4f, Idle());
            Assert.AreEqual(TextboxState.TimedWait, f.State);
            f.Update(0.2f, Idle());
            Assert.AreEqual(TextboxState.Typing, f.State);
            f.Update(0.5f, Idle());
            Assert.AreEqual("AB", f.DisplayText);
        }

        [Test]
        public void CallBackFiresWithNumberAndContinues()
        {
            var seen = new List<int>();
            var f = OpenInstant(Msg(("A", MessageEvent.CallBack, 7), ("B", MessageEvent.End, 0)));
            f.CallBack += seen.Add;
            f.Update(0.04f, Idle());
            CollectionAssert.AreEqual(new[] { 7 }, seen);
            Assert.AreEqual(TextboxState.Typing, f.State);
        }

        [Test]
        public void ScrollPageClearsPageAfterKey()
        {
            var f = OpenInstant(Msg(("Seite eins", MessageEvent.ScrollPage, 0), ("Seite zwei", MessageEvent.End, 0)));
            f.Update(10f, Idle());
            Assert.AreEqual(TextboxState.WaitKey, f.State);
            Assert.AreEqual("Seite eins", f.DisplayText);
            for (var i = 0; i < 5; i++) f.Update(0f, Idle());
            f.Update(0f, Confirm());
            Assert.AreEqual(TextboxState.Typing, f.State);
            Assert.AreEqual("", f.DisplayText);
            f.Update(10f, Idle());
            Assert.AreEqual("Seite zwei", f.DisplayText);
        }

        [Test]
        public void ScrollLineKeepsTextAndAnimatesFor150Ms()
        {
            var f = OpenInstant(Msg(("Oben", MessageEvent.ScrollLine, 0), ("Unten", MessageEvent.End, 0)));
            f.Update(10f, Idle());
            Assert.AreEqual("Oben\n", f.DisplayText);
            for (var i = 0; i < 5; i++) f.Update(0f, Idle());
            f.Update(0f, Confirm());
            Assert.AreEqual(TextboxState.Scrolling, f.State);
            f.Update(0.075f, Idle());
            Assert.AreEqual(0.5f, f.ScrollProgress, 1e-4f);
            Assert.AreEqual(0, f.ScrolledLines);
            f.Update(0.1f, Idle());
            Assert.AreEqual(1, f.ScrolledLines);
            Assert.AreEqual(TextboxState.Typing, f.State);
            f.Update(10f, Idle());
            Assert.AreEqual("Oben\nUnten", f.DisplayText);
        }

        [Test]
        public void OpeningAndClosingAnimateWindowProgress()
        {
            var f = new TextboxFlow(Msg(("X", MessageEvent.End, 0))) { OpenDuration = 0.1f, CloseDuration = 0.2f };
            Assert.AreEqual(0f, f.WindowProgress);
            f.Open();
            Assert.AreEqual(TextboxState.Opening, f.State);
            f.Update(0.05f, Idle());
            Assert.AreEqual(0.5f, f.WindowProgress, 1e-4f);
            f.Update(0.06f, Idle());
            Assert.AreEqual(TextboxState.Typing, f.State);
            Assert.AreEqual(1f, f.WindowProgress);
            f.Update(1f, Idle());
            for (var i = 0; i < 5; i++) f.Update(0f, Idle());
            f.Update(0f, Confirm());
            Assert.AreEqual(TextboxState.Closing, f.State);
            f.Update(0.1f, Idle());
            Assert.AreEqual(0.5f, f.WindowProgress, 1e-4f);
            f.Update(0.2f, Idle());
            Assert.IsTrue(f.IsClosed);
        }

        [Test]
        public void InputWhileOpeningIsIgnored()
        {
            var f = new TextboxFlow(Msg(("X", MessageEvent.End, 0))) { OpenDuration = 0.1f };
            f.Open();
            f.Update(0.01f, Confirm());
            Assert.AreEqual(TextboxState.Opening, f.State);
        }

        [Test]
        public void HeldAtEndStaysOpenUntilClosed()
        {
            var f = OpenInstant(Msg(("Frage", MessageEvent.End, 0)));
            f.HoldOpenAtEnd = true;
            f.Update(10f, Idle());
            Assert.AreEqual(TextboxState.Held, f.State);
            Assert.IsFalse(f.KeyIconVisible);
            for (var i = 0; i < 20; i++) f.Update(0.1f, Confirm());
            Assert.AreEqual(TextboxState.Held, f.State);
            f.Close();
            Assert.IsTrue(f.IsClosed);
        }

        [Test]
        public void FlowCannotOpenTwiceAndRejectsNegativeTime()
        {
            var f = OpenInstant(Msg(("X", MessageEvent.End, 0)));
            Assert.Throws<System.InvalidOperationException>(() => f.Open());
            Assert.Throws<System.ArgumentOutOfRangeException>(() => f.Update(-1f, Idle()));
        }

        [Test]
        public void EmptyLabelStillWaitsForKey()
        {
            var f = OpenInstant(Msg(("", MessageEvent.End, 0)));
            Assert.AreEqual(TextboxState.WaitKey, f.State);
        }

        [Test]
        public void FullRunWithDeltaStepsFinishesWithinExpectedTime()
        {
            // 10 Zeichen bei 0,03 s = 0,3 s, dann Tastenwarten.
            var f = OpenInstant(Msg(("abcdefghij", MessageEvent.End, 0)));
            var frames = RunUntil(f, TextboxState.WaitKey);
            Assert.That(frames, Is.InRange(17, 19));
        }

        // --- Platzhalter-Nachricht, Composer ---

        [Test]
        public void PlainMessageSplitsOnControlCharacters()
        {
            var m = PlainMessage.Parse("a\nb\vc\fd");
            Assert.AreEqual(4, m.Lines.Count);
            Assert.AreEqual(MessageEvent.NewLine, m.Lines[0].EndEvent);
            Assert.AreEqual(MessageEvent.ScrollLine, m.Lines[1].EndEvent);
            Assert.AreEqual(MessageEvent.ScrollPage, m.Lines[2].EndEvent);
            Assert.AreEqual(MessageEvent.End, m.Lines[3].EndEvent);
            Assert.AreEqual("d", m.Lines[3].Text);
        }

        [Test]
        public void PlainMessageOfNullIsOneEmptyEndSection()
        {
            var m = PlainMessage.Parse(null);
            Assert.AreEqual(1, m.Lines.Count);
            Assert.AreEqual(MessageEvent.End, m.Lines[0].EndEvent);
        }

        // --- Auswahlmenü ---

        [Test]
        public void ChoiceCursorWrapsAndConfirmSelects()
        {
            var c = new ChoiceMenuModel(2, cancelIndex: 1);
            c.Update(new UiInputState(false, false, false, false, 1));
            Assert.AreEqual(1, c.Cursor);
            c.Update(new UiInputState(false, false, false, false, 1));
            Assert.AreEqual(0, c.Cursor);
            c.Update(new UiInputState(false, false, false, false, -1));
            Assert.AreEqual(1, c.Cursor);
            c.Update(Confirm());
            Assert.IsTrue(c.IsDone);
            Assert.AreEqual(1, c.Result);
            Assert.IsFalse(c.WasCancelled);
        }

        [Test]
        public void ChoiceCancelSelectsCancelEntry()
        {
            var c = new ChoiceMenuModel(2, cancelIndex: 1);
            c.Update(Cancel());
            Assert.IsTrue(c.IsDone);
            Assert.AreEqual(1, c.Result);
            Assert.IsTrue(c.WasCancelled);
        }

        [Test]
        public void ChoiceCancelIgnoredWithoutCancelEntryAndNoWrapClamps()
        {
            var c = new ChoiceMenuModel(3, cancelIndex: -1, wrap: false);
            c.Update(Cancel());
            Assert.IsFalse(c.IsDone);
            c.Update(new UiInputState(false, false, false, false, -1));
            Assert.AreEqual(0, c.Cursor);
            for (var i = 0; i < 5; i++) c.Update(new UiInputState(false, false, false, false, 1));
            Assert.AreEqual(2, c.Cursor);
        }

        [Test]
        public void ChoiceRejectsInvalidArguments()
        {
            Assert.Throws<System.ArgumentOutOfRangeException>(() => new ChoiceMenuModel(0));
            Assert.Throws<System.ArgumentOutOfRangeException>(() => new ChoiceMenuModel(2, cancelIndex: 2));
            Assert.Throws<System.ArgumentOutOfRangeException>(() => new ChoiceMenuModel(2, initial: 2));
        }

        // --- Eingabequellen ---

        [Test]
        public void ManualInputReportsEdgesForOnePollOnly()
        {
            var m = new ManualUiInput();
            m.PressConfirm();
            var a = m.Poll();
            Assert.IsTrue(a.ConfirmPressed);
            Assert.IsTrue(a.ConfirmHeld);
            var b = m.Poll();
            Assert.IsFalse(b.ConfirmPressed);
            Assert.IsFalse(b.ConfirmHeld);
            m.HoldConfirm(true);
            Assert.IsTrue(m.Poll().ConfirmHeld);
        }

        [Test]
        public void MergedInputCombinesSources()
        {
            var a = new ManualUiInput();
            var b = new ManualUiInput();
            a.PressConfirm();
            b.PressCancel();
            b.MoveDown();
            var s = new MergedUiInput(a, b).Poll();
            Assert.IsTrue(s.ConfirmPressed);
            Assert.IsTrue(s.CancelPressed);
            Assert.AreEqual(1, s.MoveY);
        }

        // --- Unity-Objekte ---

        [Test]
        public void CanvasMatchesOriginalScaling()
        {
            var canvas = UiCanvasFactory.Create("TestCanvas", null, 400);
            try
            {
                var scaler = canvas.GetComponent<CanvasScaler>();
                Assert.AreEqual(CanvasScaler.ScaleMode.ScaleWithScreenSize, scaler.uiScaleMode);
                Assert.AreEqual(new Vector2(1280f, 720f), scaler.referenceResolution);
                Assert.AreEqual(CanvasScaler.ScreenMatchMode.MatchWidthOrHeight, scaler.screenMatchMode);
                Assert.AreEqual(0f, scaler.matchWidthOrHeight);
                Assert.AreEqual(RenderMode.ScreenSpaceOverlay, canvas.renderMode);
                Assert.AreEqual(400, canvas.sortingOrder);
            }
            finally { Object.DestroyImmediate(canvas.gameObject); }
        }

        [Test]
        public void PlaceholderSkinHasSlicedFrameAndIcon()
        {
            var skin = TextboxSkin.Placeholder();
            Assert.IsNotNull(skin.Frame);
            Assert.IsNotNull(skin.KeyIcon);
            Assert.IsFalse(skin.IsOriginal);
            Assert.Greater(skin.Frame.border.x, 0f);
        }

        [Test]
        public void FrameSpriteNamesAreTwoDigit()
        {
            Assert.AreEqual("cmn_wd_message_01_01_l", TextboxSkin.FrameSpriteName(1));
            Assert.AreEqual("cmn_wd_message_01_24_l", TextboxSkin.FrameSpriteName(24));
        }

        [Test]
        public void ViewShowsTypewriterTextAndClosesWithManualTicks()
        {
            var go = new GameObject("TextboxTest");
            try
            {
                var view = go.AddComponent<TextboxView>();
                view.Configure(null, 1, false, MessageSpeed.Normal);
                view.EnsureBuilt();
                Assert.IsTrue(view.IsBuilt);
                Assert.IsFalse(view.IsOpen);
                var closed = 0;
                view.Show("Erfundener Text.", () => closed++);
                Assert.IsTrue(view.IsOpen);
                view.Flow.OpenDuration = 0f;
                Run(view, 0.05f);
                var partial = view.Text.text;
                Assert.That(partial.Length, Is.InRange(1, 3));
                StringAssert.StartsWith(partial, "Erfundener Text.");
                Run(view, 2f);
                Assert.AreEqual("Erfundener Text.", view.Text.text);
                Assert.AreEqual(TextboxState.WaitKey, view.Flow.State);
                for (var i = 0; i < 6; i++) view.Tick(0f, UiInputState.None);
                view.Tick(0f, Confirm());
                view.Tick(1f, UiInputState.None);
                Assert.IsFalse(view.IsOpen);
                Assert.AreEqual(1, closed);
            }
            finally { Object.DestroyImmediate(go); }
        }

        [Test]
        public void ViewAskReturnsChosenAnswerAndClosesWindow()
        {
            var go = new GameObject("TextboxAskTest");
            try
            {
                var view = go.AddComponent<TextboxView>();
                view.Configure(null, 1, false, MessageSpeed.Fast);
                view.EnsureBuilt();
                var answer = -1;
                view.Ask("Frage?", new[] { "Ja", "Nein" }, 1, a => answer = a);
                for (var i = 0; i < 100 && !view.IsChoosing; i++) view.Tick(0.1f, UiInputState.None);
                Assert.IsTrue(view.IsChoosing);
                view.Tick(0f, Cancel());
                Assert.AreEqual(1, answer);
                for (var i = 0; i < 20 && view.IsOpen; i++) view.Tick(0.1f, UiInputState.None);
                Assert.IsFalse(view.IsOpen);
            }
            finally { Object.DestroyImmediate(go); }
        }

        [Test]
        public void ViewComposesMessageFromLabel()
        {
            var label = new MsbtLabel
            {
                Name = "LBL_TEST",
                Words = new[]
                {
                    new MsbtWord { Pattern = WordPattern.Str, Text = "Eins", Event = MessageEvent.NewLine },
                    new MsbtWord { Pattern = WordPattern.Str, Text = "Zwei", Event = MessageEvent.End },
                },
            };
            var go = new GameObject("TextboxLabelTest");
            try
            {
                var view = go.AddComponent<TextboxView>();
                view.Configure(null, 1, false, MessageSpeed.Fast);
                view.EnsureBuilt();
                view.Show(label);
                view.Flow.OpenDuration = 0f;
                Run(view, 1f);
                Assert.AreEqual("Eins\nZwei", view.Text.text);
            }
            finally { Object.DestroyImmediate(go); }
        }
    }
}
