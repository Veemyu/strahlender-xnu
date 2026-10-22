# Localization: Message Files, Tags, Word Substitution, Character Set

> **Historical report:** This document describes the deprecated Unity rebuild. The native static recompilation is the current product; this report is retained as project history.

Status: 2026-10-19, todo `ap-ui` (analysis phase). This document describes how the original stores and assembles text, and the C# reader built for it (`unity/Assets/Scripts/Text`, assembly `Xnu.Text`, tests `unity/Assets/Tests/EditMode/TextTests.cs`).
It contains only structures, field names, and numbers. All text examples are invented; original text appears neither here nor in the tests.

**Verification levels** (as in the Unity-era `ui-spezifikation-1`, git history):

- **[D]** Measured from data (catalog, UnityPy bundle reads, JSON exports); reproducible with scripts in section 11.
- **[S]** Read from `work/il2cpp/dump.cs` (classes, fields, offsets, constants, method signatures): structure only, not logic.
- **[A]** Assumption or inference without direct evidence; identified in text.
- **[T]** Covered by tests using synthetic data (our code only).
- **[V]** Checked against real exports (local run `work/dotnet-text/check`, numbers only).

Ghidra pseudocode was not analyzed for this work, so the original grammar logic has **not** been recreated (sections 6 and 12).

## 1. Summary

- Text is **not** stored as MSBT binary files. It is preprocessed into Unity ScriptableObjects, `Dpr.Message.MsbtData` (one object per text file, containing labels, word lists, and placeholders). [D][S]
  The Editor parser (`MsbtParser`) converted MSBT files before build. At runtime, only formatting remains (`MessageFormatter`); no parsing occurs.
- Nine game languages plus a kanji form of Japanese: Japanese (kana and kanji), English, French, Italian, German, Spanish, Korean, Simplified Chinese, and Traditional Chinese. [D]
- Each language has 119 text files with 38,296 real labels (plus 4,261 padding entries). Shared `common_msbt`: 90 files (Pokémon names and Pokédex text, 10 language sets of 9 files each) and 46,500 real labels. The “42,557 labels” figure in section 15 of `docs/masterdata.md` includes padding entries. [D][V]
- Reader `Xnu.Text` reads the JSON export (`scripts/masterdata_export.py --messages`), builds text segments with events (line break, page break, wait, callback), and substitutes placeholders through a replaceable interface. 35 tests pass (`dotnet test`, throwaway project `work/dotnet-text`); Unity EditMode tests were not run because both Editors were occupied.
- **Unresolved:** language-specific grammar (articles, gender, plural; `FormatDE/EN/FR/IT/ES/Kor/SCTagProcess`) and the exact meaning of some tag parameters (sections 6, 12).

## 2. Files and bundles

| Bundle (under `AssetAssistant/Message`) | Size | Contents |
|---|---:|---|
| `english`, `french`, `german`, `italian`, `spanish` | 1.39 / 1.46 / 1.49 / 1.44 / 1.44 MB | 119 `MsbtData` objects each, name prefix `<language>_` |
| `jpn`, `jpn_kanji` | 1.33 / 1.34 MB | 119 each; `jpn_kanji` has `isKanji = 1` |
| `korean`, `simp_chinese`, `trad_chinese` | 1.29 / 1.23 / 1.26 MB | 119 each, prefixes `korean_`, `simp_`, `trad_` |
| `common_msbt` | 1.49 MB | 90 objects, all `isResident = 1`: 9 short names × (9 languages + `jpn_kanji`) |
| `Message` | 3.7 KB | Unity `AssetBundleManifest` only |

Total 14.5 MiB (11 catalog entries). [D] These bundles contain no audio or textures.

