# Input (Controller, Keyboard, Touch)

Status: 2026-10-18, Todo `ap-input`. Implemented in `unity/Assets/Scripts/Input` (assembly `Xnu.Input`, depends only on `Xnu.Core`, `Unity.InputSystem`, and `UnityEngine.UI`). Nothing has yet been checked on physical hardware; see “Hardware Verification.”

## Structure
- `Logic/` contains pure C# logic with no UnityEngine dependency and is covered by EditMode tests (`Assets/Tests/EditMode/InputTests.cs`): dead zone and stick normalization (`StickMath`), 8-/4-direction quantization with hysteresis (`Direction8Quantizer`), face-button mapping (`FaceLayoutMap`), touch-overlay visibility (`TouchOverlayStateMachine`).
- `Runtime/GameInputAssetFactory` builds the `InputActionAsset` in code. There is no binary asset file; bindings are text in the C# file and visible in diffs. If needed, `asset.ToJson()` produces a `.inputactions` representation.
- `Runtime/GameInput` is the only interface game code should read (singleton `GameInput.Instance`, execution order −100).
- `Runtime/TouchOverlay` builds the touch UI at runtime (uGUI, no sprites/fonts from game data). `Runtime/InputDebugView` shows devices, axes, and buttons for hardware tests.
- Test scene: `Assets/Scenes/InputTest.unity` (camera, `DisplayController`, `GameInput`, `TouchOverlay` in “always visible” mode, diagnostic display). It is not included in Build Settings.

## Actions
| Action | Type | Notes |
|---|---|---|
| `Move` | Vector2 | left stick, D-pad, WASD/arrow keys, touch stick |
| `Look` | Vector2 | right stick, T/F/G/H, mouse delta while right button is held |
| `A`, `B`, `X`, `Y` | Button | functions as on Switch, not physical positions |
| `L`, `R`, `ZL`, `ZR` | Button | shoulder buttons and triggers (ZL/ZR are digital) |
| `Plus`, `Minus` | Button | Start/Menu and Select/Share |
| `StickL`, `StickR` | Button | stick click (gamepad and keyboard only, not touch) |
| `DpadUp/Down/Left/Right` | Button | individually queryable, also included in `Move` |

`GameInput` provides `Move` and `Look` after dead-zone processing (default inner 0.15, outer 0.95, circular, then rescaled to 0..1), plus `MoveDirection` as an 8-direction value for grid movement and `IsPressed/WasPressedThisFrame/WasReleasedThisFrame` for each button.

## Bindings
**Gamepad** (any Input System `Gamepad`): `Move` = left stick and D-pad, `Look` = right stick, `L/R` = shoulder buttons, `ZL/ZR` = triggers, `Plus` = `start`, `Minus` = `select`, stick clicks = `leftStickPress/rightStickPress`. A/B/X/Y are described below.

**Keyboard/mouse (Mac):** the right hand rests as a diamond on I/J/K/L, matching the positions of the Switch buttons.

| Function | Key |
|---|---|
| Move | W/A/S/D and arrow keys |
| Look | T/F/G/H, mouse while right button is held |
| A | L, Return, Space |
| B | K, Backspace |
| X / Y | I / J |
| L / R | Q / E |
| ZL / ZR | 1 / 3 |
| Plus / Minus | Tab / M |
| StickL / StickR | V / B |
| D-pad | arrow keys |

Mouse clicks are intentionally unbound so they do not overlap with touch overlay pointer input in the UI.

**Touch:** `OnScreenStick` and `OnScreenButton` write to the custom virtual device `XnuTouchPad`. It is deliberately not a `Gamepad`: with a Gamepad path, the Input System creates a virtual gamepad that appears in `Gamepad.all` and would falsify “controller connected” detection. Additionally, `GameInput.ConnectedGamepadCount()` counts only devices reported by the system itself (`native`).

## Face-Button Layout Decision (A/B/X/Y)
The Input System names face buttons by position (`buttonSouth/East/West/North`), not by their printed labels. The same position has different labels from one manufacturer to another:

| Position | Xbox | PlayStation | Nintendo |
|---|---|---|---|
| South (bottom) | A | Cross | B |
| East (right) | B | Circle | A |
| West (left) | X | Square | Y |
| North (top) | Y | Triangle | X |

Default is `FaceLayout.NintendoPositional`: A = East, B = South, X = North, Y = West. This matches the labels and functions on Switch Pro controllers and Joy-Con, and makes the game feel like the original. On Xbox, “A” (confirm) is therefore the B button; on PlayStation it is Circle. This follows the same muscle-memory logic as on Switch.

