using System;
using System.Linq;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.InputSystem;
using Xnu.Input;

namespace Xnu.Tests
{
    public class InputStickMathTests
    {
        [Test]
        public void InnerhalbDerTotzoneIstNull()
        {
            var v = StickMath.CircularDeadzone(0.1f, 0.1f, 0.2f, 0.95f);
            Assert.AreEqual(Stick2.Zero, v);
        }

        [Test]
        public void TotzoneIstKreisfoermigNichtQuadratisch()
        {
            // Beide Achsen unter 0,2, aber Betrag 0,28 > 0,2: bei quadratischer Totzone wäre das 0.
            var v = StickMath.CircularDeadzone(0.198f, 0.198f, 0.2f, 0.95f);
            Assert.Greater(v.Magnitude, 0f);
            // Auf der Achse selbst genau an der Grenze: 0.
            Assert.AreEqual(Stick2.Zero, StickMath.CircularDeadzone(0.2f, 0f, 0.2f, 0.95f));
        }

        [Test]
        public void RichtungBleibtErhalten()
        {
            var v = StickMath.CircularDeadzone(0.3f, 0.6f, 0.15f, 0.95f);
            Assert.AreEqual(0.3f / 0.6f, v.X / v.Y, 1e-4f);
            Assert.Greater(v.X, 0f);
            Assert.Greater(v.Y, 0f);
        }

        [Test]
        public void AussenzoneLiefertGenauEins()
        {
            Assert.AreEqual(1f, StickMath.CircularDeadzone(0.95f, 0f, 0.15f, 0.95f).Magnitude, 1e-5f);
            Assert.AreEqual(1f, StickMath.CircularDeadzone(0f, -1f, 0.15f, 0.95f).Magnitude, 1e-5f);
            var diag = StickMath.CircularDeadzone(1f, 1f, 0.15f, 0.95f); // Betrag 1,41 (Tastatur ohne Normalisierung)
            Assert.AreEqual(1f, diag.Magnitude, 1e-5f);
        }

        [Test]
        public void SkalierungIstLinearUndMonoton()
        {
            var prev = 0f;
            for (var m = 0.15f; m <= 0.95f; m += 0.05f)
            {
                var r = StickMath.CircularDeadzone(m, 0f, 0.15f, 0.95f).Magnitude;
                Assert.GreaterOrEqual(r, prev);
                prev = r;
            }
            Assert.AreEqual(0.5f, StickMath.CircularDeadzone(0.55f, 0f, 0.15f, 0.95f).X, 1e-5f);
        }

        [Test]
        public void NanUndUngueltigeParameter()
        {
            Assert.AreEqual(Stick2.Zero, StickMath.CircularDeadzone(float.NaN, 0f));
            Assert.Throws<ArgumentOutOfRangeException>(() => StickMath.CircularDeadzone(0.5f, 0f, -0.1f, 0.9f));
            Assert.Throws<ArgumentOutOfRangeException>(() => StickMath.CircularDeadzone(0.5f, 0f, 0.5f, 0.4f));
            Assert.Throws<ArgumentOutOfRangeException>(() => StickMath.CircularDeadzone(0.5f, 0f, 0.1f, 1.2f));
        }

        [Test]
        public void ClampUnitBegrenztNurDenBetrag()
        {
            Assert.AreEqual(1f, StickMath.ClampUnit(1f, 1f).Magnitude, 1e-5f);
            Assert.AreEqual(new Stick2(0.3f, -0.2f), StickMath.ClampUnit(0.3f, -0.2f));
            Assert.AreEqual(Stick2.Zero, StickMath.ClampUnit(float.NaN, 1f));
        }
    }

    public class InputDirectionTests
    {
        [TestCase(1f, 0f, Direction8.East)]
        [TestCase(1f, 1f, Direction8.NorthEast)]
        [TestCase(0f, 1f, Direction8.North)]
        [TestCase(-1f, 1f, Direction8.NorthWest)]
        [TestCase(-1f, 0f, Direction8.West)]
        [TestCase(-1f, -1f, Direction8.SouthWest)]
        [TestCase(0f, -1f, Direction8.South)]
        [TestCase(1f, -1f, Direction8.SouthEast)]
        [TestCase(0.1f, 0.1f, Direction8.None)]
        public void AchtRichtungen(float x, float y, Direction8 expected)
        {
            Assert.AreEqual(expected, DirectionMath.Quantize(x, y));
        }

