# Originalicons der nativen Apps

Stand: 2026-10-20. Gilt für macOS, iPadOS und beide Linux-Qt-Startwege.

## Daten und Auswahl

Die Icons stammen ausschließlich aus der Control-NCA des vom Nutzer bereitgestellten
Spiels. Die Extraktion erhält alle gültigen Sprachvarianten unter
`work/recomp/icons/source`. Update-Varianten ersetzen gleichsprachige Basisvarianten;
fehlende oder beschädigte Update-Bilder verdrängen kein gültiges Basisbild.
Die Titelzuordnung verhindert die Übernahme eines Icons aus einer anderen Anwendung.

**Keine Originalbilder, konvertierten Icons oder Nintendo-Testbilder ins Git aufnehmen.**
Sämtliche Bilddateien, Asset-Kataloge und fertigen App-Bundles bleiben unter `work/`.
Im Repository liegen nur Verarbeitungscode und Tests mit synthetischen Bildern.
Die Gestaltung wird deterministisch mit Pillow berechnet, ohne KI-Bildbearbeitung.

Standard ist amerikanisches Englisch, ersatzweise britisches Englisch, Deutsch,
die erste weitere gültige Variante oder der neutrale Platzhalter. Eine passende
Systemsprache wird nur in der Auswahl empfohlen: Sie löst keinen automatischen
Wechsel und keinen Startdialog aus. Manuelle Auswahl und Spielsprache sind unabhängig.

Im vorhandenen Dump wurden neun Varianten gefunden: Deutsch, Englisch (US),
Spanisch, Französisch, Italienisch, Japanisch, Koreanisch, vereinfachtes und
traditionelles Chinesisch. Es werden nur tatsächlich vorhandene Varianten angeboten.
Gleiche Bildinhalte teilen eine Bild-/Assetdatei, bleiben aber nach Sprache auswählbar.

## Erzeugen und Bauen

Die reguläre `extract`-Stufe von `scripts/build_all.sh` erhält die Icons vor dem
Aufräumen der Control-Daten. Bereits extrahierte Arbeitsstände lassen sich ergänzen,
ohne Gastcode oder RomFS neu zu bauen:

```sh
# Vorhandene NCAs unter work/base und work/update; Ziel-Titel aus work/exefs/main.npdm
python3 scripts/recomp/app/game_icons.py extract --prod-keys <prod.keys>

# Alternativ ausdrücklich bereitgestellte Container verwenden
python3 scripts/recomp/app/game_icons.py extract --xci <spiel.xci> --update-nsp <update.nsp> --prod-keys <prod.keys>
python3 scripts/recomp/app/game_icons.py extract --nsp <basisspiel.nsp> --prod-keys <prod.keys>
```

Falls nötig `--title-keys <title.keys>` ergänzen. Ohne vorhandene `main.npdm` ist
die Ziel-Titel-ID über `--title-id` anzugeben. Hactool-Ausgaben mit möglichen
Schlüsselwerten werden nicht protokolliert. Schlüssel werden nicht auf den Linux-Rechner übertragen.

Die Mac-Verpackung und `deploy_ios.sh build` erzeugen die jeweiligen Formate
automatisch. `vk_sync.sh` überträgt die lokalen Originalvarianten gezielt nach
`work/recomp/icons/source` auf dem entfernten Rechner; dort werden die Linux-PNGs
beim Vulkan-/Qt-Build erzeugt. Voraussetzung ist Pillow im verwendeten Python:
bei Fehlen gibt es eine Fehlermeldung, keine automatische Installation.

`BDSP_ICON_SOURCE` kann einen anderen lokalen Quellordner mit `icons.json`
bezeichnen. Ausgaben außerhalb von `work/` werden abgelehnt. Geänderte Quellen,
Metadaten oder Verarbeitungsskripte ändern den Mac-Verpackungsmarker; die
Generator-/Gastobjektmarker bleiben davon unabhängig.

## Gestaltung und Plattformgrenzen

**macOS:** Der Nutzer hat eine dunkle Kachel mit sichtbarem Innenabstand und
innerer Rundkachel gewählt. Auf 1.024 × 1.024 Pixeln hat die äußere Kachel
824 Pixel Kantenlänge und transparenten Abstand zum Canvas. Eine analytisch
berechnete Superellipse bildet die kontinuierliche Rundung. Das Originalmotiv
liegt um weitere 6,5 % der Kachelbreite nach innen versetzt auf einer weich
maskierten Rundkachel; dezente Schatten ersetzen eine harte Konturlinie.
Der Hintergrund wird aus den Randfarben des Originalbilds abgeleitet.
Dies ist eine eigene deterministische Gestaltung für die bestehende ICNS-/Dock-
Schnittstelle, keine übernommene Apple-Maskendatei.