- **File names:** `<language-prefix>_<short-name>`, e.g. `german_ss_bag`. Short names are shared across languages and start with `ss_` (72, UI/system/battle), `dp_` (30, story, names, places), or `dlp_` (17, additional content). Largest files have 3,014 (trainer text), 2,059 (scenario), and 2,056 labels (battle move messages). [D]
- **Language IDs** (`MessageEnumData.MsgLangId`): Jpn 1, Usa 2, Fra 3, Ita 4, Deu 5, Esp 7, Kor 8, Sch 9, Tch 10; 6 unused, 11 = count. Values are in each file's `langID` field and match the prefixes. [D][S]
- **UI bundle variants:** catalog suffixes `.jp .en .fr .ge .it .ko .si .sp .tr` (11 bundles each, 99 names total in `_assetBundleNamesWithVariant`). Suffix-to-language mapping (`ge` = German, `sp` = Spanish, `si` = Simplified Chinese, `tr` = Traditional Chinese) is inferred from names, not confirmed by code. [D][A]
- **System language:** `MessageEnumData.NXLangId` (Switch language code: Japanese 0, English 1, French 2, German 3, Italian 4, Spanish 5, Korean 7, Simplified Chinese 15, Traditional Chinese 16) maps to `MsgLangId`; `MessageLanguages.FromSystemLanguage` implements this, with unsupported languages falling back to English (assumption). [S][A][T]

## 3. File format (`Dpr.Message.MsbtData`)

Fields and offsets are from the IL2CPP dump [S]; JSON names are original field names [D].

| Class | Field | Type | Meaning |
|---|---|---|---|
| `MsbtData` | `hash` | int | File ID (probably hash of name, [A]) |
| | `langID` | `MsgLangId` | Language |
| | `isResident` | bool | Kept resident in memory (only `common_msbt`) |
| | `isKanji` | bool | Japanese kanji form |
| | `labelDataArray` | `LabelData[]` | Labels |
| `LabelData` | `labelIndex` | int | Label number in source file |
| | `arrayIndex` | int | Original position (not always array position; 0 for padding entries) |
| | `labelName` | string | Name, e.g. pattern `PREFIX_NNN` |
| | `styleInfo` | `StyleInfo` | Display style |
| | `attributeValueArray` | int[] | 5 values (gender, initial-letter class, countability, display pattern, article) or empty |
| | `tagDataArray` | `TagData[]` | Placeholders |
| | `wordDataArray` | `WordData[]` | Word sequence |
| `StyleInfo` | `styleIndex`, `colorIndex`, `fontSize`, `maxWidth`, `controlID` | int | Style ID (0..187, 124 distinct), color ID (−1 = default), font size, maximum line width in pixels, control (0 normal, 1 single-line battle text, 2 “unknown message”) |
| `TagData` | `tagIndex`, `groupID`, `tagID`, `tagPatternID`, `forceArticle`, `tagParameter`, `tagWordArray`, `forceGrmID` | | Placeholder; see section 5 |
| `WordData` | `patternID`, `eventID`, `tagIndex`, `tagValue`, `str`, `strWidth` | | Word; see section 4 |

**Padding entries:** Each language has 4,261 labels with empty names, no words, an `attributeValueArray` of length 0, and `fontSize` 0 (9,940 in `common_msbt`). They fill gaps in numbering but contain no text. They cause `labelIndex` 0 to repeat; reader skips them when searching (`MsbtLabel.IsPadding`). Real names are unique within each file. [D][V]

**Styles:** `fontSize` 42 (19,676 labels), 54 (13,602), 32 (5,017). `maxWidth` 420 (12,187), 1080 (9,507), 1620 (3,927), 736 (3,516), 588 (2,940). Color −1 for 37,921 labels, 0 for 4,261 padding entries, 10 for 375. [D]
Style names (`MessageEnumData.StyleID`, 76 names such as `std_18_N`, `keywait_text_23`) encode font size and variant in their names. `MessageStyleDataModel` table (font size, color per style) is in `resources.assets` without TypeTree and has not been read. [S]

## 4. A label's word list

A label is a sequence of `WordData`. Display text is produced by processing words in order. [D][V]

| `patternID` | Name | Meaning | Frequency (German) |
|---:|---|---|---:|
| 0 | `Str` | Text segment; `strWidth` = width in pixels using original font | 37,987 |
| 5 | `WordTag` | Placeholder; `tagIndex` = **position** in `tagDataArray` | 8,926 |
| 7 | `Event` | Text segment followed by an event | 27,939 |
| 2 | `ColorTag` | TextMeshPro markup `<color=#…>` / `</color>` in `str` | 598 |
| 3 | `SizeTag` | `<size=…%>` / `</size>` | 36 |
| 4 | `CtrlTag` | `<pos=…px>`, `<line-indent=…px>` | 22 |
| 1, 6 | `FontTag`, `SpriteFont` | Reserved, not used in German/English | 0 |