        [Test]
        public void SektorgrenzenSindWinkelbasiert()
        {
            // 20° liegt noch im Osten-Sektor (±22,5°), 25° schon im Nordosten.
            Assert.AreEqual(Direction8.East, DirectionMath.Quantize(Mathf.Cos(20f * Mathf.Deg2Rad), Mathf.Sin(20f * Mathf.Deg2Rad)));
            Assert.AreEqual(Direction8.NorthEast, DirectionMath.Quantize(Mathf.Cos(25f * Mathf.Deg2Rad), Mathf.Sin(25f * Mathf.Deg2Rad)));
            // Vollkreis: 350° ist wieder Osten.
            Assert.AreEqual(Direction8.East, DirectionMath.Quantize(Mathf.Cos(350f * Mathf.Deg2Rad), Mathf.Sin(350f * Mathf.Deg2Rad)));
        }

        [Test]
        public void VierRichtungenOhneDiagonalen()
        {
            Assert.AreEqual(Direction8.East, DirectionMath.Quantize(1f, 0.6f, 0.5f, diagonals: false));
            Assert.AreEqual(Direction8.North, DirectionMath.Quantize(0.6f, 1f, 0.5f, diagonals: false));
            Assert.AreEqual(Direction8.West, DirectionMath.Quantize(-1f, -0.4f, 0.5f, diagonals: false));
            Assert.AreEqual(Direction8.South, DirectionMath.Quantize(0.1f, -1f, 0.5f, diagonals: false));
        }

        [Test]
        public void HystereseHaeltRichtungAnDerGrenze()
        {
            var q = new Direction8Quantizer(0.5f, 0.35f, 8f);
            Assert.AreEqual(Direction8.East, q.Update(1f, 0f));
            // 28° liegt knapp hinter der Grenze (22,5°), aber innerhalb der Hysterese (22,5+8): bleibt Osten.
            Assert.AreEqual(Direction8.East, q.Update(Mathf.Cos(28f * Mathf.Deg2Rad), Mathf.Sin(28f * Mathf.Deg2Rad)));
            // 35° ist deutlich darüber: Wechsel.
            Assert.AreEqual(Direction8.NorthEast, q.Update(Mathf.Cos(35f * Mathf.Deg2Rad), Mathf.Sin(35f * Mathf.Deg2Rad)));
            // Und zurück bei 20° erst, wenn über die Hysterese hinaus (45-22,5-8 = 14,5°).
            Assert.AreEqual(Direction8.NorthEast, q.Update(Mathf.Cos(20f * Mathf.Deg2Rad), Mathf.Sin(20f * Mathf.Deg2Rad)));
            Assert.AreEqual(Direction8.East, q.Update(Mathf.Cos(10f * Mathf.Deg2Rad), Mathf.Sin(10f * Mathf.Deg2Rad)));
        }

        [Test]
        public void SchwelleMitHysterese()
        {
            var q = new Direction8Quantizer(0.5f, 0.35f, 8f);
            Assert.AreEqual(Direction8.None, q.Update(0.45f, 0f));
            Assert.AreEqual(Direction8.East, q.Update(0.55f, 0f));
            Assert.AreEqual(Direction8.East, q.Update(0.4f, 0f), "unter Auslöseschwelle, über Loslassschwelle");
            Assert.AreEqual(Direction8.None, q.Update(0.3f, 0f));
        }

        [Test]
        public void SchrittUndVierWegReduktion()
        {
            Assert.AreEqual((1, 1), DirectionMath.Step(Direction8.NorthEast));
            Assert.AreEqual((0, -1), DirectionMath.Step(Direction8.South));
            Assert.AreEqual((0, 0), DirectionMath.Step(Direction8.None));
            Assert.IsTrue(DirectionMath.IsDiagonal(Direction8.SouthWest));
            Assert.IsFalse(DirectionMath.IsDiagonal(Direction8.West));
            Assert.AreEqual(Direction8.East, DirectionMath.ToFourWay(0.9f, 0.5f));
            Assert.AreEqual(Direction8.North, DirectionMath.ToFourWay(0.5f, 0.5f));
            Assert.AreEqual(Direction8.None, DirectionMath.ToFourWay(0f, 0f));
        }

        [Test]
        public void KombinationDeadzoneUndQuantisierung()
        {
            // Rohwerte eines leicht verrauschten Sticks in Ruhe erzeugen keine Richtung.
            var v = StickMath.CircularDeadzone(0.08f, -0.06f);
            Assert.AreEqual(Direction8.None, DirectionMath.Quantize(v.X, v.Y));
            // Voll nach rechts-oben gedrückt.
            v = StickMath.CircularDeadzone(0.75f, 0.7f);
            Assert.AreEqual(Direction8.NorthEast, DirectionMath.Quantize(v.X, v.Y));
        }
    }

