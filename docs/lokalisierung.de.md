# Lokalisierung: Message-Dateien, Tags, Wortersetzung, Zeichensatz

Stand: 2026-10-19, Todo `ap-ui` (Analysephase). Dieses Dokument beschreibt, wie das Original Texte speichert und zusammensetzt, und den dazu gebauten
C#-Leser (`unity/Assets/Scripts/Text`, Assembly `Xnu.Text`, Tests `unity/Assets/Tests/EditMode/TextTests.cs`).
Es enthält nur Strukturen, Feldnamen und Zahlen. Alle Textbeispiele sind erfunden; Originaltexte stehen weder hier noch in den Tests.

**Prüfstufen** (wie in `docs/ui-spezifikation-1.md`):
- **[D]** aus den Daten gemessen (Katalog, UnityPy-Lesen der Bundles, Auswertung der JSON-Exporte); reproduzierbar mit den Skripten in Abschnitt 11.
- **[S]** aus `work/il2cpp/dump.cs` gelesen (Klassen, Felder, Offsets, Konstanten, Methodensignaturen), also die Form, nicht die Logik.
- **[A]** Annahme oder Schluss ohne direkten Beleg; im Text benannt.
- **[T]** durch Test auf synthetischen Daten abgesichert (nur für unseren Code).
- **[V]** gegen die echten Exporte geprüft (lokaler Lauf `work/dotnet-text/check`, nur Zahlen).
Ghidra-Pseudocode wurde für diesen Teil nicht ausgewertet; die Grammatiklogik des Originals ist daher **nicht** nachgebaut (Abschnitt 6).

## 1. Ergebnis in Kürze
- Die Texte liegen **nicht** als MSBT-Binärdateien vor, sondern **fertig vorverarbeitet** als Unity-ScriptableObjects `Dpr.Message.MsbtData` (je Textdatei ein Objekt mit Labels, Wortlisten und Platzhaltern). [D][S]
  Der Editor-Parser (`MsbtParser`) hat die MSBT-Dateien schon vor dem Bau umgewandelt. Zur Laufzeit gibt es nur noch Formatieren (`MessageFormatter`), kein Parsen.
- Neun Spielsprachen plus eine Kanji-Fassung des Japanischen: Japanisch (Kana und Kanji), Englisch, Französisch, Italienisch, Deutsch, Spanisch, Koreanisch,
  Chinesisch vereinfacht und traditionell. [D]
- Je Sprache 119 Textdateien mit 38.296 echten Labels (dazu 4.261 Auffüll-Einträge); gemeinsam genutzt: `common_msbt` mit 90 Dateien (Pokémon-Namen und Pokédex-Texte, 10 Sprachsätze
  zu je 9 Dateien) und 46.500 echten Labels. Die Zahl „42.557 Labels“ in `docs/masterdata.md` Abschnitt 15 zählt die Auffüll-Einträge mit. [D][V]
- Der Leser `Xnu.Text` liest den JSON-Export (`scripts/masterdata_export.py --messages`), baut daraus Textabschnitte mit Ereignissen (Zeilenumbruch, Seitenwechsel, Warten, Rückruf)
  und ersetzt Platzhalter über eine austauschbare Schnittstelle. 35 Tests grün (`dotnet test`, Wegwerfprojekt `work/dotnet-text`); Unity-Lauf der EditMode-Tests steht aus, weil beide Editoren belegt waren.
- **Nicht gelöst:** die sprachspezifische Grammatik (Artikel, Geschlecht, Plural; `FormatDE/EN/FR/IT/ES/Kor/SCTagProcess`) und die genaue Bedeutung einzelner Tag-Parameter (Abschnitt 6, 12).