`eventID` (`MsgEventID`) describes what happens **after** the word, independent of pattern:

| `eventID` | Name | Meaning | `tagValue` |
|---:|---|---|---|
| 0 | `None` | Continue in same segment | – |
| 1 | `NewLine` | Line break | – |
| 2 | `Wait` | Short pause | Seconds (0.15, 0.2, 0.5) |
| 3 | `ScrollPage` | Wait for button, clear page (symbol ▼) | – |
| 4 | `ScrollLine` | Wait for button, scroll up one line (symbol ▽) | – |
| 5 | `CallBack` | Return control to game flow | Callback number (0..10) |
| 6 | `GuidIcon` | Guide icon, unused in data | – |
| 7 | `End` | End of message | – |

Every real label ends with `End` (38,296 of 38,296). German frequencies: `NewLine` 18,211, `ScrollPage` 4,291, `ScrollLine` 1,069, `CallBack` 47, `Wait` 31. [D][V]
Meaning of `ScrollPage`/`ScrollLine` and symbols comes from names and constants `PAGE_CHANGE_CHAR` (▼ U+25BC) and `PAGE_SCROLL_CHAR` (▽ U+25BD); exact behavior is [A].

**Rich text:** data contains only `color`, `size`, `pos`, and `line-indent` (German: 292 opening and 306 closing `color`, 18 each `size`, 20 `pos`, 2 `line-indent`). Color is a hex value in markup. [D]

**Segments:** composition produces one segment per event (text, event, value). A label averages 1.6 segments (German: 61,945 segments for 38,296 labels), maximum 43 words. [V]

## 5. Placeholders (tags)

`TagData` describes what is substituted at runtime. Two similarly named numbers have different meanings:

- `WordData.tagIndex` = position in the label's `tagDataArray` (always valid; 0 invalid references in German, English, and `common`). [V]
- `TagData.tagIndex` = **slot in runtime buffer** `TagWordBuffer` (0..18, `WORD_PARAM_ARRAY_SIZE` = 19). Game writes values to these slots before display (`SetTagWordParam(index, word)`); buffer is empty between labels. [D][S]
  Example (invented): `{"tagIndex":10,"groupID":1,"tagID":0}` reads slot 10; the word is at position 1 in the tag list.

| `tagPatternID` | Name | Frequency (German) | Meaning |
|---:|---|---:|---|
| 0 | `Word` | 7,709 | Word from buffer; `groupID` 1 (names) or 22 (German) |
| 1 | `Digit` | 714 | Number; `groupID` 2, `tagID` 0..6 = number of digits (`DigitID`, ones … tens of millions) |
| 5 | `GrammarWord` | 503 | Choose from `tagWordArray` (usually 2 words); `groupID` 22 (German) |
| 2, 3, 4, 6, 7, 8 | `Conversion`, `RichText`, `Grammar`, `ControlDesign`, `ControlMessage`, `SpriteFont` | 0 | Reserved, not used in German/English |

**Groups and names:** `groupID` 1 = `Name`, `tagID` = `NameID`: German data uses 48 distinct placeholder types (highest ID 85; trainer name 0, Pokémon name 1, nickname 2, type 3, place 5, ability 6, move 7, nature 8, item 9, …; `NameID` has 76 names).
Most frequent in German: Pokémon name 2,586, nickname 2,290, trainer name 1,655, item 399, move 222. Other groups: `System` 0 (font, size, color), `Digit` 2, `Grm` 16, `EN/FR/IT/DE/ES` 19–23, `Kor` 25, `SC` 26, `Character1` 50 (24 special characters: heart, note, ♂, ♀, Pokédollar, arrows, pocket symbols, …), `Character2` 51 (21: quotation marks, thin spaces, superscript letters, …), `Ctrl1` 189, `Ctrl2` 190. [S]
Exports contain only groups 1, 2, and 22 (German), or 1, 2, and 19 (English); special characters and controls are converted to words, markup, or events before build. [D]

**Parameters:** For numbers, `tagParameter` values: 205 (616 times, probably “standard/none”), 0, 1, 2, 3, 4, 5. `DigitTagParamID` defines 1 standard, 2 comma, 3 period, 4 space, 5 narrow space (thousands separator, [S]); meanings of 205 and 0 are open [A]. For grammar words, 255 (167 times), 254, and 253 (182 times) refer to gender of player, TV commentator, and party Pokémon (`REF_USER_GENDER_VALUE` 255, `REF_TV_GENDER_VALUE` 254, `REF_USER_PARTY_VALUE` 253, [S]); small values 0..5 probably select word forms [A]. `forceGrmID` (0 none, 1 singular, 2 plural, 3 masculine, 4 capitalize first letter) is set on 21 of 8,926 tags. [D]

