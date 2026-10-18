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

## Erster Build (macOS, 2026-10-18)
- Module `ios` (471 MB) und `mac-il2cpp` (713 MB) per `unity install-modules -e 6000.3.26f1 -a arm64 -m ios mac-il2cpp --non-interactive` installiert (ohne `--accept-eula`).
- Leerer Test-Build `StandaloneOSX` mit IL2CPP über das MCP-Tool `build` (der offene Editor hält das Projekt, daher kein Batch-Build): **Succeeded**, 134 s, 0 Fehler, 1 Warnung. Das Binary ist **universell (arm64 + x86_64)**, ca. 132 MB App.
- Start der App: Engine 6000.3.26f1, Metal-Gerät Apple M1 Pro, läuft stabil.
- Xcode 26.0.1 liegt in `/Applications/Xcode.app`, das iPhoneOS-26.0-SDK wird mit `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer` gefunden. `xcode-select` zeigt weiter auf die Command Line Tools (Umstellen braucht Admin).
- iOS: Apple-ID (kostenloses Team) muss noch in Xcode hinzugefügt werden (`security find-identity -v -p codesigning` zeigt bisher 0 Identitäten). Ohne bezahltes Team: Profil 7 Tage, kein `.ipa` für andere; ob der Entitlement „Increased Memory Limit“ verfügbar ist, ist offen.

## Erster iOS/iPadOS-Build (2026-10-18)
- Leerer iOS-Build (IL2CPP, Xcode-Projekt) über das MCP-Tool `build`: **Succeeded**, 24,5 s, 0 Fehler. Das Projekt ist auf „Automatically manage signing“ gestellt.
- In Xcode 26 gebaut, signiert und auf ein **iPad Pro 12,9" (6. Generation, M2, iPadOS 26.4.2)** installiert, mit kostenlosem Team. `devicectl` listet die App (`xnu-m0`). Entwicklermodus aktiv, Entwicklerprofil am Gerät vertraut.
- Bauwarnungen (Unity-generierter Code, ignorierbar): veraltete lproj-Ordner, „Update to recommended settings“, deprecated APIs (`useCVTextureCache`, `SecTrustGetCertificateAtIndex`, Sensoren, `controllerPausedHandler`). Das Xcode-Projekt wird bei jedem Unity-Build neu erzeugt, Änderungen daran gehen verloren.
- Signaturablauf: Xcode legt das Zertifikat selbst an (Apple Development, Schlüsselbund). `security find-identity -v -p codesigning` zeigt danach 1 gültige Identität. Der Zugriff von `codesign` auf den Schlüssel wurde freigegeben. Die Team-ID gehört nicht ins Repo.
- Wiederholung per CLI (Idee, ungetestet): `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild -project Unity-iPhone.xcodeproj -scheme Unity-iPhone -destination 'id=<UDID>' -allowProvisioningUpdates` und `xcrun devicectl device install app`. 