## 2. Dateien und Bundles
| Bundle (unter `AssetAssistant/Message`) | Größe | Inhalt |
|---|---:|---|
| `english`, `french`, `german`, `italian`, `spanish` | 1,39 / 1,46 / 1,49 / 1,44 / 1,44 MB | je 119 `MsbtData`-Objekte, Namenspräfix `<sprache>_` |
| `jpn`, `jpn_kanji` | 1,33 / 1,34 MB | je 119; `jpn_kanji` hat `isKanji = 1` |
| `korean`, `simp_chinese`, `trad_chinese` | 1,29 / 1,23 / 1,26 MB | je 119, Präfixe `korean_`, `simp_`, `trad_` |
| `common_msbt` | 1,49 MB | 90 Objekte, alle `isResident = 1`: 9 Kurznamen × (9 Sprachen + `jpn_kanji`) |
| `Message` | 3,7 KB | nur das Unity-`AssetBundleManifest` |
Summe 14,5 MiB (11 Katalogeinträge). [D] Es gibt keine Audio- oder Texturanteile in diesen Bundles.

- **Dateinamen:** `<Sprachpräfix>_<Kurzname>`, z. B. `german_ss_bag`. Der Kurzname ist in allen Sprachen gleich; Kurznamen beginnen mit `ss_` (72, Oberfläche/System/Kampf),
  `dp_` (30, Handlung, Namen, Orte) oder `dlp_` (17, Zusatzinhalte). Die größten Dateien haben 3.014 (Trainertexte), 2.059 (Szenario) und 2.056 Labels (Kampf-Angriffsmeldungen). [D]
- **Sprach-IDs** (`MessageEnumData.MsgLangId`): Jpn 1, Usa 2, Fra 3, Ita 4, Deu 5, Esp 7, Kor 8, Sch 9, Tch 10; 6 ist unbelegt, 11 = Anzahl. Die Werte stehen im Feld `langID` jeder Datei und decken sich mit den Präfixen. [D][S]
- **Sprachvarianten der UI-Bundles:** Katalogendungen `.jp .en .fr .ge .it .ko .si .sp .tr` (jeweils 11 Bundles, zusammen die 99 Namen aus `_assetBundleNamesWithVariant`). Die Zuordnung Endung → Sprache
  (`ge` = Deutsch, `sp` = Spanisch, `si` = Chinesisch vereinfacht, `tr` = traditionell) ist aus den Namen abgeleitet, nicht aus Code belegt. [D][A]
- **Systemsprache:** `MessageEnumData.NXLangId` (Switch-Sprachcode: Japanisch 0, Englisch 1, Französisch 2, Deutsch 3, Italienisch 4, Spanisch 5, Koreanisch 7, Chinesisch vereinfacht 15, traditionell 16)
  wird auf `MsgLangId` abgebildet; `MessageLanguages.FromSystemLanguage` setzt das um, nicht unterstützte Sprachen fallen auf Englisch (Annahme). [S][A][T]

## 3. Format der Datei (`Dpr.Message.MsbtData`)
Felder und Offsets aus dem Il2Cpp-Dump [S]; JSON-Namen sind die Originalfeldnamen [D].

| Klasse | Feld | Typ | Bedeutung |
|---|---|---|---|
| `MsbtData` | `hash` | int | Dateikennung (vermutlich Hash des Namens, [A]) |
| | `langID` | `MsgLangId` | Sprache |
| | `isResident` | bool | dauerhaft im Speicher (nur `common_msbt`) |
| | `isKanji` | bool | Kanji-Fassung des Japanischen |
| | `labelDataArray` | `LabelData[]` | Labels |
| `LabelData` | `labelIndex` | int | Nummer des Labels in der Quelldatei |
| | `arrayIndex` | int | Position laut Original (nicht immer gleich der Position im Array, bei Auffüll-Einträgen 0) |
| | `labelName` | string | Name, z. B. Schema `PRÄFIX_NNN` |
| | `styleInfo` | `StyleInfo` | Darstellungsstil |
| | `attributeValueArray` | int[] | 5 Werte (Geschlecht, Anlautklasse, Zählbarkeit, Anzeigemuster, Artikel) oder leer |
| | `tagDataArray` | `TagData[]` | Platzhalter |
| | `wordDataArray` | `WordData[]` | Wortliste |
| `StyleInfo` | `styleIndex`, `colorIndex`, `fontSize`, `maxWidth`, `controlID` | int | Stil-Nr. (0..187, 124 verschiedene), Farb-Nr. (−1 = Standard), Schriftgröße, maximale Zeilenbreite in Pixeln, Steuerung (0 normal, 1 einzeilig im Kampf, 2 „unbekannte Nachricht“) |
| `TagData` | `tagIndex`, `groupID`, `tagID`, `tagPatternID`, `forceArticle`, `tagParameter`, `tagWordArray`, `forceGrmID` | | Platzhalter, siehe Abschnitt 5 |
| `WordData` | `patternID`, `eventID`, `tagIndex`, `tagValue`, `str`, `strWidth` | | Wort, siehe Abschnitt 4 |

