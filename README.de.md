**English version: [README.md](README.md)**

# strahlender-xnu

Pokémon Brilliant Diamond als native App auf iPad, iPhone, Mac, Linux und Windows. Du bringst dein eigenes, legal erworbenes Exemplar des Spiels und deine eigenen Schlüssel mit. Der Installer macht daraus eine App für dein Gerät.

Das ist kein Emulator. Der ARM64-Code des Spiels wird vorab in nativen Code übersetzt, und eine kleine Laufzeit ersetzt das Betriebssystem der Switch und ihre Grafikschnittstelle. Die Grafik läuft über Metal auf Apple-Geräten und über Vulkan unter Linux und Windows.

Das Repository enthält **keine Spieldaten**, keine Schlüssel, keine Speicherstände und keinen erzeugten Code. Pokémon ist eine Marke von Nintendo, Game Freak und Creatures; dieses Projekt steht mit keiner dieser Firmen in Verbindung.

## Warum „strahlender-xnu“

- **strahlender** ist deutsch für „brilliant“, das Wort aus dem deutschen Titel *Pokémon Strahlender Diamant* (Brilliant Diamond).
- **xnu** ist der Kernel unter macOS, iOS und iPadOS. Das Projekt begann auf Apple-Plattformen, Linux und Windows kamen später dazu, und der Name blieb.

## Wo es läuft

**Unterstützt:** iPad, iPhone (iPhone-11-Familie und neuer, A13-Chip mit 4 GB RAM oder mehr; iOS und iPadOS 17 oder neuer), Mac (Apple Silicon; macOS 14 Sonoma oder neuer), Linux x86-64, Windows 10 22H2 und 11 (x86-64).<br>
**Experimentell:** Linux aarch64 (braucht Vulkan 1.3). Installer und Build-Werkzeuge laufen auf einem echten aarch64-Rechner, ein vollständiger Spiel-Build und die Darstellung sind noch nicht verifiziert, Tester sind willkommen (siehe [docs/BUILD.de.md](docs/BUILD.de.md), Abschnitt 6).<br>
**Geplant:** Apple TV.

Das iPhone ist auf einem iPhone 11 Pro Max getestet.

Die Mindestsysteme (macOS 14, iOS und iPadOS 17) sind im Build gesetzt und wurden nur auf macOS 26 (Tahoe) geprüft, gebaut mit Xcode 27.1 und mit Xcode 16.4. Auf macOS 14 oder 15 sowie auf iOS 17 oder 18 wurde die App nicht gestartet. Tests auf solchen Systemen sind willkommen.

## Loslegen

