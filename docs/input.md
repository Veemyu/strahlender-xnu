# On-screen keyboard (text entry)

Updated: 2026-10-24. When the game asks for text (player name, rival name, nicknames, codes) it calls the system's software keyboard,
a library applet. This project answers that call with its own keyboard, drawn from the keyboard layout files of the Switch **firmware you
provide**; the repository contains none of those files. Without them, text is answered automatically (see below).

## What you need

- The firmware's keyboard applet data, as a folder with `swkbd/lyt/*.szs` (Qwerty, Sign, Numeric, 50on, Swkbd, common).
  Point `BDSP_FIRMWARE_DATA` at the folder that contains `swkbd/`. The text check of the game (NG words) additionally uses
  `0100000000000823.romfs` from the same folder; without it the check is skipped.
- A normal (not scripted) run on macOS. iOS/iPadOS is not connected yet.

## Using it (macOS)

- Typing: the keyboard of the Mac; Backspace/Delete, Left/Right/Home/End move and delete in the text, Return confirms, Esc cancels.
- Mouse: click a key.
- Controller: D-pad or left stick moves the focus, A presses the key, B deletes, X cancels, Y inserts a space, L/R move the caret,
  left stick click toggles Shift, Plus confirms.
- While the keyboard is open the game sees no input.
- The game stops inside the keyboard call; the window keeps showing the last game image behind the keyboard.

Key characters follow the standard national layouts (US, UK, DE, FR, ES, IT, PT, RU). Choose one with `BDSP_SWKBD_LAYOUT=us|uk|de|fr|es|it|pt|ru`
(default `us`); `BDSP_SWKBD_LANG` selects the language of the button labels (default `USen`).

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