**Runtime word substitution** (names and signatures only, [S]): classes `PlayerNameData`, `MonsNameData`, `UserPokemonWordParam`, `ItemNameWordParam`, `PlaceWordParam`, `GlossaryWordParam`, `DigitWordParam`, `StringWordParam`, `TrTypeAndNameWordParam` (all `AWordParamBase`) fill the buffer. Names resolve through other text files (glossary): `ss_monsname`, `ss_wazaname`, `ss_itemname` with variants `_plural`, `_classified`, `_acc` (plural, definite/indefinite article, accusative), `dp_trainers_name`, `dp_trainers_type`, `ss_tokusei`, `ss_seikaku`, `ss_typename`, `dp_fld_areaname*` (`MessageDataConstants`). Egg and fixed speaker names use special labels. [S]

## 6. Grammar (not recreated)

Original formats placeholders per language (`FormatENTagProcess`, `…FR…`, `…IT…`, `…DE…`, `…ES…`, `…Kor…`, `…SC…`) using gender, countability, initial-letter class, and article rules (`MessageEnumData.AttributeID`, `ENID`, `DEID`, `GrmID`, `QtyID`, `GenderID`).
This logic exists only in the binary. So far, only names and signatures have been analyzed. Current behavior of `Xnu.Text.DefaultTagFormatter` is a **skeleton** [A][T]:

- Name/word placeholders: text from buffer (`TagWord.Text`); if missing, visibly render `{group:id}`.
- Numbers: integer, thousands separator selected by `tagParameter` (2 comma, 3 period, 4 space, 5 narrow space U+202F), **no zero-padding** (assumed).
- Grammar words: select by source gender for 253/254/255; otherwise singular (quantity 1) or plural (assumed).
- `ITagFormatter` can be replaced once original logic is recovered from pseudocode. Next step for German is verification against oracle runs as in the battle specifications.

## 7. Character set and fonts

- **Font:** TextMeshPro (Unity package, `TMP_FontAsset` version 1.1.0) with **SDF atlas** (SDFAA render mode, 5 px padding). Five font bundles `Dpr/font/*` (24.2 MiB total): [D]

| Bundle | Static glyphs (characters) | Atlas | Dynamic fallback | Embedded TTF |
|---|---:|---|---|---:|
| `efigs_font` (English, French, Italian, German, Spanish) | 268 (273) | 1024² | 1024², source TTF | 3.54 MB |
| `jpn_font` | 1,973 (1,976) | 2048² | 1024² | 3.44 MB |
| `kor_font` | 1,724 (1,724) | 2048² | 2048² | 3.72 MB |
| `sch_font` (+ `sch_ext_font`, 41 glyphs) | 3,306 (3,308) | 4096×2048 | 2048² | 7.81 MB |
| `tch_font` | 3,490 (3,490) | 4096×2048 | 2048² | 3.58 MB |

  Each bundle also contains `or_font` (6 glyphs, 128², symbols such as U+202F and U+E300) and atlas textures in `Alpha8` format. Fallback fonts (`*_fb`, dynamic population mode) render characters outside the static set at runtime from embedded TrueType font.
  TTF family names in bundles are commercial fonts (FOT-… and one Nintendo house font). [D]
- **German coverage:** 141 distinct characters across all text files; 138 are in static EFIGS set, 1 (U+202F) in `or_font`, 2 private-use characters (U+E104, U+E300) are sprites/symbols (TMP Sprite Asset). Ä, Ö, Ü, ß and quotation marks („ “ ’) are present statically. English: 131 characters, 129 static. [D]
- **Font selection by language:** `MessageEnumData.FontID` (Std/Small/Big/Huge × Base/efigs/kor/simp/trad, 20 values), `FontSizeID` Small/Std/Big/Huge, `UIFontSizeID` SSS to XL (UI text sizes, [S]); `MessageHelper.GetFontFileName(lang)` chooses bundle.
  Japanese supports kana and kanji modes (`SetJPNKanjiFlag`, config `LangJpnMode`). [S]
