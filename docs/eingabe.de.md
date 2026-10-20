# Eingabe (Controller, Tastatur, Touch)

Stand: 2026-10-18, Todo `ap-input`. Umgesetzt in `unity/Assets/Scripts/Input` (Assembly `Xnu.Input`, hängt nur an `Xnu.Core`, `Unity.InputSystem` und `UnityEngine.UI`). Auf echter Hardware ist noch nichts geprüft, siehe Abschnitt „Auf Hardware prüfen“.

## Aufbau
- `Logic/` enthält reine C#-Logik ohne UnityEngine-Bezug und ist per EditMode-Test abgedeckt (`Assets/Tests/EditMode/InputTests.cs`): Totzone und Stick-Normalisierung (`StickMath`), 8-/4-Richtungs-Quantisierung mit Hysterese (`Direction8Quantizer`), Belegung der Gesichtstasten (`FaceLayoutMap`), Sichtbarkeit des Touch-Overlays (`TouchOverlayStateMachine`).
- `Runtime/GameInputAssetFactory` baut das `InputActionAsset` im Code. Es gibt keine binäre Asset-Datei; die Bindungen stehen als Text in der C#-Datei und sind im Diff lesbar. Bei Bedarf liefert `asset.ToJson()` ein `.inputactions`-Abbild.
- `Runtime/GameInput` ist die einzige Stelle, die Spielcode lesen soll (Singleton `GameInput.Instance`, Ausführungsreihenfolge −100).
- `Runtime/TouchOverlay` baut die Touch-Oberfläche zur Laufzeit (uGUI, ohne Sprites/Schriften aus Spieldaten). `Runtime/InputDebugView` zeigt Geräte, Achsen und Tasten für Hardwaretests.
- Testszene: `Assets/Scenes/InputTest.unity` (Kamera, `DisplayController`, `GameInput`, `TouchOverlay` im Modus „immer sichtbar“, Diagnoseanzeige). Sie ist nicht in den Build Settings eingetragen.

## Aktionen
| Aktion | Typ | Hinweis |
|---|---|---|
| `Move` | Vector2 | linker Stick, D-Pad, WASD/Pfeiltasten, Touch-Stick |
| `Look` | Vector2 | rechter Stick, T/F/G/H, Maus-Delta bei gedrückter rechter Taste |
| `A`, `B`, `X`, `Y` | Button | Funktionen wie auf der Switch, nicht Positionen |
| `L`, `R`, `ZL`, `ZR` | Button | Schultertasten und Trigger (ZL/ZR sind digital) |
| `Plus`, `Minus` | Button | Start/Menü und Select/Teilen |
| `StickL`, `StickR` | Button | Stick-Klick (nur Gamepad und Tastatur, nicht Touch) |
| `DpadUp/Down/Left/Right` | Button | einzeln abfragbar, zusätzlich in `Move` enthalten |

`GameInput` liefert `Move` und `Look` nach Totzone (Standard innen 0,15, außen 0,95, kreisförmig, danach auf 0..1 umskaliert), außerdem `MoveDirection` als 8-Richtungs-Wert für Gitterbewegung und `IsPressed/WasPressedThisFrame/WasReleasedThisFrame` je Taste.

## Bindungen
**Gamepad** (jedes `Gamepad` des Input Systems): `Move` = linker Stick und D-Pad, `Look` = rechter Stick, `L/R` = Schultertasten, `ZL/ZR` = Trigger, `Plus` = `start`, `Minus` = `select`, Stick-Klicks = `leftStickPress/rightStickPress`. A/B/X/Y siehe nächster Abschnitt.

**Tastatur/Maus (Mac)**: Die rechte Hand liegt als Diamant auf I/J/K/L, passend zur Position der Switch-Tasten.

| Funktion | Taste |
|---|---|
| Move | W/A/S/D und Pfeiltasten |
| Look | T/F/G/H, Maus bei gedrückter rechter Taste |
| A | L, Return, Leertaste |
| B | K, Rücktaste |
| X / Y | I / J |
| L / R | Q / E |
| ZL / ZR | 1 / 3 |
| Plus / Minus | Tab / M |
| StickL / StickR | V / B |
| D-Pad | Pfeiltasten |

