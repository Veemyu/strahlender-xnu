# Neustartprompt

Diesen Text in eine neue Sitzung im Repo `strahlender-xnu` einfügen:

---

Wir arbeiten im Repo `strahlender-xnu` weiter: natives Pokémon Brilliant Diamond für macOS und iPadOS per statischer Rekompilation des Original-ARM64-Codes (Unity-Rebuild ist deprecated, nicht anfassen).

Lies zuerst `todo/neustart.md`, dann `docs/arbeitsstand-2026-10-19.md` und `docs/betriebshandbuch.md`. Prüfe mit `git status`, `git log -3` und `git log origin/main -1`, ob alles gepusht ist und ob noch Prozesse laufen (nur eigene PIDs, `kill <PID>`).

Regeln: kein sudo, kein Plattenscan. Repo-Dateien nur mit `edit`/`create`. Nie Spieldaten, Keys, Saves, Screenshots oder erzeugten Code ins Repo. Commit nur als Veemyu ohne Co-Author, danach pushen; vor dem Commit `python3 scripts/repo_check.py` und `python3 -m unittest discover -s scripts/tests`. Dokumente auf Deutsch in UTF-8 mit ä ö ü ß. Antworten kurz. Kleine Aufgaben an `claude-haiku-5.5` oder `gpt-6-luna`, Code und Fehlersuche an Sonnet, höchstens zwei große Agenten gleichzeitig, Agenten committen nie. Keine Wiederholungsschleifen auf dem iPad.

Fasse danach in fünf Zeilen zusammen, wo wir stehen, und schlage vor, mit Todo 1 (Wasser in Metal) zu beginnen. Warte auf meine Bestätigung, bevor du Agenten startest.