Das englische Standardicon wird als `BDSP.icns` eingebaut. Unter **BDSP → App-Symbol**
sind alle Varianten auswählbar; die Einstellung wird mit `NSUserDefaults`
gespeichert. Die Auswahl ändert das Dock-Icon zur Laufzeit. Das Finder-Icon bleibt
das fest eingebaute Standardicon; die Dock-Schnittstelle verspricht keinen
sprachabhängigen Finder-Wechsel
([Apple: applicationIconImage](https://developer.apple.com/documentation/appkit/nsapplication/applicationiconimage)).

**iPadOS:** Das Motiv erhält 6,25 % inneren Abstand je Seite auf einer deckenden,
aus den Randfarben abgeleiteten Fläche. Die Datei bleibt quadratisch und ohne
Alpha-Kanal. Die äußere Rundung übernimmt iPadOS selbst; sie wird nicht doppelt
in die Bilddatei eingebrannt
([Apple: App icons](https://developer.apple.com/design/human-interface-guidelines/app-icons)).
Alle Originalvarianten werden mit `actool` kompiliert und als alternative Icons
registriert, einschließlich der iPad-spezifischen Metadaten. Die Auswahl steht unter
**Einstellungen → Apps → BDSP → App-Symbol**. Sie wird beim nächsten Aktivieren von
BDSP angewendet. Nur bei einer tatsächlich anderen Bildvariante wird ein Wechsel
angefordert; iPadOS kann dabei einen Systemhinweis anzeigen. Gleichzeitige
Wechselanfragen werden verhindert. Beim Wegfall einer gespeicherten Variante wird
auf den Standard zurückgefallen; dies ist auch im Einstellungshinweis erklärt.

Die persönliche `project.pbxproj` bleibt unberührt. Nach dem Einbinden der Icons,
Einstellungen und Shader wird das fertige Bundle mit der Identität des Xcode-Builds
erneut signiert und mit `codesign --verify --deep --strict` geprüft.
Der Shader-Startpfad bleibt unverändert.

**Linux:** Die PNG-Größen 16, 32, 48, 64, 128, 256 und 512 entstehen auf dem
entfernten Rechner unter `work/recomp/icons/linux`. Beide Qt-Hüllen erhalten ein
Menü **App-Symbol / App icon** und dieselbe über QSettings gespeicherte Auswahl.
Das laufende Fenster verwendet die gewählte Variante. Der erzeugte
`dev.local.xnubdsp.desktop`-Starter hat das englische Standardicon und liegt
ebenfalls nur unter `work/`; der Build installiert nichts in Systemverzeichnisse.
`BDSP_ICON_DIR` kann das erzeugte Linux-Iconverzeichnis ausdrücklich vorgeben.

Freie Bilddateien werden nicht zur Laufzeit importiert. Insbesondere iPadOS kann
als Home-Bildschirm-Icon nur beim Build registrierte Varianten verwenden.

## Prüfung

- Originaldaten: neun gültige Sprachvarianten aus dem lokalen Dump extrahiert.
- Synthetische Python-Tests: Zusammenführung, beschädigte Bilder, Platzhalter,
  Titelzuordnung, Mehrdeutigkeit, Bildgrößen, ICNS, iPad-Metadaten, Sprachvorschlag,
  Inhaltsduplikate und Build-Invalidierung.
- Deterministische Gestaltung: identische Pixel bei wiederholter Berechnung,
  transparente Mac-Außenfläche, deckendes iPad-Icon und exakt definierter Innenabstand.
- Nativer Apple-Test: gemeinsame Sprach-/Variantensuche für Mac und iPad.
- Nativer Qt-Test auf Linux: Standard, japanische Auswahl, erneutes Öffnen mit
  gespeicherter Auswahl sowie Rückfall nach Entfernen der Variante. Ausschließlich
  synthetische Bilder und isolierte Testeinstellungen unter `work/`.
- Beide Linux-Qt-Builds und kurze Startläufe geprüft. Mac- und Linux-Icon vom
  Nutzer als sichtbar bestätigt; ebenso das ursprüngliche iPad-Icon vor der Randergänzung.
- Ein gezielter iPad-Lauf, keine Wiederholungsschleifen. Der Gerätespielstand
  wurde vor der Installation gesichert und danach unverändert verglichen.

Logs: `work/builds/icons-*.log`; Linux-Bau-/Startlogs unter `work/recomp/icons/`.
Die Vorschau `work/recomp/icons/mac-layout-preview.png` zeigt die skriptbasierten
Gestaltungsvarianten; verwendet wird die dunkle Variante A mit innerer Rundung.
Die abschließende Sichtprüfung der Randgestaltung und ein echter iPad-
Variantenwechsel bleiben Nutzerprüfungen; sie werden nicht aus einem erfolgreichen
Build oder einem sichtbaren Standardicon abgeleitet.