**Auffüll-Einträge:** 4.261 Labels je Sprache (9.940 in `common_msbt`) haben leeren Namen, keine Wörter, `attributeValueArray` der Länge 0 und `fontSize` 0. Sie belegen Lücken in der Nummerierung,
tragen aber keinen Text. Wegen ihnen wiederholt sich `labelIndex` 0; der Leser überspringt sie bei der Suche (`MsbtLabel.IsPadding`). Echte Namen sind je Datei eindeutig. [D][V]

**Stil:** `fontSize` 42 (19.676 Labels), 54 (13.602), 32 (5.017). `maxWidth` 420 (12.187), 1080 (9.507), 1620 (3.927), 736 (3.516), 588 (2.940). Farbe −1 bei 37.921, 0 bei 4.261 (Auffüll), 10 bei 375. [D]
Die Stilnamen (`MessageEnumData.StyleID`, 76 Namen wie `std_18_N`, `keywait_text_23`) tragen Schriftgröße und Variante im Namen; die Tabelle `MessageStyleDataModel` (Schriftgröße, Farbe je Stil) liegt in `resources.assets` ohne TypeTree und ist noch nicht gelesen. [S]

## 4. Wortliste eines Labels
Ein Label ist eine Folge von `WordData`. Der Anzeigetext entsteht, indem man die Wörter der Reihe nach verarbeitet. [D][V]

| `patternID` | Name | Bedeutung | Häufigkeit (Deutsch) |
|---:|---|---|---:|
| 0 | `Str` | Textstück, `strWidth` = Breite in Pixeln der Originalschrift | 37.987 |
| 5 | `WordTag` | Platzhalter; `tagIndex` = **Position** in `tagDataArray` | 8.926 |
| 7 | `Event` | Textstück mit anschließendem Ereignis | 27.939 |
| 2 | `ColorTag` | TextMeshPro-Markup `<color=#…>` / `</color>` im Feld `str` | 598 |
| 3 | `SizeTag` | `<size=…%>` / `</size>` | 36 |
| 4 | `CtrlTag` | `<pos=…px>`, `<line-indent=…px>` | 22 |
| 1, 6 | `FontTag`, `SpriteFont` | vorgesehen, in Deutsch/Englisch nicht belegt | 0 |

`eventID` (`MsgEventID`) beschreibt, was **nach** dem Wort geschieht, unabhängig vom Muster:
| `eventID` | Name | Bedeutung | `tagValue` |
|---:|---|---|---|
| 0 | `None` | weiter im selben Abschnitt | – |
| 1 | `NewLine` | Zeilenumbruch | – |
| 2 | `Wait` | kurze Pause | Sekunden (0,15, 0,2, 0,5) |
| 3 | `ScrollPage` | Taste abwarten, Seite löschen (Symbol ▼) | – |
| 4 | `ScrollLine` | Taste abwarten, eine Zeile hochschieben (Symbol ▽) | – |
| 5 | `CallBack` | Rückruf an den Spielablauf | Rückrufnummer (0..10) |
| 6 | `GuidIcon` | Führungssymbol, unbelegt in den Daten | – |
| 7 | `End` | Ende der Nachricht | – |
Jedes echte Label endet mit `End` (38.296 von 38.296). Häufigkeiten Deutsch: `NewLine` 18.211, `ScrollPage` 4.291, `ScrollLine` 1.069, `CallBack` 47, `Wait` 31. [D][V]
Die Bedeutung von `ScrollPage`/`ScrollLine` und der Symbole stammt aus den Namen und den Konstanten `PAGE_CHANGE_CHAR` (▼ U+25BC) und `PAGE_SCROLL_CHAR` (▽ U+25BD); das genaue Verhalten ist [A].