    public class InputLayoutTests
    {
        [Test]
        public void NintendoPositionellIstOstSuedNordWest()
        {
            Assert.AreEqual(FacePosition.East, FaceLayoutMap.Position(FaceLayout.NintendoPositional, GameButton.A));
            Assert.AreEqual(FacePosition.South, FaceLayoutMap.Position(FaceLayout.NintendoPositional, GameButton.B));
            Assert.AreEqual(FacePosition.North, FaceLayoutMap.Position(FaceLayout.NintendoPositional, GameButton.X));
            Assert.AreEqual(FacePosition.West, FaceLayoutMap.Position(FaceLayout.NintendoPositional, GameButton.Y));
        }

        [Test]
        public void SuedBestaetigenTauschtAbUndXy()
        {
            Assert.AreEqual(FacePosition.South, FaceLayoutMap.Position(FaceLayout.SouthConfirm, GameButton.A));
            Assert.AreEqual(FacePosition.East, FaceLayoutMap.Position(FaceLayout.SouthConfirm, GameButton.B));
            Assert.AreEqual(FacePosition.West, FaceLayoutMap.Position(FaceLayout.SouthConfirm, GameButton.X));
            Assert.AreEqual(FacePosition.North, FaceLayoutMap.Position(FaceLayout.SouthConfirm, GameButton.Y));
        }

        [Test]
        public void JedeBelegungIstEineBijektion()
        {
            foreach (FaceLayout layout in Enum.GetValues(typeof(FaceLayout)))
            {
                var positions = Enumerable.Range(0, 4).Select(i => FaceLayoutMap.Position(layout, (GameButton)i)).ToArray();
                Assert.AreEqual(4, positions.Distinct().Count(), layout.ToString());
                foreach (FacePosition p in Enum.GetValues(typeof(FacePosition)))
                    Assert.AreEqual(p, FaceLayoutMap.Position(layout, FaceLayoutMap.Button(layout, p)));
            }
        }

        [Test]
        public void GamepadPfadeUndFehlerfaelle()
        {
            Assert.AreEqual("<Gamepad>/buttonEast", FaceLayoutMap.GamepadPath(FaceLayout.NintendoPositional, GameButton.A));
            Assert.AreEqual("<Gamepad>/buttonSouth", FaceLayoutMap.GamepadPath(FaceLayout.SouthConfirm, GameButton.A));
            Assert.Throws<ArgumentException>(() => FaceLayoutMap.Position(FaceLayout.NintendoPositional, GameButton.L));
            Assert.IsTrue(GameButtons.IsFace(GameButton.Y));
            Assert.IsFalse(GameButtons.IsFace(GameButton.L));
        }
    }

    public class InputOverlayStateTests
    {
        [Test]
        public void OhneGamepadSichtbarMitTouchscreen()
        {
            var m = new TouchOverlayStateMachine();
            m.Initialize(TouchOverlayMode.Auto, touchAvailable: true, gamepadCount: 0);
            Assert.IsTrue(m.Visible);
        }

        [Test]
        public void OhneTouchscreenBleibtAutoVerborgen()
        {
            var m = new TouchOverlayStateMachine();
            m.Initialize(TouchOverlayMode.Auto, touchAvailable: false, gamepadCount: 0);
            Assert.IsFalse(m.Visible);
            m.Tick(5f);
            Assert.IsFalse(m.Visible);
        }

        [Test]
        public void VerbindenBlendetSofortAus()
        {
            var m = new TouchOverlayStateMachine();
            m.Initialize(TouchOverlayMode.Auto, true, 0);
            m.GamepadCount = 1;
            Assert.IsFalse(m.Visible);
        }

        [Test]
        public void TrennenBlendetNachVerzoegerungEin()
        {
            var m = new TouchOverlayStateMachine(0.5f);
            m.Initialize(TouchOverlayMode.Auto, true, 1);
            Assert.IsFalse(m.Visible);
            m.GamepadCount = 0;
            m.Tick(0.3f);
            Assert.IsFalse(m.Visible);
            m.Tick(0.3f);
            Assert.IsTrue(m.Visible);
        }

        [Test]
        public void KurzesTrennenLaesstDasOverlayNichtAufblitzen()
        {
            var m = new TouchOverlayStateMachine(0.5f);
            m.Initialize(TouchOverlayMode.Auto, true, 1);
            m.GamepadCount = 0;
            m.Tick(0.3f);
            m.GamepadCount = 1; // wieder da, bevor die Verzögerung abgelaufen ist
            m.Tick(0.3f);
            m.GamepadCount = 0;
            m.Tick(0.3f); // Verzögerung beginnt von vorn
            Assert.IsFalse(m.Visible);
        }

        [Test]
        public void MehrereGamepadsZaehlenErstBeimLetztenTrennen()
        {
            var m = new TouchOverlayStateMachine(0f);
            m.Initialize(TouchOverlayMode.Auto, true, 2);
            m.GamepadCount = 1;
            m.Tick(1f);
            Assert.IsFalse(m.Visible);
            m.GamepadCount = 0;
            m.Tick(0f);
            Assert.IsTrue(m.Visible);
        }