- **Installer (am einfachsten):** Lade den [neuesten Installer](https://github.com/Veemyu/strahlender-xnu/releases/latest) für dein System. Er führt durch Schlüssel, Spieldateien und den Build. Python ist enthalten. Siehe [Installer-Details](installer/README.md) (englisch).
- **Kommandozeile:** `./install.command` auf macOS (Doppelklick im Finder) oder `./install-linux.sh` unter Linux prüft die Werkzeuge, fragt nach deinen Spieldateien und baut.
- **Bauanleitung:** [docs/BUILD.de.md](docs/BUILD.de.md) (englisch: [docs/BUILD.md](docs/BUILD.md)).

Du brauchst: dein eigenes Exemplar des Spiels (XCI, optional das Update als NSP) und deine `prod.keys`. Apps für iPhone und iPad werden auf einem Mac mit Xcode gebaut und mit deiner eigenen Apple-ID signiert.

**IPA exportieren** bettet die Spieldaten deines eigenen Dumps in die IPA ein, ein Sideload-Werkzeug wie iloader braucht sonst nichts. Die IPA ist groß (etwa 5,3 GB, so viel freier Platz wird gebraucht), nur für deine eigenen Geräte gedacht und darf nie weitergegeben werden: sie enthält Spieldaten aus deinem eigenen Dump, und dieses Projekt verteilt keine. Bei zu wenig Platz bricht der Export ab und nennt den Bedarf; er wechselt nie von selbst auf einen Export ohne Spieldaten. Bewusst ohne Spieldaten exportieren: "Ohne Spieldaten exportieren" im Installer (ab 0.1.4) oder `--ios-export-no-embed`; diese IPA braucht ihren Ordner **Game Library** ([Details](installer/docs/ios-delivery.md#an-ipa-alone-does-not-run)).

## Was dabei ist

- Ein GUI-Installer für macOS, Linux und Windows.
- App-Symbole, aus deinen eigenen Spieldaten erzeugt, in allen Sprachen des Spiels.
- Mod-Unterstützung: Dateimods (RomFS) lassen sich ohne Neuinstallation tauschen, Codemods (ExeFS) werden in die App gebaut. Siehe [docs/mods.md](docs/mods.md) (englisch).
- Die System-Tastatur der Switch (Horizon OS) für Texteingaben. Sie braucht deine Switch-Firmware beim Bauen. Siehe [docs/input.md](docs/input.md) (englisch).

## Dokumentation

Alle Dokumente liegen in [docs/](docs/) (nur Englisch); Einstieg in [docs/README.md](docs/README.md) (deutsch: [docs/README.de.md](docs/README.de.md)). Gute Einstiege sind `docs/architecture.md` für die Funktionsweise, `docs/recomp-macapp.md`, `docs/recomp-ios.md` und `docs/recomp-linux.md` für die Plattformen und `docs/changelog.md` für aktuelle Änderungen.

Der Unity-Nachbau ist eingestellt und liegt auf dem Branch `unity` (`unity/DEPRECATED.md` dort). `main` enthält ihn nicht mehr.

### Verwandte Projekte

Wer lieber den Weg über das Original-Unity-Projekt gehen möchte, findet die Arbeit an anderer Stelle:

- [uDPR](https://github.com/shatter9652/uDPR) von shatter9652, eine Unity-Rekreation, die auf [opendpr](https://github.com/TeamLumi/opendpr) aufbaut.
- [opendpr](https://github.com/TeamLumi/opendpr) von TeamLumi, das ursprüngliche Projekt.

## Fremdcode und Attribution

Dieses Projekt übernimmt und verändert Teile von **LASRecomp** (https://github.com/peiikai/LASRecomp, Commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5`), Copyright (c) 2026 Peiikai, MIT-Lizenz. Betroffen sind:

- `shader_translator/`: Maxwell-zu-MSL/GLSL-Übersetzer, aus dem Original abgeleitet und verändert (`shader_translator/NOTICE.md`, Lizenz `shader_translator/LICENSE-LASRecomp`).
- `scripts/recomp/runtime/`: Laufzeit im Entwurf des Originals, enthält Teile davon wörtlich (`scripts/recomp/runtime/NOTICE.md`, Lizenz `scripts/recomp/runtime/LICENSE-LASRecomp`).
- Header `cpu.h`, `simd.h`, `simd_fp.h`: unverändert in `scripts/recomp/upstream/runtime/` (Lizenz `scripts/recomp/upstream/LICENSE`).
- NVN-Grafikschicht (Metal und Vulkan): geändert gegenüber LASRecomp, Quellen unter `scripts/recomp/runtime/nvn/src/`; die unveränderten Originale stehen in der Git-Historie (Commits `e43b466`, `2d01ade`, `d1c40e7`) und im LASRecomp-Commit `09f8e5e`.

Vollständige Liste, Drittkomponenten und Nicht-Übernommenes: `THIRD_PARTY_NOTICES.md`.

Der Nutzer dieses Repositorys hat die Übernahme und Weiterentwicklung des MIT-lizenzierten Codes ausdrücklich freigegeben. Die Lizenz des Originals nimmt Nintendo-Eigentum und die Drittkomponenten seines `third_party/` ausdrücklich aus; davon ist hier nichts enthalten.

## Lizenz des eigenen Codes

Der eigene Code dieses Repositorys steht unter der MIT-Lizenz (`LICENSE`, Copyright (c) 2026 Veemyu). Ausgenommen sind die Fremdteile oben: Sie behalten ihre eigene Lizenz (`scripts/recomp/runtime/LICENSE-LASRecomp`, `scripts/recomp/upstream/LICENSE`, `shader_translator/LICENSE-LASRecomp`). Spieldaten, Keys und Dumps gehören nicht zum Repository und fallen nicht unter diese Lizenz.
