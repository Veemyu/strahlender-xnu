# Unity im Autopilot: Dialoge und Hänger vermeiden

Stand: 2026-10-19. Wenn niemand am Rechner sitzt, blockiert jeder modale Unity-Dialog alle Steuerbefehle (`unity command …` läuft in die Zeitüberschreitung). Dieses Dokument beschreibt Ursachen, was wir verhindern und wie wir uns erholen.

## Ursachen, die wir gesehen haben

| Auslöser | Folge | Gegenmaßnahme |
|---|---|---|
| Editor hart beendet (`kill`, Absturz) mit ungespeicherter Szene | Beim nächsten Start fragt Unity „Szenen-Backup wiederherstellen?“ (`Temp/__Backupscenes`, `Assets/_Recovery`) | `scripts/unity_safe.sh` löscht beides vor dem Start (nur wenn kein Editor läuft); beide Pfade stehen im `.gitignore` |
| `run_tests` im laufenden Spielmodus | Zeitüberschreitung, danach reagieren alle Befehle nicht mehr | vor jedem Testlauf `editor_stop` (macht `unity_safe.sh test` selbst) |
| Kompilierfehler beim Start | möglicher „Abgesicherter Modus“-Dialog | Dateien nie halbfertig in `unity/Assets` ablegen; erst im dotnet-Wegwerfprojekt grün, dann übernehmen |
| Absturzmeldung des Editors | Dialog „Unity quit unexpectedly“ | Startoption `-silent-crashes` |
| API-Updater | Dialog „Update scripts?“ | Startoption `-disable-assembly-updater` |
| Szene mit Änderungen schließen/öffnen | Dialog „Szene speichern?“ | in Editor-Skripten keine `EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo`, kein `EditorUtility.DisplayDialog` (im Projekt aktuell nirgends verwendet; Prüfung per grep) |

## Werkzeug: `scripts/unity_safe.sh`

```
scripts/unity_safe.sh status             # aus | haengt | bereit
scripts/unity_safe.sh open               # startet den Editor, räumt Backups weg, wartet bis „bereit“
scripts/unity_safe.sh restart            # sauber beenden (unity close), notfalls kill <PID>, aufräumen, starten
scripts/unity_safe.sh test [Assembly]    # editor_stop, Tests, bei Hänger Neustart und zweiter Versuch; Ergebnis in work/test-results.json
scripts/unity_safe.sh watch              # Wächter: Neustart, wenn der Editor 3 Minuten nicht antwortet
```

Einstellungen über Umgebungsvariablen: `XNU_UNITY_PROJECT`, `XNU_UNITY_WAIT_OPEN`, `XNU_UNITY_PING_TIMEOUT`, `XNU_UNITY_TEST_TIMEOUT`.

Regeln:
- Wächter nur laufen lassen, wenn kein Agent den Editor im Spielmodus für eine lange Messung braucht (er startet nach drei fehlenden Antworten neu).
- Nie `pkill`; die Skripte beenden Prozesse nur per `kill <PID>`.
- Das Aufräumen löscht ungespeicherte Szenen-Änderungen. Das ist gewollt: Szenen entstehen aus Editor-Skripten und lassen sich neu erzeugen.

## Was nicht automatisiert ist

- **Dialoge des Betriebssystems** (Lizenz, Anmeldung, macOS-Berechtigungen) lassen sich nur mit Bedienungshilfen-Rechten per AppleScript wegklicken. Das ist fragil und braucht eine einmalige Freigabe; wir tun es nicht.
- **Unity-Hub-Anmeldung/Lizenz:** läuft über das CLI-Token; läuft es ab, hilft nur eine neue Anmeldung durch den Nutzer.