**Rich-Text im Text:** in den Daten kommen nur `color`, `size`, `pos` und `line-indent` vor (Deutsch: 292 öffnende und 306 schließende `color`, je 18 `size`, 20 `pos`, 2 `line-indent`). Die Farbe ist ein Hexwert im Markup. [D]

**Abschnitte:** Beim Zusammensetzen ergibt sich je Ereignis ein Abschnitt (Text, Ereignis, Wert). Ein Label hat im Mittel 1,6 Abschnitte (Deutsch 61.945 Abschnitte bei 38.296 Labels), maximal 43 Wörter. [V]

## 5. Platzhalter (Tags)
`TagData` beschreibt, was zur Laufzeit eingesetzt wird. Zwei Zahlen heißen ähnlich und sind verschieden:
- `WordData.tagIndex` = Position in `tagDataArray` des Labels (immer gültig, 0 ungültige Verweise in Deutsch, Englisch und `common`). [V]
- `TagData.tagIndex` = **Platz im Laufzeitpuffer** `TagWordBuffer` (0..18, `WORD_PARAM_ARRAY_SIZE` = 19). Das Spiel schreibt vor dem Anzeigen die Werte in diese Plätze (`SetTagWordParam(index, wort)`), zwischen den Labels ist er leer. [D][S]
  Beispiel (erfunden): `{"tagIndex":10,"groupID":1,"tagID":0}` liest Platz 10, das Wort steht an Position 1 der Tag-Liste.

| `tagPatternID` | Name | Häufigkeit (Deutsch) | Bedeutung |
|---:|---|---:|---|
| 0 | `Word` | 7.709 | Wort aus dem Puffer, `groupID` 1 (Namen) oder 22 (Deutsch) |
| 1 | `Digit` | 714 | Zahl, `groupID` 2, `tagID` 0..6 = Stellenzahl (`DigitID`, Einer … Zehner-Millionen) |
| 5 | `GrammarWord` | 503 | Auswahl aus `tagWordArray` (meist 2 Wörter), `groupID` 22 (Deutsch) |
| 2, 3, 4, 6, 7, 8 | `Conversion`, `RichText`, `Grammar`, `ControlDesign`, `ControlMessage`, `SpriteFont` | 0 | vorgesehen, in Deutsch/Englisch nicht belegt |

**Gruppen und Namen:** `groupID` 1 = `Name`, `tagID` = `NameID`: in Deutsch 48 verschiedene Platzhalterarten kommen vor (höchste Nummer 85; Trainername 0, Pokémonname 1, Spitzname 2, Typ 3, Ort 5, Fähigkeit 6, Attacke 7, Wesen 8, Item 9, …; `NameID` kennt 76 Namen).
Häufigste (Deutsch): Pokémonname 2.586, Spitzname 2.290, Trainername 1.655, Item 399, Attacke 222. Weitere Gruppen: `System` 0 (Schrift, Größe, Farbe), `Digit` 2, `Grm` 16, `EN/FR/IT/DE/ES` 19–23, `Kor` 25, `SC` 26,
`Character1` 50 (24 Sonderzeichen: Herz, Note, ♂, ♀, Pokédollar, Pfeile, Taschensymbole …), `Character2` 51 (21: Anführungszeichen, schmale Leerzeichen, hochgestellte Buchstaben …), `Ctrl1` 189, `Ctrl2` 190. [S]
In den Exporten kommen nur die Gruppen 1, 2 und 22 (Deutsch), 1, 2 und 19 (Englisch) vor; Sonderzeichen und Steuerungen sind vor dem Bau in Wörter, Markup oder Ereignisse umgewandelt. [D]

**Parameter:** `tagParameter` bei Zahlen: 205 (616 ×, vermutlich „Standard/keiner“), 0, 1, 2, 3, 4, 5. `DigitTagParamID` kennt 1 Standard, 2 Komma, 3 Punkt, 4 Leerzeichen, 5 schmales Leerzeichen (Tausendertrenner, [S]);
die Bedeutung von 205 und 0 ist offen [A]. Bei Grammatik-Wörtern verweisen 255 (167 ×), 254 und 253 (182 ×) auf das Geschlecht des Spielers, des Fernsehsprechers beziehungsweise des Party-Pokémons
(`REF_USER_GENDER_VALUE` 255, `REF_TV_GENDER_VALUE` 254, `REF_USER_PARTY_VALUE` 253, [S]); kleine Werte 0..5 wählen vermutlich Wortformen [A]. `forceGrmID` (0 = keine, 1 Einzahl, 2 Mehrzahl, 3 Maskulin, 4 Anfangsbuchstabe groß) ist bei 21 von 8.926 Tags gesetzt. [D]