Mausklicks sind bewusst nicht belegt, damit sie nicht doppelt mit dem Touch-Overlay (Zeiger-Eingabe in der UI) wirken.

**Touch**: `OnScreenStick` und `OnScreenButton` schreiben in das eigene virtuelle Gerät `XnuTouchPad`. Es ist absichtlich kein `Gamepad`: Mit einem Gamepad-Pfad legt das Input System ein virtuelles Gamepad an, das in `Gamepad.all` auftaucht und die Erkennung „Controller verbunden“ verfälschen würde. Zusätzlich zählt `GameInput.ConnectedGamepadCount()` nur Geräte, die das System selbst gemeldet hat (`native`).

## Layout-Entscheidung (A/B/X/Y)
Das Input System benennt Gesichtstasten nach der Position (`buttonSouth/East/West/North`), nicht nach der Aufschrift. Dieselbe Position trägt je Hersteller andere Beschriftungen:

| Position | Xbox | PlayStation | Nintendo |
|---|---|---|---|
| Süd (unten) | A | Kreuz | B |
| Ost (rechts) | B | Kreis | A |
| West (links) | X | Quadrat | Y |
| Nord (oben) | Y | Dreieck | X |

Standard ist `FaceLayout.NintendoPositional`: A = Ost, B = Süd, X = Nord, Y = West. Damit stimmen Aufschrift und Funktion auf Switch-Pro-Controller und Joy-Con, und das Spiel fühlt sich wie das Original an. Auf Xbox liegt „A“ (Bestätigen) dann auf der B-Taste, auf PlayStation auf dem Kreis; das ist die gleiche Muskelgedächtnis-Logik wie auf der Switch.

Die Alternative `FaceLayout.SouthConfirm` (A = Süd, B = Ost, X = West, Y = Nord) legt Bestätigen auf die untere Taste, wie es Xbox- und PlayStation-Nutzer gewohnt sind. Umschalten: `GameInput.Instance.FaceLayout = ...`; das Asset wird dabei neu aufgebaut. In der Testszene wechselt F2 die Belegung. Eine Einstellungsseite und das Speichern der Wahl fehlen noch.

Dass die Position und nicht die Aufschrift zählt, ist durch den Quelltext des Input-System-Pakets (1.20.0) gestützt: `SwitchProControllerHID` (macOS/Windows) und `SwitchProControlleriOS` (iOS/iPadOS) belegen Ost mit A und Süd mit B. Die Switch-Pro-Belegung unter iPadOS wird über eine eigene Zustandsstruktur mit vertauschten Gesichtstasten abgebildet, damit „Ost“ auch dort A bleibt.

## Controller-Wechsel
- Das Touch-Overlay ist sichtbar, wenn ein Touchscreen vorhanden ist (iPad, iPhone oder `Touchscreen.current`) und kein echtes Gamepad verbunden ist.
- Verbinden blendet das Overlay sofort aus, auch wenn mehrere Controller da sind; erst nach dem Trennen des letzten wird eingeblendet.
- Nach dem Trennen wird das Overlay erst nach 0,75 s eingeblendet, damit kurze Bluetooth-Aussetzer es nicht aufblitzen lassen.
- Modi: `Auto` (obige Regel), `AlwaysVisible`, `AlwaysHidden`. Auf einem Mac ohne Touchscreen bleibt `Auto` ausgeblendet; zum Testen `AlwaysVisible` setzen oder `AssumeTouchscreen` aktivieren.
- Tastatur und Gamepad funktionieren parallel. Bei der Simulation über das Unity-Werkzeug (`simulate_key`/`simulate_pointer`) blieb die Aktion `A` einmal „hängen“, als Tastatur und Touch überlappend gedrückt und losgelassen wurden; direkte Aufrufe der OnScreen-Komponenten und Zustandsereignisse verhielten sich korrekt. Vermutlich ein Artefakt des Werkzeugs, auf Hardware gegenprüfen.