Alternative `FaceLayout.SouthConfirm` (A = South, B = East, X = West, Y = North) puts Confirm on the bottom button, as Xbox and PlayStation users expect. Switch with `GameInput.Instance.FaceLayout = ...`; the asset is rebuilt. F2 toggles the mapping in the test scene. A settings page and persistence for this choice are still missing.

The positional mapping is supported by the Input System package source (1.20.0): `SwitchProControllerHID` (macOS/Windows) and `SwitchProControlleriOS` (iOS/iPadOS) map East to A and South to B. On iPadOS, the Switch Pro mapping uses its own state structure with swapped face buttons so that “East” remains A there too.

## Controller Switching
- The touch overlay is visible when a touchscreen is available (iPad, iPhone, or `Touchscreen.current`) and no real gamepad is connected.
- Connecting a controller hides the overlay immediately, even if multiple controllers are connected; it appears again only after the last one disconnects.
- After disconnection, the overlay appears after 0.75 s to avoid flickering on brief Bluetooth dropouts.
- Modes: `Auto` (rule above), `AlwaysVisible`, `AlwaysHidden`. On a Mac without touchscreen, `Auto` stays hidden; set `AlwaysVisible` or enable `AssumeTouchscreen` for testing.
- Keyboard and gamepad work in parallel. In Unity tool simulation (`simulate_key`/`simulate_pointer`), action `A` once remained “stuck” when keyboard and touch were pressed/released with overlapping timing; direct calls to OnScreen components and state events behaved correctly. Probably a tool artifact; verify on hardware.

## Touch UI
- ZL/L at upper left, R/ZR at upper right, Minus/Plus at top center; touch stick on left (relative to touch point, radius 110 units) with D-pad over it; A/B/X/Y diamond on right (A right, B bottom, X top, Y left, Nintendo layout).
- Canvas is 1080 units high (width follows screen, 16:9 through 4:3); buttons are 120–240 units, about 15–25 mm on a 12.9-inch iPad Pro.
- Overlay covers the full screen, not the 16:9 area of `DisplayController`; at 4:3 the top buttons land in the black bars. Container respects `Screen.safeArea`.
- Multitouch comes from the Input System UI module (`InputSystemUIInputModule`, added as needed).
- Evidence (not in repository): `work/input/inputtest_16x9_1920x1080.png`, `work/input/inputtest_4x3_2048x1536.png`.

## Open Items
- Rumble/haptics (`Gamepad.SetMotorSpeeds`, Apple Core Haptics) not connected.
- Gyro/motion sensors on Switch controllers not connected.
- No rebinding UI; layout choice and dead zones are not saved yet.
- Touch: D-pad buttons trigger only on direct tap (sliding across does not change direction); no right touch stick or stick clicks; camera (`Look`) cannot be controlled by touch.
- Touch overlay face-button labels never change (always Nintendo letters).
- Mac: the Input System package connects controllers via HID on macOS (Xbox, DualShock/DualSense, Switch Pro), not Apple's GameController framework; package's Apple GameController binding (`IOSGameController`) exists only for iOS/iPadOS/tvOS. MFi controllers on macOS are therefore unresolved.

## Hardware Verification
Everything below is assumed from source and test simulation, not measured:
1. **Switch Pro on iPad** (Bluetooth): does it appear as `SwitchProControlleriOS`? Do A/B/X/Y labels, Plus/Minus, stick clicks, ZL/ZR (digital), and D-pad match? Test scene diagnostics show layout name.
2. **Switch Pro on Mac** (Bluetooth or USB): detected as `SwitchProControllerHID`, same buttons as above. Check whether macOS gives the game exclusive access to the controller.
3. **Joy-Con** separately and paired on iPad and Mac: package has no dedicated layout; whether/how they appear is unknown.
4. **Xbox and PlayStation controllers** on both devices: South/East as in table, `Plus`/`Minus` on Menu/View or Options/Share, trigger threshold for ZL/ZR.
5. **MFi controller** on iPad.
6. Connect/disconnect while running: overlay hides immediately and returns after 0.75 s; no stuck buttons.
7. Touch on iPad: multitouch (stick plus buttons), safe area (home indicator), button accuracy.
8. In the Editor, the game view receives keyboard and pointer input only when focused; test controllers in a player build if possible.