**Wortersetzung zur Laufzeit** (nur Namen und Signaturen, [S]): Klassen `PlayerNameData`, `MonsNameData`, `UserPokemonWordParam`, `ItemNameWordParam`, `PlaceWordParam`, `GlossaryWordParam`, `DigitWordParam`, `StringWordParam`, `TrTypeAndNameWordParam`
(alle `AWordParamBase`) füllen den Puffer. Namen werden über weitere Textdateien aufgelöst (Glossar): `ss_monsname`, `ss_wazaname`, `ss_itemname` mit den Varianten `_plural`, `_classified`, `_acc` (Mehrzahl, bestimmter/unbestimmter Artikel, Akkusativ),
`dp_trainers_name`, `dp_trainers_type`, `ss_tokusei`, `ss_seikaku`, `ss_typename`, `dp_fld_areaname*` (`MessageDataConstants`). Das Ei und feste Sprechernamen haben Sonderlabels. [S]

## 6. Grammatik (nicht nachgebaut)
Das Original formatiert Platzhalter je Sprache (`FormatENTagProcess`, `…FR…`, `…IT…`, `…DE…`, `…ES…`, `…Kor…`, `…SC…`) nach Geschlecht, Zählbarkeit, Anlaut und Artikelregeln (`MessageEnumData.AttributeID`, `ENID`, `DEID`, `GrmID`, `QtyID`, `GenderID`).
Diese Logik liegt nur im Binary. Bisher ausgewertet: Namen und Signaturen. Was `Xnu.Text.DefaultTagFormatter` heute tut, ist ein **Gerüst** [A][T]:
- Namen- und Wort-Platzhalter: Text aus dem Puffer (`TagWord.Text`); fehlt er, steht sichtbar `{gruppe:id}`.
- Zahlen: ganze Zahl, Tausendertrenner nach `tagParameter` (2 Komma, 3 Punkt, 4 Leerzeichen, 5 schmales Leerzeichen U+202F), **keine** Auffüllung (Annahme).
- Grammatik-Wörter: Auswahl nach Geschlecht der Quelle bei 253/254/255, sonst Einzahl (Anzahl 1) oder Mehrzahl (Annahme).
- `ITagFormatter` lässt sich ersetzen, sobald die Originallogik aus dem Pseudocode vorliegt. Das ist der nächste Schritt für Deutsch (Prüfung gegen Orakel-Läufe wie in den Kampf-Spezifikationen).

## 7. Zeichensatz und Schriften
- **Schrift:** TextMeshPro (Unity-Paket, `TMP_FontAsset` Version 1.1.0) mit **SDF-Atlas** (Render-Modus SDFAA, Rand 5 px). Fünf Schriftbundles `Dpr/font/*` (zusammen 24,2 MiB): [D]

| Bundle | Statische Glyphen (Zeichen) | Atlas | Dynamischer Fallback | eingebettete TTF |
|---|---:|---|---|---:|
| `efigs_font` (Englisch, Französisch, Italienisch, Deutsch, Spanisch) | 268 (273) | 1024² | 1024², Quellschrift TTF | 3,54 MB |
| `jpn_font` | 1.973 (1.976) | 2048² | 1024² | 3,44 MB |
| `kor_font` | 1.724 (1.724) | 2048² | 2048² | 3,72 MB |
| `sch_font` (+ `sch_ext_font` 41 Glyphen) | 3.306 (3.308) | 4096×2048 | 2048² | 7,81 MB |
| `tch_font` | 3.490 (3.490) | 4096×2048 | 2048² | 3,58 MB |
  Jedes Bundle enthält zusätzlich `or_font` (6 Glyphen, 128², Symbole wie U+202F und U+E300) und die Atlas-Texturen im Format `Alpha8`. Die Fallback-Schriften (`*_fb`, Population-Modus dynamisch) rendern Zeichen außerhalb des statischen Satzes zur Laufzeit aus der eingebetteten TrueType-Schrift.
  Die TTF-Familiennamen im Bundle sind kommerzielle Schriften (FOT-… und eine Nintendo-Hausschrift). [D]
