# On-screen keyboard (text entry)

Updated: 2026-10-24. When the game asks for text (player name, rival name, nicknames, codes) it calls the system's software keyboard,
a library applet. This project answers that call with its own keyboard, drawn from the keyboard layout files of the Switch **firmware you
provide**; the repository contains none of those files. Without them macOS/Linux use a simple independent keyboard. iOS/iPadOS instead show only the prompt, a native editable field and the
blurred game while UIKit handles text input. Complete readable Horizon layouts plus valid text and button-glyph fonts select Horizon
exclusively on iOS; UIKit's keyboard is never opened over it. Both need a normal, not scripted, run (see below).

## What you need

- The firmware's keyboard applet data in one folder (`BDSP_FIRMWARE_DATA`):
  `swkbd/lyt/*.szs` (layouts and animations), `swkbd/message/<language>/swkbd.msbt.szs` (button labels),
  `fonts/nintendo_udsg-r_std_003.bfttf` and `fonts/nintendo_ext_003.bfttf` (text font and button glyphs; without them a Mac font is used),
  optionally the Korean and Chinese fonts `fonts/nintendo_udsg-r_ko_003.bfttf`, `nintendo_udsg-r_org_zh-cn_003.bfttf`, `nintendo_udjxh-db_zh-tw_003.bfttf` (characters the text font lacks, e.g. Hangul),
  `swkbd/sound/swkbd.bfsar` (the keyboard's sounds; without it the keyboard is silent),
  and `0100000000000823.romfs` (word list of the game's name check; without it the check is skipped).
  `scripts/swkbd_firmware_extract.py --nca-dir <registered NCAs> --keys <prod.keys> --hactool <hactool> --out <folder>` writes exactly this
  folder from your own firmware dump (it uses hactool and your keys locally and prints no key material).
  The GUI installer does not currently import or extract firmware. On iPhone/iPad, the app reads already extracted keyboard data from
  `Documents/Firmware`; without complete layouts/fonts, UIKit handles input. Firmware is optional and is not part of the game RomFS.
- A normal (not scripted) run on macOS or iPadOS. `BDSP_SWKBD_SIMPLE=1` forces the fallback even with firmware files (native input on iOS).
- iPadOS: the app reads the files from `Documents/Firmware` (same folder layout; copy it with the Files app or `devicectl`, without
  `--remove-existing-content`). Without complete layouts/fonts, only a prompt and native field appear above the iOS keyboard.

## Using it (macOS)

- Typing: the keyboard of the Mac; Backspace/Delete, Left/Right/Home/End move and delete in the text, Return confirms, Esc cancels.
- Mouse: click a key.
- Controller: D-pad or left stick moves the focus, A presses the key, B deletes, X cancels, Y inserts a space, L/R move the caret,
  left stick click toggles Shift, Plus confirms.
- iPadOS: touch a key, or the text field to bring up the system keyboard; a hardware keyboard types directly; a controller works like on the Mac.
  The touch gamepad is hidden while the keyboard is open.
- While the keyboard is open the game sees no input.
- The game stops inside the keyboard call; the window keeps showing the last game image behind the keyboard.

Key characters follow the standard national layouts (US, UK, DE, FR, ES, IT, PT, RU) and the tabs below the keys switch between letters,
symbols and two pages of accented letters. The label language follows the runtime's console language (`BDSP_LANG`, e.g. `de-DE`), or `BDSP_SWKBD_LANG` (e.g. `EUde`, default `USen`), and, unless
`BDSP_SWKBD_LAYOUT=us|uk|de|fr|es|it|pt|ru` says otherwise, the key layout. The globe key (bottom left) switches to the next
layout; the space bar shows its name, taken from the firmware's message file, for a moment. The globe cycles US, UK, DE, FR, ES, IT, PT, RU, Korean, Japanese romaji and the Japanese kana grid
(the 50 sound table). Korean keys are jamo that form syllables (final consonants, double vowels, backspace per jamo); romaji forms hiragana;
the kana grid has a hiragana / katakana toggle and the small-kana / dakuten key (left stick). There is no kanji or hanzi conversion
(that needs a dictionary), and Chinese keeps the US letters. The kana grid's column order and tab labels are our reading of the layout file,
not checked against a console. The colour scheme is light like the console's default;
`BDSP_SWKBD_THEME=dark` selects a dark one (the layout files do not contain the colours, both schemes are ours).

The keyboard plays the console's animations (layouts' own: focus, press, open, close, counter shake) and sounds (focus tick, key press,
backspace and repeat, shift / caps lock, length error, error when the focus cannot move). The game behind it is blurred once when the
keyboard opens and dimmed. `BDSP_SWKBD_SOUND=0` switches the sounds off.

## Memory and cost

Nothing of the keyboard is kept while it is closed: its layouts, textures, sounds, GPU textures, glyph atlas, fonts and the thread that repeats the
game picture are built when it opens and freed when it closes. While it is open the picture behind it is frozen, so the blur is made once per
opening and the repeated game image is not drawn under it; the keyboard is redrawn when something is entered or moves, otherwise only for the caret.
Text is drawn from one small glyph atlas (`swkbd_text.c`, the firmware's own fonts rasterized with stb_truetype in `third_party/`) instead of one
texture per string. `BDSP_SWKBD_STATS=1` logs the process and GPU memory and the number of blurs and frames; `BDSP_SWKBD_PREVIEW_CLOSE=<frame>` and
`BDSP_SWKBD_PREVIEW_AGAIN=<frame>` close and reopen the preview keyboard. `BDSP_SWKBD_ATLAS=0` draws the text with CoreText again (macOS, iPadOS).

## Scripted and test runs

A run with any of `BDSP_INPUT_SCRIPT`, `BDSP_KEY_SCRIPT`, `BDSP_SWKBD_TEXT`, `BDSP_SWKBD_AUTO` or `BDSP_NO_ALERT` does not open the keyboard;
the answer is automatic:

- `BDSP_SWKBD_TEXT=<text>` answers with that text (cut to the length limit, padded to the minimum).
- Otherwise the initial text of the prompt is used.
- With neither, the keyboard is **cancelled**: there is no built-in default name. Scripted runs that pass the naming prompts
  (for example the intro skip of the iPhone/iPad tests) must set `BDSP_SWKBD_TEXT`.

`BDSP_SWKBD_UI=1` opens the keyboard even in a scripted run. `BDSP_SWKBD_PREVIEW=<frame>` opens it at that frame without the game asking
(look and feel tests together with `BDSP_WINDOW_SHOT`). `BDSP_TRACE_APPLET=1` logs the applet protocol and the keyboard.

## Tests

- `scripts/recomp/rt-bdsp/test/run_lyt_test.sh`: readers for Yaz0, SARC, BFLYT, BFLAN, BNTX (synthetic part always; firmware part with `BDSP_FIRMWARE_DATA`).
- `scripts/recomp/rt-bdsp/test/run_swkbd_ui_test.sh`: keyboard logic and a software rendering to a PPM.
- `scripts/recomp/rt-bdsp/test/run_swkbd_text_test.sh`: glyph atlas text (measure, placement, atlas reuse and clearing; with `BDSP_FIRMWARE_DATA`, the firmware fonts).
- `scripts/recomp/rt-bdsp/test/run_swkbd_snd_test.sh`: reader of the sound archive (synthetic part always; firmware part with `BDSP_FIRMWARE_DATA`).

## Controllers (game input)

Plug in or pair over Bluetooth and it works; no driver, mapper or Steam Input is needed. All connected pads act as player 1 (BDSP is a
single-player game). The keyboard stays available next to the pad on every platform.

- **macOS, iPadOS:** `GameController.framework` only (Switch Pro, Joy-Con, DualShock, DualSense, Xbox, MFi). SDL's gamepad subsystem is
  not started on Apple platforms: it would open the same devices through HIDAPI and fight with Apple's own driver over them. Nintendo pads
  already name their buttons like the console and are used as they are; Xbox and PlayStation pads are mapped by position (A right, B bottom,
  X top, Y left). On the Mac `pad_layout = xbox` keeps the labels of those pads instead. The iPad hides the touch gamepad while a pad is
  connected.
- **Linux (and Windows, prepared):** SDL3's gamepad subsystem in its own thread (`pad_sdl.c`), independent of the window and of the UI
  toolkit (Qt or SDL). Nintendo pads need nothing on a desktop with the kernel driver `hid-nintendo`. If a Nintendo or Sony pad is connected
  but cannot be opened, the log says so once; `scripts/recomp/rt-bdsp/app/linux/udev/70-bdsp-controllers.rules` grants the logged-in user access
  (commands are in the file, root needed once).
- **Buttons:** A, B, X, Y by position; L/R; ZL/ZR as buttons (the game needs no analog trigger); both sticks (12 % dead zone) and their clicks;
  D-pad; Plus and Minus. Not implemented: motion, rumble, other players.
- **Keys** (Linux): Return/Space/K = A, Backspace/J = B, X, Y, Q/E = L/R, P = Plus, O = Minus, arrows and WASD = D-pad. The Mac has the
  Ryujinx default keys (see the app's help text).
- **Layers:** `input.h` is the neutral interface. Keyboard, touch and gamepads are separate sources (`input_source_set`); the game reads the merged
  state through `input_current`, which is empty while the on-screen keyboard is open.
- `BDSP_PAD_LOG=1` (Linux/Windows) prints connections and every change of buttons and sticks, with the button names.
- **Windows (prepared, not built or tested):** the controller layer needs no change, only the build target. `input.c` and `pad_sdl.c` use
  POSIX threads (`pthread_mutex`, `pthread_once`), so the Windows build is MinGW-w64 (winpthreads), not MSVC. SDL3's gamepad subsystem handles
  Switch Pro, Joy-Con, DualShock, DualSense and Xbox pads over USB or Bluetooth with its own drivers (HIDAPI, XInput); that it runs without a
  window on Windows, as it does on Linux, is not yet checked. The Linux-only part (the hidraw hint for the udev rules) is behind `#ifdef __linux__`.

