# unity/ – Unity-6.3-Projekt (eigener Code)

Hier liegt nur **eigener Code und Projekteinstellung**. Spieldaten, Dumps, Keys und extrahierte Inhalte gehören nicht ins Repo (`.gitignore`).

- `Assets/Scripts/Core` – gemeinsame Hilfen (z. B. `GameDataPaths`: Ort des Nutzer-Dumps, Variable `XNU_GAMEDATA`)
- `Assets/Scripts/Save` – Spielstand lesen/prüfen (Port von `scripts/bdsp_save.py`)
- `Assets/Scripts/Data` – Stammdaten aus den Bundles des Dumps
- `Assets/Scripts/Boot` – Start und Asset-Laden
- `Assets/Tests/EditMode` – Unit-Tests (nur synthetische Daten)

Team-ID und Signatur gehören nicht in `ProjectSettings`; `scripts/ios_deploy.sh` liest sie aus `work/local.env`.
Editor: `unity open unity` (Unity 6000.3.26f1, arm64, Metal).