- **Abdeckung Deutsch:** 141 verschiedene Zeichen in allen Textdateien; 138 stehen im statischen EFIGS-Satz, 1 (U+202F) in `or_font`, 2 Zeichen im Privatbereich (U+E104, U+E300) gehören zu Sprites/Symbolen (TMP-Sprite-Asset). Ä, Ö, Ü, ß und die Anführungszeichen („ “ ’) sind statisch vorhanden. Englisch: 131 Zeichen, 129 statisch. [D]
- **Schriftwahl je Sprache:** `MessageEnumData.FontID` (Std/Small/Big/Huge × Basis/efigs/kor/simp/trad, 20 Werte), `FontSizeID` Small/Std/Big/Huge, `UIFontSizeID` SSS bis XL (UI-Textgrößen, [S]); `MessageHelper.GetFontFileName(lang)` wählt das Bundle.
  Japanisch kennt Kana- und Kanji-Modus (`SetJPNKanjiFlag`, Konfig `LangJpnMode`). [S]
- **Breiten:** `strWidth` ist in den Daten fest (Pixel der Originalschrift). Layout (Zeilenumbruch, `CheckTextResize`, `CalcMessageWidth`) hängt daran. Eine andere Schrift ändert Umbrüche und Größen; für „1:1“ müssen die Originalschriften benutzt werden.
- **Lizenz:** Die TTF-Dateien sind Fremdinhalt. Sie dürfen nicht ins Repo und nicht in die Weitergabe; der Build nimmt sie nur aus dem eigenen Dump (wie Texturen) und legt sie in die persönliche App. Alternative offene Schriften (z. B. mit OFL) wären eine eigene Entscheidung und weichen von den festen Breiten ab (Abschnitt 12).
- **Sonderzeichen in Konstanten:** `SPACE_CODE` 12288 (ideografisches Leerzeichen), `QUATER_SPACE_CODE` 8239 (U+202F), `ZERO_SPACE_CODE` 8203, `TAG_CHAR` U+007C, `SPRITE_FONT_WIDTH` 32. [S]

## 8. Laufzeit im Original (Ablauf)
`MessageManager` (Singleton, liegt in `resources.assets`) [S]:
1. `Initialize(langId)`: lädt das Sprach-Bundle und `common_msbt` asynchron (`MsgDataFileLoader`, `LoadMsbtFileTask`), baut je Datei ein `MsbtDataModel` mit `labelIndexTable` und `labelDataArray`.
2. Abfragen: `GetMsgFile(dateiname[, sprache])`, `GetSimpleMessage` und `GetNameMessage` (nach Labelname oder Index), `GetAttributeInfo`. `UIText` (TextMeshPro-Unterklasse) bindet `messageFile` + `messageId` direkt an ein Textfeld und holt den Text beim Start oder Sprachwechsel.
3. Fenstertexte: `MsgWindow` → `MsgWindowDataModel.FormatTextData` → `MessageFormatter.Format` → `MessageTextLineDataModel[]` → `WindowMessage.UpdateMessage` (Schreibmaschine, Ereignisse) → `MsgTextContainer` / `WindowMsgText` (TMP).
4. Sprachwechsel: `ReloadAllMsbtFile`, `UIManager.Reload` entlädt Sprachatlanten und lädt die der neuen Sprache; Kanji-Wechsel über `onChangeKanjiMode`.
Außerdem: `LabelParseProcessor`/`MsbtParser` (Editor/Import) und `MessageViewer` (Debug-Szene) existieren im Spielcode, sind für uns nicht nötig.

## 9. Textgeschwindigkeit
Konfiguration `ConfigID.MessageSpeed` (Stufen `MSGSPEED` Slow 0, Normal 1, Fast 2, Max 3 = Anzahl). Die Zeitwerte stehen in `MsgWindowConfig` (ScriptableObject in `resources.assets`, ohne TypeTree über das Feldlayout aus dem Dump gelesen, [D][S]):