- **Widths:** `strWidth` is fixed in data (pixels using original font). Layout (line breaks, `CheckTextResize`, `CalcMessageWidth`) depends on it. A different font changes wrapping and sizing; original fonts are required for “1:1.”
- **License:** TTFs are third-party content. They must not be added to repository or redistributed; build extracts them only from user's own dump (like textures) and places them in personal app. Open licensed alternatives (e.g. OFL) would be a separate decision and differ from fixed widths (section 12).
- **Special-character constants:** `SPACE_CODE` 12288 (ideographic space), `QUATER_SPACE_CODE` 8239 (U+202F), `ZERO_SPACE_CODE` 8203, `TAG_CHAR` U+007C, `SPRITE_FONT_WIDTH` 32. [S]

## 8. Original runtime flow

`MessageManager` (singleton in `resources.assets`) [S]:

1. `Initialize(langId)`: asynchronously loads language bundle and `common_msbt` (`MsgDataFileLoader`, `LoadMsbtFileTask`), then builds an `MsbtDataModel` per file with `labelIndexTable` and `labelDataArray`.
2. Queries: `GetMsgFile(filename[, language])`, `GetSimpleMessage`, `GetNameMessage` (by label name or index), `GetAttributeInfo`. `UIText` (TextMeshPro subclass) binds `messageFile` + `messageId` directly to a text field and fetches the text at startup or language change.
3. Window text: `MsgWindow` → `MsgWindowDataModel.FormatTextData` → `MessageFormatter.Format` → `MessageTextLineDataModel[]` → `WindowMessage.UpdateMessage` (typewriter, events) → `MsgTextContainer` / `WindowMsgText` (TMP).
4. Language change: `ReloadAllMsbtFile`, `UIManager.Reload` unloads old language atlases and loads new ones; kanji change via `onChangeKanjiMode`.

The game code also includes `LabelParseProcessor`/`MsbtParser` (Editor/import) and `MessageViewer` (debug scene); we do not need them.

## 9. Text speed

Configuration `ConfigID.MessageSpeed` (levels `MSGSPEED`: Slow 0, Normal 1, Fast 2, Max 3 = count). Timing values are in `MsgWindowConfig` (ScriptableObject in `resources.assets`, no TypeTree; field layout read from dump, [D][S]):

| Value | Measurement |
|---|---|
| `msgSpeed[]` (seconds per character) | 0.06 / 0.03 / 0.01 (Slow / Normal / Fast) |
| `fastForwardMagnification` | 5 |
| `scrollTextDuration` | 0.15 s |
| `waitAfterFinishMsgFrame` | 4 frames |
| `windowWidthOffset`, `offsetMessagePosX`, `iconMoveDist`, `addAngleSec` | 134, 115, 8, 210 |
| `wndAnimType`, `speakerFrameWidthOffset`, `textLinePaddingOffset` | 0, 0, 0 |

`MessageTimingConfig` carries these defaults; `MessageTypewriter` shows one character per interval (assumption: first character after one full interval) and supports fast-forward (factor 5). [A][T]
Default setting on first launch has not been read (stored in save/config). Holding button accelerates (`CheckPlayMsgSpeedUp`); auto mode (`EnableAutoMode`) waits on a timer. [S]

## 10. Reader `Xnu.Text`

Pure C# assembly (`unity/Assets/Scripts/Text`, depends only on `Xnu.Data` for `MiniJson`, no UnityEngine; C# 9).

| File | Contents |
|---|---|
| `MessageModel.cs` | Enums (`MessageLanguage`, `MessageSpeed`, `MessageEvent`), constants (`WordPattern`, `TagPattern`, `TagGroup`, `TagParameterRef`), models `MsbtFile`/`MsbtLabel`/`MsbtStyle`/`MsbtTag`/`MsbtWord`, lookup by name/label number, padding detection |
| `MsbtJsonReader.cs` | Reads export (`class` must be `MsbtData`); type errors → `FormatException`; missing optional fields → defaults; unknown `eventID` → `None` |
| `MessageLanguages.cs` | Language ↔ bundle folder, file prefix, variant suffix, font bundle, EFIGS, system language, parse file names (`jpn_kanji_` before `jpn_`) |
| `MessageBank.cs` | All files; keys (language, kanji, short name); lookup by label name or number |
| `MessageComposer.cs` | Label → `ComposedMessage` (segments with text, event, value, static width; `FlatText`) |
| `TagWords.cs` | `TagWordBuffer` (19 slots), `ITagFormatter`, `DefaultTagFormatter` (skeleton, section 6) |
| `RichText.cs` | Recognize/strip markup, count visible characters, prefix with n characters |
| `MessageTiming.cs` | `MessageTimingConfig` (measurements from section 9), `MessageTypewriter` |