        [Test]
        public void FesteModiIgnorierenGamepad()
        {
            var m = new TouchOverlayStateMachine();
            m.Initialize(TouchOverlayMode.AlwaysVisible, false, 3);
            Assert.IsTrue(m.Visible);
            m.Mode = TouchOverlayMode.AlwaysHidden;
            Assert.IsFalse(m.Visible);
            m.Mode = TouchOverlayMode.AlwaysVisible;
            Assert.IsTrue(m.Visible, "fester Modus blendet ohne Verzögerung ein");
        }

        [Test]
        public void EreignisNurBeiAenderung()
        {
            var m = new TouchOverlayStateMachine(0f);
            var events = 0;
            var last = false;
            m.VisibilityChanged += v => { events++; last = v; };
            m.Initialize(TouchOverlayMode.Auto, true, 0);
            Assert.AreEqual(1, events);
            m.Tick(1f);
            m.GamepadCount = 0;
            Assert.AreEqual(1, events);
            m.GamepadCount = 1;
            Assert.AreEqual(2, events);
            Assert.IsFalse(last);
        }

        [Test]
        public void NegativeWerteWerdenAbgefangen()
        {
            var m = new TouchOverlayStateMachine();
            Assert.Throws<ArgumentOutOfRangeException>(() => new TouchOverlayStateMachine(-1f));
            m.Initialize(TouchOverlayMode.Auto, true, -5);
            Assert.IsTrue(m.Visible);
            m.Tick(-1f);
            Assert.IsTrue(m.Visible);
        }
    }

    public class InputAssetTests
    {
        [Test]
        public void AssetEnthaeltAlleAktionen()
        {
            var asset = GameInputAssetFactory.Create(FaceLayout.NintendoPositional);
            try
            {
                var map = asset.FindActionMap(GameInputAssetFactory.MapName, true);
                Assert.IsNotNull(map.FindAction("Move"));
                Assert.IsNotNull(map.FindAction("Look"));
                for (var b = GameButton.A; b <= GameButton.DpadRight; b++)
                    Assert.IsNotNull(map.FindAction(b.ToString()), b.ToString());
                Assert.AreEqual(2 + GameButtons.Count, map.actions.Count);
                Assert.AreEqual(3, asset.controlSchemes.Count);
            }
            finally { UnityEngine.Object.DestroyImmediate(asset); }
        }

        [Test]
        public void GamepadBindungFolgtDerBelegung()
        {
            foreach (FaceLayout layout in Enum.GetValues(typeof(FaceLayout)))
            {
                var asset = GameInputAssetFactory.Create(layout);
                try
                {
                    var map = asset.FindActionMap(GameInputAssetFactory.MapName, true);
                    for (var b = GameButton.A; b <= GameButton.Y; b++)
                    {
                        var path = map.FindAction(b.ToString()).bindings
                            .First(x => x.groups == GameInputAssetFactory.SchemeGamepad).path;
                        Assert.AreEqual(FaceLayoutMap.GamepadPath(layout, b), path, layout + "/" + b);
                    }
                }
                finally { UnityEngine.Object.DestroyImmediate(asset); }
            }
        }

        [Test]
        public void SchultertastenUndMenuTastenSindFest()
        {
            var asset = GameInputAssetFactory.Create(FaceLayout.SouthConfirm);
            try
            {
                string Pad(GameButton b) => asset.FindAction("Game/" + b).bindings
                    .First(x => x.groups == GameInputAssetFactory.SchemeGamepad).path;
                Assert.AreEqual("<Gamepad>/leftShoulder", Pad(GameButton.L));
                Assert.AreEqual("<Gamepad>/rightTrigger", Pad(GameButton.ZR));
                Assert.AreEqual("<Gamepad>/start", Pad(GameButton.Plus));
                Assert.AreEqual("<Gamepad>/select", Pad(GameButton.Minus));
                Assert.AreEqual("<Gamepad>/rightStickPress", Pad(GameButton.StickR));
            }
            finally { UnityEngine.Object.DestroyImmediate(asset); }
        }

        [Test]
        public void TouchBindungenZeigenNichtAufGamepad()
        {
            var asset = GameInputAssetFactory.Create(FaceLayout.NintendoPositional);
            try
            {
                foreach (var action in asset.FindActionMap(GameInputAssetFactory.MapName, true).actions)
                    foreach (var binding in action.bindings.Where(x => x.groups == GameInputAssetFactory.SchemeTouch))
                        StringAssert.StartsWith("<XnuTouchPad>/", binding.path);
                Assert.IsNull(XnuTouchPad.ButtonPath(GameButton.StickL));
            }
            finally { UnityEngine.Object.DestroyImmediate(asset); }
        }
    }
}