| Wert | Messung |
|---|---|
| `msgSpeed[]` (Sekunden je Zeichen) | 0,06 / 0,03 / 0,01 (Slow / Normal / Fast) |
| `fastForwardMagnification` | 5 |
| `scrollTextDuration` | 0,15 s |
| `waitAfterFinishMsgFrame` | 4 Bilder |
| `windowWidthOffset`, `offsetMessagePosX`, `iconMoveDist`, `addAngleSec` | 134, 115, 8, 210 |
| `wndAnimType`, `speakerFrameWidthOffset`, `textLinePaddingOffset` | 0, 0, 0 |
`MessageTimingConfig` trägt genau diese Standardwerte; `MessageTypewriter` zeigt ein Zeichen je Intervall (Annahme: das erste nach einem vollen Intervall) und kennt Schnellvorlauf (Faktor 5). [A][T]
Standardwert der Einstellung beim ersten Start ist nicht gelesen (liegt im Speicherstand/in der Konfig). Taste halten beschleunigt (`CheckPlayMsgSpeedUp`), der Auto-Modus (`EnableAutoMode`) wartet zeitgesteuert. [S]

## 10. Der Leser `Xnu.Text`
Reine C#-Assembly (`unity/Assets/Scripts/Text`, Abhängigkeit nur `Xnu.Data` wegen `MiniJson`, kein UnityEngine; C# 9).

| Datei | Inhalt |
|---|---|
| `MessageModel.cs` | Enums (`MessageLanguage`, `MessageSpeed`, `MessageEvent`), Konstanten (`WordPattern`, `TagPattern`, `TagGroup`, `TagParameterRef`), Modell `MsbtFile` / `MsbtLabel` / `MsbtStyle` / `MsbtTag` / `MsbtWord`, Suche nach Name und Labelnummer, Auffüll-Erkennung |
| `MsbtJsonReader.cs` | liest den Export (`class` muss `MsbtData` sein); Typfehler → `FormatException`; fehlende optionale Felder → Standardwerte; unbekannte `eventID` → `None` |
| `MessageLanguages.cs` | Sprache ↔ Bundle-Ordner, Dateipräfix, Variantenendung, Schriftbundle, EFIGS, Systemsprache, Zerlegen von Dateinamen (`jpn_kanji_` vor `jpn_`) |
| `MessageBank.cs` | alle Dateien, Schlüssel (Sprache, Kanji, Kurzname), Abfrage nach Labelname oder -nummer |
| `MessageComposer.cs` | Label → `ComposedMessage` (Abschnitte mit Text, Ereignis, Wert, statischer Breite; `FlatText`) |
| `TagWords.cs` | `TagWordBuffer` (19 Plätze), `ITagFormatter`, `DefaultTagFormatter` (Gerüst, Abschnitt 6) |
| `RichText.cs` | Markup erkennen, entfernen, sichtbare Zeichen zählen, Präfix mit n Zeichen |
| `MessageTiming.cs` | `MessageTimingConfig` (Messwerte aus Abschnitt 9), `MessageTypewriter` |
Verwendung: `MsbtJsonReader.Parse(json)` → `MessageBank.AddRange` → `bank.TryGetLabel("ss_bag", "NAME", MessageLanguage.Deu, out var label)` → `new MessageComposer().Compose(label, buffer)`.

**Tests** [T]: 35 NUnit-Tests mit erfundenen Texten (`TextTests.cs`): Leser (Struktur, Standardwerte, Fehler, Unicode, Auffüll-Einträge), Dateimodell, Sprachtabellen (alle 9 Sprachen), Bank (Sprache/Kanji getrennt, Duplikate), Zusammensetzen
(Ereignisse mit Werten, Platzhalter, fehlende Werte, Markup, fehlendes End, leeres Label), Zahlen und Grammatik-Gerüst, Rich-Text (inkl. Surrogatpaare), Schreibmaschine, Ende-zu-Ende. Lauf im Wegwerfprojekt `work/dotnet-text` (net10, NUnit 3.14): 35/35 grün.
Der Lauf der Unity-EditMode-Tests wurde nicht gemacht (keine Editor-Nutzung erlaubt); die Dateien sind byte-gleich zu den getesteten.