Usage: `MsbtJsonReader.Parse(json)` → `MessageBank.AddRange` → `bank.TryGetLabel("ss_bag", "NAME", MessageLanguage.Deu, out var label)` → `new MessageComposer().Compose(label, buffer)`.

**Tests** [T]: 35 NUnit tests with invented text (`TextTests.cs`): reader (structure, defaults, errors, Unicode, padding), file model, language tables (all 9 languages), bank (language/kanji separation, duplicates), composition (events with values, placeholders, missing values, markup, missing End, empty label), number and grammar skeleton, rich text (including surrogate pairs), typewriter, end-to-end. Run in throwaway project `work/dotnet-text` (net10, NUnit 3.14): 35/35 passing.
Unity EditMode tests were not run (no Editor use allowed); files are byte-identical to tested versions.

**Cross-check against real exports** [V] (`work/dotnet-text/check`, numbers only):

| Export | Files | Real labels | Padding | Words | Placeholders | Segments | Invalid references | Parse | Compose |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| German | 119 | 38,296 | 4,261 | 75,508 | 8,926 | 61,945 | 0 | 1.5 s | 48 ms |
| English | 119 | 38,296 | 4,261 | 71,411 | 8,684 | 56,723 | 0 | 1.0 s | 37 ms |
| `common` | 90 | 46,500 | 9,940 | 64,775 | 268 | 64,526 | 0 | 1.0 s | 32 ms |

Every label ends with `End`. Event counts match Python statistics (`scripts/msg_stats.py`).
Parsing about 18 MB JSON takes 1–1.5 s on M1 Pro. For player, a build step should convert exports into compact binary format without padding entries (not implemented).

## 11. Scripts (read-only; output under ignored `work/ui`)

| Script | Purpose |
|---|---|
| `scripts/msg_stats.py` | Statistics for message exports (patterns, events, tags, styles, rich text); emits no text |
| `scripts/ui_dump_view.py` | Print classes from `dump.cs` without RVA lines |
| `scripts/ui_resources_scan.py` | Inspect `resources.assets`: script classes and `MsgWindowConfig` by field layout |
| `scripts/ui_find_script.py` | Find bundles with a class's MonoBehaviours, show fields (truncate strings) |

Text export itself remains `scripts/masterdata_export.py export --messages`; to add more languages, extend `MESSAGE_BUNDLES` (so far English, German, `common`).

## 12. Gaps and open questions

1. **Grammar** (section 6): original per-language logic missing; implement German first (pseudocode for `FormatDETagProcess`, `FormatDigitTagProcess`, `MessageTagAnalyzer`), then oracle test.
2. **Number parameters** (205, 0, 1..5) and number padding: unresolved.
3. **Style table** (`styleIndex` → size/color) and `UIFontSizeID` sizes (`TextFontData`, `FontMaterialData` in `resources.assets`) not read. Requires reading `resources.assets` without TypeTree (field layout from `dump.cs`, following `ui_resources_scan.py`).
4. **Font license:** original fonts only from user's own dump into personal build; user decision needed whether open replacement is allowed (widths differ; 1:1 fidelity lost).
5. **Language scope:** dump contains all 9 languages; first version needs only German/English (exports available). Which device language should apply (system language or `SelectLanguage`)? Default text speed?
6. **Bundle language variants** (`.ge`, etc.): mapping is inferred; original selection logic (`MessageHelper.GetLanguageVariant`) not read.
7. **Typewriter behavior** (first character, button acceleration, end wait) estimated from signatures/config; pseudocode of `WindowMessage.UpdateMessage` has not been checked.
8. **Audio:** `MsgWindowSoundPlayer` and `SoundTagData` (7 entries, Wwise events) are not implemented (requirement: no audio).
9. **Build binary format:** JSON is too slow/large for player; compact format should be added as build step.
