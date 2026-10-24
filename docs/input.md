# On-screen keyboard (text entry)

Updated: 2026-10-24. When the game asks for text (player name, rival name, nicknames, codes) it calls the system's software keyboard,
a library applet. This project answers that call with its own keyboard, drawn from the keyboard layout files of the Switch **firmware you
provide**; the repository contains none of those files. Without them the game still gets a simple keyboard of our own (same keys and
controls, plain colours and shapes, no Switch look). Both need a normal, not scripted, run (see below).

## What you need

- The firmware's keyboard applet data in one folder (`BDSP_FIRMWARE_DATA`):
  `swkbd/lyt/*.szs` (layouts and animations), `swkbd/message/<language>/swkbd.msbt.szs` (button labels),
  `fonts/nintendo_udsg-r_std_003.bfttf` and `fonts/nintendo_ext_003.bfttf` (text font and button glyphs; without them a Mac font is used),
  and `0100000000000823.romfs` (word list of the game's name check; without it the check is skipped).
  `scripts/swkbd_firmware_extract.py --nca-dir <registered NCAs> --keys <prod.keys> --hactool <hactool> --out <folder>` writes exactly this
  folder from your own firmware dump (it uses hactool and your keys locally and prints no key material).
- A normal (not scripted) run on macOS. iOS/iPadOS is not connected yet. `BDSP_SWKBD_SIMPLE=1` forces the simple keyboard even with firmware files.

## Using it (macOS)

- Typing: the keyboard of the Mac; Backspace/Delete, Left/Right/Home/End move and delete in the text, Return confirms, Esc cancels.
- Mouse: click a key.
- Controller: D-pad or left stick moves the focus, A presses the key, B deletes, X cancels, Y inserts a space, L/R move the caret,
  left stick click toggles Shift, Plus confirms.
- While the keyboard is open the game sees no input.
- The game stops inside the keyboard call; the window keeps showing the last game image behind the keyboard.

Key characters follow the standard national layouts (US, UK, DE, FR, ES, IT, PT, RU) and the tabs below the keys switch between letters,
symbols and two pages of accented letters. `BDSP_SWKBD_LANG` selects the language of the labels (default `USen`, e.g. `EUde`) and, unless
`BDSP_SWKBD_LAYOUT=us|uk|de|fr|es|it|pt|ru` says otherwise, the key layout. The colour scheme is light like the console's default;
`BDSP_SWKBD_THEME=dark` selects a dark one (the layout files do not contain the colours, both schemes are ours).

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