**Gegenprobe mit echten Exporten** [V] (`work/dotnet-text/check`, nur Zahlen):
| Export | Dateien | echte Labels | Auffüll | Wörter | Platzhalter | Abschnitte | ungültige Verweise | Parse | Compose |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Deutsch | 119 | 38.296 | 4.261 | 75.508 | 8.926 | 61.945 | 0 | 1,5 s | 48 ms |
| Englisch | 119 | 38.296 | 4.261 | 71.411 | 8.684 | 56.723 | 0 | 1,0 s | 37 ms |
| `common` | 90 | 46.500 | 9.940 | 64.775 | 268 | 64.526 | 0 | 1,0 s | 32 ms |
Jedes Label endet mit `End`. Die Ereigniszahlen stimmen mit der Python-Statistik (`scripts/msg_stats.py`) überein.
JSON-Parsen von ca. 18 MB dauert 1–1,5 s auf dem M1 Pro. Für den Player empfiehlt sich ein Build-Schritt, der den Export in ein kompaktes Binärformat ohne Auffüll-Einträge überführt (nicht gebaut).

## 11. Skripte (nur lesen, Ausgabe unter `work/ui`, gitignored)
| Skript | Zweck |
|---|---|
| `scripts/msg_stats.py` | Statistik der Message-Exporte (Muster, Ereignisse, Tags, Stile, Rich-Text); gibt keine Texte aus |
| `scripts/ui_dump_view.py` | Klassen aus `dump.cs` ohne RVA-Zeilen ausgeben |
| `scripts/ui_resources_scan.py` | `resources.assets`: Skriptklassen und `MsgWindowConfig` nach Feldlayout |
| `scripts/ui_find_script.py` | Bundles mit MonoBehaviours einer Klasse finden, Felder anzeigen (Strings gekürzt) |
Der Export der Texte selbst bleibt `scripts/masterdata_export.py export --messages`; für weitere Sprachen `MESSAGE_BUNDLES` ergänzen (bisher Englisch, Deutsch, `common`).

## 12. Lücken und offene Fragen
1. **Grammatik** (Abschnitt 6): Originallogik je Sprache fehlt; Deutsch zuerst nachbauen (Pseudocode von `FormatDETagProcess`, `FormatDigitTagProcess`, `MessageTagAnalyzer`), dann Orakel-Test.
2. **Zahlenparameter** (205, 0, 1..5) und Auffüllung der Zahlen: offen.
3. **Stiltabelle** (`styleIndex` → Größe/Farbe) und `UIFontSizeID`-Größen (`TextFontData`, `FontMaterialData` in `resources.assets`) nicht gelesen. Voraussetzung: Lesen von `resources.assets` ohne TypeTree (Feldlayout aus `dump.cs`, Vorbild: `ui_resources_scan.py`).
4. **Schriftlizenz:** Original-Schriften nur aus dem eigenen Dump in den persönlichen Build; Entscheidung des Nutzers nötig, ob ein offener Ersatz erlaubt sein soll (Breiten weichen ab, 1:1 gebrochen).
5. **Sprachumfang:** Alle 9 Sprachen liegen im Dump; für die erste Version genügen Deutsch und Englisch (Export vorhanden). Welche Sprache gilt auf dem Gerät (Systemsprache oder Auswahl über `SelectLanguage`)? Standard-Textgeschwindigkeit?
6. **Sprachvarianten der Bundles** (`.ge` usw.): Zuordnung abgeleitet; die Auswahllogik des Originals (`MessageHelper.GetLanguageVariant`) nicht gelesen.
7. **Typewriter-Verhalten** (erstes Zeichen, Tastenbeschleunigung, Warten am Ende) aus Signaturen und Konfigwerten geschätzt; Prüfung am Pseudocode von `WindowMessage.UpdateMessage` steht aus.
8. **Sound:** `MsgWindowSoundPlayer` und `SoundTagData` (7 Einträge, Wwise-Ereignisse) werden nicht umgesetzt (Vorgabe: kein Ton).
9. **Binärformat im Build:** JSON ist für den Player zu langsam/groß; ein kompaktes Format ist als Build-Schritt nachzuziehen.