## Touch-Oberfläche
- Links oben ZL/L, rechts oben R/ZR, Mitte oben Minus/Plus; links Touch-Stick (relativ zum Berührungspunkt, Radius 110 Einheiten) mit D-Pad darüber; rechts A/B/X/Y als Raute (A rechts, B unten, X oben, Y links, wie bei Nintendo).
- Zeichenfläche 1080 Einheiten hoch (Breite folgt dem Bildschirm, 16:9 wie 4:3); Knöpfe sind 120–240 Einheiten groß, auf einem iPad Pro 12,9" etwa 15–25 mm.
- Das Overlay liegt auf dem vollen Bildschirm, nicht im 16:9-Ausschnitt des `DisplayController`; bei 4:3 landen die oberen Tasten in den schwarzen Balken. Der Container richtet sich nach `Screen.safeArea`.
- Mehrfingerbedienung kommt vom UI-Eingabemodul des Input Systems (`InputSystemUIInputModule`, wird bei Bedarf angelegt).
- Belege (nicht im Repo): `work/input/inputtest_16x9_1920x1080.png`, `work/input/inputtest_4x3_2048x1536.png`.

## Offene Punkte
- Rumble/Haptik (`Gamepad.SetMotorSpeeds`, Apple Core Haptics) nicht angebunden.
- Gyro/Bewegungssensoren der Switch-Controller nicht angebunden.
- Keine Rebinding-Oberfläche; Layout-Wahl und Totzonen werden noch nicht gespeichert.
- Touch: D-Pad-Tasten lösen nur beim direkten Antippen aus (Darübergleiten wechselt die Richtung nicht); kein rechter Touch-Stick, keine Stick-Klicks; Kamera (`Look`) ist per Touch nicht bedienbar.
- Kein Wechsel der Gesichtstasten-Beschriftung im Touch-Overlay (immer Nintendo-Buchstaben).
- Mac: Das Input-System-Paket bindet unter macOS Controller über HID an (Xbox, DualShock/DualSense, Switch Pro), nicht über das Apple-GameController-Framework; die Apple-GameController-Anbindung (`IOSGameController`) gibt es im Paket nur für iOS/iPadOS/tvOS. MFi-Controller unter macOS sind deshalb ungeklärt.

## Auf Hardware prüfen
Alles Folgende ist Annahme aus dem Quelltext und der Test-Simulation, nicht gemessen:
1. **Switch Pro am iPad** (Bluetooth): Erscheint das Gerät als `SwitchProControlleriOS`? Stimmen A/B/X/Y mit der Aufschrift, Plus/Minus, Stick-Klicks, ZL/ZR (digital), D-Pad? In der Testszene zeigt die Diagnoseanzeige den Layoutnamen.
2. **Switch Pro am Mac** (Bluetooth oder USB): Erkennung als `SwitchProControllerHID`, gleiche Tasten wie oben. Prüfen, ob macOS den Controller dem Spiel überhaupt exklusiv gibt.
3. **Joy-Con** einzeln und als Paar an iPad und Mac: Das Paket enthält dafür kein eigenes Layout; es ist offen, ob und wie sie erscheinen.
4. **Xbox- und PlayStation-Controller** an beiden Geräten: Süd/Ost wie in der Tabelle, `Plus`/`Minus` auf Menü/Ansicht beziehungsweise Optionen/Teilen, Trigger-Schwelle für ZL/ZR.
5. **MFi-Controller** am iPad.
6. Anschluss/Trennen im laufenden Betrieb: Overlay blendet sofort aus und nach 0,75 s wieder ein; keine hängenden Tasten.
7. Touch am iPad: Mehrfingerbedienung (Stick plus Tasten), Safe Area (Home-Indikator), Treffsicherheit der Knöpfe.
8. Im Editor erhält die Spielansicht Tastatur- und Zeigereingaben nur mit Fokus; Controller-Tests am besten im Player.
