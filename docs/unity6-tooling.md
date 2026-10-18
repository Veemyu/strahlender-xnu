# Unity 6.3 LTS: Werkzeuge und Testergebnis (Stand 2026-10-18)

## Installation
- Unity Hub per `brew install --cask unity-hub`. Editor per Hub-CLI: `Unity Hub -- --headless install --version 6000.3.26f1 --architecture arm64` (Hub-GUI zeigt dabei ein Login-Fenster, der CLI-Download braucht es nicht).
- Der Editor ist ein **Arm64-Binary**. Per `eval` bestätigt: `Metal | Apple M1 Pro | 6000.3.26f1 | Arm64 | macOS 26.6.2`.
- Unity 2019.4.27f1 (Referenz zum Original) bleibt als Intel-Editor unter Rosetta installiert.

## CLI und MCP
- `unity` CLI 1.0.0-beta.13, angemeldet per OAuth (Schlüsselbund). Projekt anlegen: `unity projects new <name> --path <dir> --editor-version 6000.3.26f1 --architecture arm64 --template com.unity.template.3d`. Das lief im **Batchmodus mit der CLI-Anmeldung** (bei 2019.4 scheiterte die Lizenz).
- Editor steuern erfordert das Paket `com.unity.pipeline` (Unity 6.0+): `unity pipeline install` im Projekt (0.8.0-exp.1), dann `unity open .` und `unity status --until-ready`.
- MCP-Server `unity` für Copilot CLI per `unity mcp configure copilot-cli` eingetragen (Backup `~/.copilot/mcp-config.json.pre-unity.backup`). Tools u. a.: `editor_play`, `eval`, `capture_game_view`, `console`, `create_gameobject`, `get_graphics_settings`, Build- und Test-Befehle.
- Test (Projekt `work/unity6-test`): Play, Screenshot, Eval (Frame-Zähler läuft), Stop funktionieren. `create_gameobject` lieferte einmal `Network error` (Ursache offen).

## Offen für iOS/iPadOS
- iOS-Build-Support-Modul in Unity noch nicht installiert.
- `xcode-select` zeigt auf die Command Line Tools, das iPhoneOS-SDK wird nicht gefunden (Xcode.app ist vorhanden).
