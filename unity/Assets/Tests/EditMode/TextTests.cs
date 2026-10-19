using System;
using System.Collections.Generic;
using NUnit.Framework;
using Xnu.Text;

namespace Xnu.Tests
{
    // Ausschließlich synthetische Beispieldaten mit erfundenen Texten; die Struktur entspricht dem MsbtData-Export.
    public class TextTests
    {
        // --- Hilfen für synthetische JSON-Daten ---

        static string Word(int pattern, int ev, string str, int tagIndex = -1, double tagValue = 0, double width = -1) =>
            "{\"patternID\":" + pattern + ",\"eventID\":" + ev + ",\"tagIndex\":" + tagIndex + ",\"tagValue\":" + tagValue.ToString("0.0###", System.Globalization.CultureInfo.InvariantCulture) +
            ",\"str\":\"" + str + "\",\"strWidth\":" + width.ToString("0.0###", System.Globalization.CultureInfo.InvariantCulture) + "}";

        static string Tag(int slot, int group, int id, int pattern, int parameter = 0, string words = "") =>
            "{\"tagIndex\":" + slot + ",\"groupID\":" + group + ",\"tagID\":" + id + ",\"tagPatternID\":" + pattern +
            ",\"forceArticle\":0,\"tagParameter\":" + parameter + ",\"tagWordArray\":[" + words + "],\"forceGrmID\":0}";

        static string Label(int index, string name, string words, string tags = "", string style = null) =>
            "{\"labelIndex\":" + index + ",\"arrayIndex\":" + index + ",\"labelName\":\"" + name + "\"," +
            "\"styleInfo\":" + (style ?? "{\"styleIndex\":3,\"colorIndex\":-1,\"fontSize\":42,\"maxWidth\":1000,\"controlID\":0}") + "," +
            "\"attributeValueArray\":[5,0],\"tagDataArray\":[" + tags + "],\"wordDataArray\":[" + words + "]}";

        static string File(string name, int lang, string labels, bool resident = false, bool kanji = false) =>
            "{\"name\":\"" + name + "\",\"data\":{\"hash\":77,\"langID\":" + lang + ",\"isResident\":" + (resident ? 1 : 0) +
            ",\"isKanji\":" + (kanji ? 1 : 0) + ",\"labelDataArray\":[" + labels + "]}}";

        static string Doc(params string[] files) =>
            "{\"class\":\"MsbtData\",\"namespace\":\"Dpr.Message\",\"assembly\":\"Assembly-CSharp.dll\",\"bundle\":\"synthetic\",\"instances\":[" +
            string.Join(",", files) + "]}";

        static MsbtLabel LabelOf(string words, string tags = "")
        {
            var files = MsbtJsonReader.Parse(Doc(File("german_demo", 5, Label(0, "LBL_000", words, tags))));
            return files[0].Labels[0];
        }

        // --- Leser ---

        [Test]
        public void ParseReadsFilesLabelsStyleTagsAndWords()
        {
            var json = Doc(File("german_demo_a", 5,
                Label(7, "DEMO_001", Word(0, 0, "Hallo ") + "," + Word(5, 0, "", 0) + "," + Word(7, 7, "!", -1, 0, 6.5),
                    Tag(3, 1, 0, 0, 0, "\"eins\",\"zwei\""))));
            var files = MsbtJsonReader.Parse(json);
            Assert.AreEqual(1, files.Count);
            var f = files[0];
            Assert.AreEqual("german_demo_a", f.Name);
            Assert.AreEqual(77, f.Hash);
            Assert.AreEqual(5, f.LanguageId);
            Assert.IsFalse(f.IsResident);
            var l = f.Labels[0];
            Assert.AreEqual(7, l.LabelIndex);
            Assert.AreEqual("DEMO_001", l.Name);
            Assert.AreEqual(3, l.Style.StyleIndex);
            Assert.AreEqual(-1, l.Style.ColorIndex);
            Assert.AreEqual(42, l.Style.FontSize);
            Assert.AreEqual(1000, l.Style.MaxWidth);
            Assert.AreEqual(new[] { 5, 0 }, l.Attributes);
            Assert.AreEqual(1, l.Tags.Length);
            Assert.AreEqual(3, l.Tags[0].Index);
            Assert.AreEqual(new[] { "eins", "zwei" }, l.Tags[0].Words);
            Assert.AreEqual(3, l.Words.Length);
            Assert.AreEqual(WordPattern.WordTag, l.Words[1].Pattern);
            Assert.AreEqual(0, l.Words[1].TagIndex);
            Assert.AreEqual(MessageEvent.End, l.Words[2].Event);
            Assert.AreEqual(6.5f, l.Words[2].Width, 1e-6);
        }

        [Test]
        public void ParseUsesDefaultsForMissingOptionalFields()
        {
            const string json = "{\"class\":\"MsbtData\",\"instances\":[{\"name\":\"x\",\"data\":{\"labelDataArray\":[{\"labelName\":\"A\"}]}}]}";
            var l = MsbtJsonReader.Parse(json)[0].Labels[0];
            Assert.AreEqual("A", l.Name);
            Assert.AreEqual(0, l.Words.Length);
            Assert.AreEqual(0, l.Tags.Length);
            Assert.AreEqual(-1, l.Style.ColorIndex);
        }

        [Test]
        public void ParseMapsUnknownEventIdsToNone()
        {
            var l = LabelOf(Word(0, -1, "a") + "," + Word(0, 99, "b"));
            Assert.AreEqual(MessageEvent.None, l.Words[0].Event);
            Assert.AreEqual(MessageEvent.None, l.Words[1].Event);
        }

        [Test]
        public void ParseRejectsWrongStructure()
        {
            Assert.Throws<FormatException>(() => MsbtJsonReader.Parse("[]"));
            Assert.Throws<FormatException>(() => MsbtJsonReader.Parse("{\"class\":\"WazaTable\",\"instances\":[]}"));
            Assert.Throws<FormatException>(() => MsbtJsonReader.Parse("{\"class\":\"MsbtData\",\"instances\":[{\"name\":\"x\"}]}"));
            Assert.Throws<FormatException>(() =>
                MsbtJsonReader.Parse("{\"class\":\"MsbtData\",\"instances\":[{\"name\":\"x\",\"data\":{\"labelDataArray\":5}}]}"));
            Assert.Throws<FormatException>(() =>
                MsbtJsonReader.Parse("{\"class\":\"MsbtData\",\"instances\":[{\"name\":\"x\",\"data\":{\"labelDataArray\":[{\"labelName\":3}]}}]}"));
            Assert.Throws<FormatException>(() => MsbtJsonReader.Parse("{\"class\":\"MsbtData\",\"instances\":["));
        }

        [Test]
        public void ParseHandlesUnicodeAndEscapes()
        {
            var l = LabelOf(Word(0, 7, "Käse \\u00fc \\\"x\\\" \\ud83d\\ude00"));
            Assert.AreEqual("Käse ü \"x\" \U0001F600", l.Words[0].Text);
        }

        // --- Dateimodell ---

        [Test]
        public void PaddingLabelsAreSkippedAndLookupsWork()
        {
            var labels = Label(0, "FIRST", Word(0, 7, "a")) + "," +
                         Label(0, "", "") + "," + Label(0, "", "") + "," +
                         Label(3, "SECOND", Word(0, 7, "b")) + "," +
                         Label(4, "FIRST", Word(0, 7, "dup"));
            var f = MsbtJsonReader.Parse(Doc(File("german_demo", 5, labels)))[0];
            Assert.AreEqual(5, f.Labels.Count);
            Assert.IsTrue(f.Labels[1].IsPadding);
            Assert.IsFalse(f.Labels[0].IsPadding);
            Assert.AreEqual(2, f.LabelCount, "verschiedene Namen ohne Auffüll-Einträge");
            Assert.IsTrue(f.TryGetLabel("SECOND", out var second));
            Assert.AreEqual(3, second.LabelIndex);
            Assert.IsTrue(f.TryGetLabel("FIRST", out var first));
            Assert.AreEqual("a", first.Words[0].Text);
            Assert.IsTrue(f.TryGetLabel(3, out var byIndex));
            Assert.AreEqual("SECOND", byIndex.Name);
            Assert.IsFalse(f.TryGetLabel("second", out _), "Namen sind groß-/kleinschreibungsempfindlich");
            Assert.IsFalse(f.TryGetLabel("MISSING", out _));
            Assert.IsFalse(f.TryGetLabel((string)null, out _));
        }

        [Test]
        public void ShortNameDropsLanguagePrefix()
        {
            Assert.AreEqual("ss_bag", new MsbtFile { Name = "german_ss_bag" }.ShortName);
            Assert.AreEqual("ss_bag", new MsbtFile { Name = "jpn_kanji_ss_bag" }.ShortName);
            Assert.AreEqual("other", new MsbtFile { Name = "other" }.ShortName);
        }

        // --- Sprachen ---

        [Test]
        public void LanguageTablesCoverAllNineLanguages()
        {
            var expected = new[]
            {
                (MessageLanguage.Jpn, "jpn", "jpn_", "jp", "jpn_font"),
                (MessageLanguage.Usa, "english", "english_", "en", "efigs_font"),
                (MessageLanguage.Fra, "french", "french_", "fr", "efigs_font"),
                (MessageLanguage.Ita, "italian", "italian_", "it", "efigs_font"),
                (MessageLanguage.Deu, "german", "german_", "ge", "efigs_font"),
                (MessageLanguage.Esp, "spanish", "spanish_", "sp", "efigs_font"),
                (MessageLanguage.Kor, "korean", "korean_", "ko", "kor_font"),
                (MessageLanguage.Sch, "simp_chinese", "simp_", "si", "sch_font"),
                (MessageLanguage.Tch, "trad_chinese", "trad_", "tr", "tch_font"),
            };
            foreach (var (lang, folder, prefix, suffix, font) in expected)
            {
                Assert.AreEqual(folder, MessageLanguages.BundleFolder(lang));
                Assert.AreEqual(prefix, MessageLanguages.FilePrefix(lang));
                Assert.AreEqual(suffix, MessageLanguages.VariantSuffix(lang));
                Assert.AreEqual(font, MessageLanguages.FontBundle(lang));
            }
            Assert.AreEqual("jpn_kanji", MessageLanguages.BundleFolder(MessageLanguage.Jpn, true));
            Assert.AreEqual("jpn_kanji_", MessageLanguages.FilePrefix(MessageLanguage.Jpn, true));
            Assert.AreEqual(5, (int)MessageLanguage.Deu);
            Assert.AreEqual(7, (int)MessageLanguage.Esp);
            Assert.Throws<ArgumentOutOfRangeException>(() => MessageLanguages.BundleFolder((MessageLanguage)6));
        }

        [Test]
        public void EfigsFlagMatchesFiveLanguages()
        {
            Assert.IsTrue(MessageLanguages.IsEfigs(MessageLanguage.Deu));
            Assert.IsTrue(MessageLanguages.IsEfigs(MessageLanguage.Usa));
            Assert.IsFalse(MessageLanguages.IsEfigs(MessageLanguage.Jpn));
            Assert.IsFalse(MessageLanguages.IsEfigs(MessageLanguage.Kor));
        }

        [Test]
        public void SystemLanguageMapping()
        {
            Assert.AreEqual(MessageLanguage.Jpn, MessageLanguages.FromSystemLanguage(0));
            Assert.AreEqual(MessageLanguage.Usa, MessageLanguages.FromSystemLanguage(1));
            Assert.AreEqual(MessageLanguage.Deu, MessageLanguages.FromSystemLanguage(3));
            Assert.AreEqual(MessageLanguage.Kor, MessageLanguages.FromSystemLanguage(7));
            Assert.AreEqual(MessageLanguage.Sch, MessageLanguages.FromSystemLanguage(15));
            Assert.AreEqual(MessageLanguage.Tch, MessageLanguages.FromSystemLanguage(16));
            Assert.AreEqual(MessageLanguage.Usa, MessageLanguages.FromSystemLanguage(99), "unbekannt: Englisch");
        }

        [Test]
        public void SplitFileNameFindsLongestPrefixFirst()
        {
            Assert.IsTrue(MessageLanguages.TrySplitFileName("jpn_kanji_ss_x", out var l1, out var k1, out var s1));
            Assert.AreEqual((MessageLanguage.Jpn, true, "ss_x"), (l1, k1, s1));
            Assert.IsTrue(MessageLanguages.TrySplitFileName("jpn_ss_x", out var l2, out var k2, out var s2));
            Assert.AreEqual((MessageLanguage.Jpn, false, "ss_x"), (l2, k2, s2));
            Assert.IsTrue(MessageLanguages.TrySplitFileName("simp_dp_y", out var l3, out _, out var s3));
            Assert.AreEqual((MessageLanguage.Sch, "dp_y"), (l3, s3));
            Assert.IsFalse(MessageLanguages.TrySplitFileName("german_", out _, out _, out _), "Präfix ohne Namen");
            Assert.IsFalse(MessageLanguages.TrySplitFileName("klingon_x", out _, out _, out _));
            Assert.IsFalse(MessageLanguages.TrySplitFileName(null, out _, out _, out _));
        }

        // --- Bank ---

        [Test]
        public void BankSeparatesLanguagesAndKanji()
        {
            var json = Doc(
                File("german_ss_demo", 5, Label(0, "L", Word(0, 7, "de"))),
                File("english_ss_demo", 2, Label(0, "L", Word(0, 7, "en"))),
                File("jpn_ss_demo", 1, Label(0, "L", Word(0, 7, "kana"))),
                File("jpn_kanji_ss_demo", 1, Label(0, "L", Word(0, 7, "kanji")), false, true),
                File("odd_name", 4, Label(0, "L", Word(0, 7, "it"))));
            var bank = new MessageBank();
            bank.AddRange(MsbtJsonReader.Parse(json));
            Assert.AreEqual(5, bank.FileCount);
            Assert.IsTrue(bank.TryGetLabel("ss_demo", "L", MessageLanguage.Deu, out var de));
            Assert.AreEqual("de", de.Words[0].Text);
            Assert.IsTrue(bank.TryGetLabel("ss_demo", "L", MessageLanguage.Usa, out var en));
            Assert.AreEqual("en", en.Words[0].Text);
            Assert.IsTrue(bank.TryGetLabel("ss_demo", 0, MessageLanguage.Jpn, out var kana));
            Assert.AreEqual("kana", kana.Words[0].Text);
            Assert.IsTrue(bank.TryGetLabel("ss_demo", "L", MessageLanguage.Jpn, out var kanji, true));
            Assert.AreEqual("kanji", kanji.Words[0].Text);
            Assert.IsTrue(bank.TryGetLabel("odd_name", "L", MessageLanguage.Ita, out _), "unbekanntes Präfix: Sprache aus langID");
            Assert.IsFalse(bank.TryGetFile("ss_demo", MessageLanguage.Fra, out _));
            Assert.IsFalse(bank.TryGetLabel("ss_demo", "NOPE", MessageLanguage.Deu, out _));
        }

        [Test]
        public void BankRejectsDuplicatesAndNull()
        {
            var bank = new MessageBank();
            var f = MsbtJsonReader.Parse(Doc(File("german_a", 5, "")))[0];
            bank.Add(f);
            Assert.Throws<ArgumentException>(() => bank.Add(MsbtJsonReader.Parse(Doc(File("german_a", 5, "")))[0]));
            Assert.Throws<ArgumentNullException>(() => bank.Add(null));
        }

        // --- Zusammensetzen ---

        [Test]
        public void ComposeSimpleLabelGivesOneEndLine()
        {
            var m = new MessageComposer().Compose(LabelOf(Word(0, 0, "Guten ", -1, 0, 40) + "," + Word(0, 7, "Tag", -1, 0, 25)));
            Assert.AreEqual(1, m.Lines.Count);
            Assert.AreEqual("Guten Tag", m.Lines[0].Text);
            Assert.AreEqual(MessageEvent.End, m.Lines[0].EndEvent);
            Assert.AreEqual(65f, m.Lines[0].StaticWidth, 1e-4);
            Assert.AreEqual("Guten Tag", m.FlatText);
        }

        [Test]
        public void ComposeSplitsAtEventsAndKeepsValues()
        {
            var words = string.Join(",",
                Word(7, 1, "eins"),
                Word(7, 4, "zwei"),
                Word(7, 2, "drei", -1, 0.2),
                Word(7, 5, "vier", -1, 3),
                Word(7, 3, "fünf"),
                Word(0, 7, "sechs"));
            var m = new MessageComposer().Compose(LabelOf(words));
            Assert.AreEqual(6, m.Lines.Count);
            CollectionAssert.AreEqual(
                new[] { MessageEvent.NewLine, MessageEvent.ScrollLine, MessageEvent.Wait, MessageEvent.CallBack, MessageEvent.ScrollPage, MessageEvent.End },
                m.Lines.ConvertAll(l => l.EndEvent));
            Assert.AreEqual(0.2f, m.Lines[2].EventValue, 1e-6);
            Assert.AreEqual(3f, m.Lines[3].EventValue, 1e-6);
            Assert.AreEqual("eins\nzwei\ndreivierfünf\fsechs", m.FlatText);
        }

        [Test]
        public void ComposeSubstitutesTagsFromBuffer()
        {
            var tags = Tag(2, 1, 0, TagPattern.Word) + "," + Tag(5, 1, 9, TagPattern.Word);
            var words = Word(0, 0, "Hi ") + "," + Word(5, 0, "", 0) + "," + Word(0, 0, " und ") + "," + Word(5, 0, "", 1) + "," + Word(0, 7, "!");
            var label = LabelOf(words, tags);
            var buffer = new TagWordBuffer();
            buffer.SetText(2, "Alex");
            buffer.SetText(5, "Trank");
            Assert.AreEqual("Hi Alex und Trank!", new MessageComposer().Compose(label, buffer).FlatText);
        }

        [Test]
        public void ComposeShowsVisiblePlaceholderForMissingValues()
        {
            var label = LabelOf(Word(5, 7, "", 0), Tag(4, 1, 7, TagPattern.Word));
            Assert.AreEqual("{1:7}", new MessageComposer().Compose(label).FlatText);
        }

        [Test]
        public void ComposeCountsInvalidTagReferences()
        {
            var label = LabelOf(Word(5, 0, "", 3) + "," + Word(5, 0, "", -1) + "," + Word(0, 7, "x"));
            var m = new MessageComposer().Compose(label);
            Assert.AreEqual(2, m.InvalidTagReferences);
            Assert.AreEqual("x", m.FlatText);
        }

        [Test]
        public void ComposeKeepsMarkupWordsVerbatim()
        {
            var words = string.Join(",",
                Word(0, 0, "a "), Word(2, 0, "<color=#ff0000>"), Word(0, 0, "rot", -1, 0, 10), Word(2, 0, "</color>"),
                Word(3, 0, "<size=75%>"), Word(0, 0, "klein"), Word(3, 0, "</size>"), Word(4, 0, "<pos=150px>"), Word(0, 7, "|"));
            var m = new MessageComposer().Compose(LabelOf(words));
            Assert.AreEqual("a <color=#ff0000>rot</color><size=75%>klein</size><pos=150px>|", m.Lines[0].Text);
            Assert.AreEqual("a rotklein|", RichText.Strip(m.Lines[0].Text));
            Assert.AreEqual(10f, m.Lines[0].StaticWidth, 1e-4, "nur Wörter mit Breite > 0 zählen");
        }

        [Test]
        public void ComposeAddsEndWhenLabelHasNoTerminalEvent()
        {
            var m = new MessageComposer().Compose(LabelOf(Word(0, 0, "offen")));
            Assert.AreEqual(1, m.Lines.Count);
            Assert.AreEqual(MessageEvent.End, m.Lines[0].EndEvent);
            Assert.AreEqual("offen", m.Lines[0].Text);
        }

        [Test]
        public void ComposeEmptyLabelGivesSingleEmptyEndLine()
        {
            var m = new MessageComposer().Compose(LabelOf(""));
            Assert.AreEqual(1, m.Lines.Count);
            Assert.AreEqual("", m.Lines[0].Text);
            Assert.AreEqual(MessageEvent.End, m.Lines[0].EndEvent);
        }

        [Test]
        public void ComposeEndsWithoutExtraLineAfterTrailingPageBreak()
        {
            var m = new MessageComposer().Compose(LabelOf(Word(7, 3, "seite")));
            Assert.AreEqual(1, m.Lines.Count);
            Assert.AreEqual(MessageEvent.ScrollPage, m.Lines[0].EndEvent);
        }

        [Test]
        public void ComposeUsesCustomFormatter()
        {
            var label = LabelOf(Word(5, 7, "", 0), Tag(0, 9, 9, TagPattern.Conversion));
            var m = new MessageComposer(new FixedFormatter("<<" + 1 + ">>")).Compose(label);
            Assert.AreEqual("<<1>>", m.FlatText);
            Assert.Throws<ArgumentNullException>(() => new MessageComposer().Compose(null));
        }

        sealed class FixedFormatter : ITagFormatter
        {
            readonly string _s;
            public FixedFormatter(string s) { _s = s; }
            public string Format(MsbtTag tag, TagWordBuffer buffer) => _s;
        }

        // --- Platzhalter ---

        [Test]
        public void DigitTagsFormatWithSeparators()
        {
            var f = new DefaultTagFormatter();
            var b = new TagWordBuffer();
            b.SetNumber(0, 1234567);
            Assert.AreEqual("1234567", f.Format(new MsbtTag { Index = 0, Pattern = TagPattern.Digit, Parameter = 0 }, b));
            Assert.AreEqual("1,234,567", f.Format(new MsbtTag { Index = 0, Pattern = TagPattern.Digit, Parameter = 2 }, b));
            Assert.AreEqual("1.234.567", f.Format(new MsbtTag { Index = 0, Pattern = TagPattern.Digit, Parameter = 3 }, b));
            Assert.AreEqual("1 234 567", f.Format(new MsbtTag { Index = 0, Pattern = TagPattern.Digit, Parameter = 4 }, b));
            Assert.AreEqual("1\u202F234\u202F567", f.Format(new MsbtTag { Index = 0, Pattern = TagPattern.Digit, Parameter = 5 }, b));
            b.SetNumber(1, 123456);
            Assert.AreEqual("123,456", f.Format(new MsbtTag { Index = 1, Pattern = TagPattern.Digit, Parameter = 2 }, b));
            b.SetNumber(2, 999);
            Assert.AreEqual("999", f.Format(new MsbtTag { Index = 2, Pattern = TagPattern.Digit, Parameter = 2 }, b));
            b.SetNumber(3, -4500);
            Assert.AreEqual("-4,500", f.Format(new MsbtTag { Index = 3, Pattern = TagPattern.Digit, Parameter = 2 }, b));
            b.SetNumber(4, 0);
            Assert.AreEqual("0", f.Format(new MsbtTag { Index = 4, Pattern = TagPattern.Digit, Parameter = 2 }, b));
        }

        [Test]
        public void GrammarWordsFollowGenderSourceOrCount()
        {
            var f = new DefaultTagFormatter();
            var b = new TagWordBuffer { UserGender = 1, TvGender = 0, UserPartyGender = 1 };
            var words = new[] { "er", "sie", "es" };
            Assert.AreEqual("sie", f.Format(new MsbtTag { Index = 0, Pattern = TagPattern.GrammarWord, Parameter = TagParameterRef.User, Words = words }, b));
            Assert.AreEqual("er", f.Format(new MsbtTag { Index = 0, Pattern = TagPattern.GrammarWord, Parameter = TagParameterRef.Tv, Words = words }, b));
            Assert.AreEqual("sie", f.Format(new MsbtTag { Index = 0, Pattern = TagPattern.GrammarWord, Parameter = TagParameterRef.UserParty, Words = words }, b));
            b.UserGender = 2;
            Assert.AreEqual("es", f.Format(new MsbtTag { Index = 0, Pattern = TagPattern.GrammarWord, Parameter = TagParameterRef.User, Words = words }, b));
            b.UserGender = 9;
            Assert.AreEqual("es", f.Format(new MsbtTag { Index = 0, Pattern = TagPattern.GrammarWord, Parameter = TagParameterRef.User, Words = words }, b), "zu große Auswahl wird begrenzt");

            b.Set(6, new TagWord { Text = "Wort", Count = 1 });
            Assert.AreEqual("ein", f.Format(new MsbtTag { Index = 6, Pattern = TagPattern.GrammarWord, Words = new[] { "ein", "mehrere" } }, b));
            b.Set(6, new TagWord { Text = "Wort", Count = 3 });
            Assert.AreEqual("mehrere", f.Format(new MsbtTag { Index = 6, Pattern = TagPattern.GrammarWord, Words = new[] { "ein", "mehrere" } }, b));
            Assert.AreEqual("{22:5}", f.Format(new MsbtTag { GroupId = 22, TagId = 5, Pattern = TagPattern.GrammarWord }, b), "ohne Wörter: Platzhalter");
        }

        [Test]
        public void FormatterRejectsNullAndUnknownPatterns()
        {
            var f = new DefaultTagFormatter();
            Assert.Throws<ArgumentNullException>(() => f.Format(null, new TagWordBuffer()));
            Assert.Throws<ArgumentNullException>(() => f.Format(new MsbtTag(), null));
            Assert.AreEqual("{50:2}", f.Format(new MsbtTag { GroupId = 50, TagId = 2, Pattern = TagPattern.SpriteFont }, new TagWordBuffer()));
            Assert.AreEqual("{1:2}", f.Format(new MsbtTag { Index = 99, GroupId = 1, TagId = 2, Pattern = TagPattern.Word }, new TagWordBuffer()));
        }

        [Test]
        public void TagWordBufferChecksBoundsAndClears()
        {
            var b = new TagWordBuffer();
            Assert.AreEqual(19, TagWordBuffer.Size);
            Assert.IsFalse(b.IsSet(18));
            b.SetText(18, "x");
            Assert.IsTrue(b.IsSet(18));
            Assert.AreEqual("x", b.Get(18).Text);
            b.Clear();
            Assert.IsFalse(b.IsSet(18));
            Assert.Throws<ArgumentOutOfRangeException>(() => b.Set(19, new TagWord()));
            Assert.Throws<ArgumentOutOfRangeException>(() => b.Get(-1));
        }

        // --- Rich-Text ---

        [Test]
        public void RichTextStripAndCount()
        {
            Assert.AreEqual("ab", RichText.Strip("<color=#fff>a</color><size=50%>b</size>"));
            Assert.AreEqual(2, RichText.CountGlyphs("<color=#fff>a</color><size=50%>b</size>"));
            Assert.AreEqual(1, RichText.CountGlyphs("\U0001F600"), "Surrogatpaar zählt einfach");
            Assert.AreEqual(0, RichText.CountGlyphs(""));
            Assert.AreEqual(0, RichText.CountGlyphs(null));
            Assert.AreEqual("", RichText.Strip(null));
        }

        [Test]
        public void RichTextLeavesUnknownAngleBracketsAlone()
        {
            Assert.AreEqual("a < b > c", RichText.Strip("a < b > c"));
            Assert.AreEqual("<foo>x", RichText.Strip("<foo>x"));
            Assert.AreEqual("<color=#fff", RichText.Strip("<color=#fff"), "unvollständiges Markup bleibt Text");
            Assert.AreEqual(0, RichText.MarkupLength("<color=<x>", 0));
            Assert.AreEqual("<pos=150px>".Length, RichText.MarkupLength("<pos=150px>x", 0));
            Assert.AreEqual("</line-indent>".Length, RichText.MarkupLength("</line-indent>", 0));
        }

        [Test]
        public void RichTextTakeGlyphsKeepsSurroundingMarkup()
        {
            const string s = "<color=#fff>ab</color>cd";
            Assert.AreEqual("<color=#fff>", RichText.TakeGlyphs(s, 0));
            Assert.AreEqual("<color=#fff>a", RichText.TakeGlyphs(s, 1));
            Assert.AreEqual("<color=#fff>ab</color>", RichText.TakeGlyphs(s, 2));
            Assert.AreEqual(s, RichText.TakeGlyphs(s, 4));
            Assert.AreEqual(s, RichText.TakeGlyphs(s, 99));
            Assert.AreEqual("", RichText.TakeGlyphs(s, -1));
            Assert.AreEqual("\U0001F600", RichText.TakeGlyphs("\U0001F600x", 1));
        }

        // --- Schreibmaschine ---

        [Test]
        public void TimingDefaultsMatchOriginalConfigValues()
        {
            var c = new MessageTimingConfig();
            Assert.AreEqual(0.06f, c.SecondsFor(MessageSpeed.Slow), 1e-6);
            Assert.AreEqual(0.03f, c.SecondsFor(MessageSpeed.Normal), 1e-6);
            Assert.AreEqual(0.01f, c.SecondsFor(MessageSpeed.Fast), 1e-6);
            Assert.AreEqual(5f, c.FastForward, 1e-6);
            Assert.AreEqual(0.15f, c.ScrollTextDuration, 1e-6);
            Assert.AreEqual(4, c.WaitAfterFinishFrames);
            Assert.Throws<ArgumentOutOfRangeException>(() => c.SecondsFor((MessageSpeed)3));
        }

        [Test]
        public void TypewriterRevealsGlyphsByElapsedTime()
        {
            var line = new ComposedLine { Text = "<color=#fff>abcd</color>" };
            var t = new MessageTypewriter(line, MessageSpeed.Normal);
            Assert.AreEqual(4, t.TotalGlyphs);
            Assert.AreEqual(0, t.VisibleGlyphs);
            t.Advance(0.029f);
            Assert.AreEqual(0, t.VisibleGlyphs);
            t.Advance(0.001f);
            Assert.AreEqual(1, t.VisibleGlyphs);
            Assert.AreEqual("<color=#fff>a", t.VisibleText);
            t.Advance(0.06f);
            Assert.AreEqual(3, t.VisibleGlyphs);
            Assert.IsFalse(t.IsComplete);
            t.Advance(10f);
            Assert.AreEqual(4, t.VisibleGlyphs);
            Assert.IsTrue(t.IsComplete);
            Assert.AreEqual(line.Text, t.VisibleText);
        }

        [Test]
        public void TypewriterFastForwardAndSpeedsDiffer()
        {
            var line = new ComposedLine { Text = "0123456789" };
            var slow = new MessageTypewriter(line, MessageSpeed.Slow);
            var fast = new MessageTypewriter(line, MessageSpeed.Fast);
            var ff = new MessageTypewriter(line, MessageSpeed.Slow);
            slow.Advance(0.3f);
            fast.Advance(0.3f);
            ff.Advance(0.3f, true);
            Assert.AreEqual(5, slow.VisibleGlyphs);
            Assert.AreEqual(10, fast.VisibleGlyphs);
            Assert.AreEqual(10, ff.VisibleGlyphs, "5-fache Beschleunigung: 1,5 s entsprechen 25 Zeichen, begrenzt auf 10");
            Assert.Throws<ArgumentOutOfRangeException>(() => slow.Advance(-1f));
            var done = new MessageTypewriter(line, MessageSpeed.Slow);
            done.Finish();
            Assert.IsTrue(done.IsComplete);
            Assert.Throws<ArgumentNullException>(() => new MessageTypewriter(null, MessageSpeed.Slow));
        }

        [Test]
        public void TypewriterHandlesEmptyLineAndZeroInterval()
        {
            var empty = new MessageTypewriter(new ComposedLine(), MessageSpeed.Slow);
            Assert.IsTrue(empty.IsComplete);
            var cfg = new MessageTimingConfig { SecondsPerChar = new[] { 0f, 0f, 0f } };
            var instant = new MessageTypewriter(new ComposedLine { Text = "abc" }, MessageSpeed.Normal, cfg);
            Assert.AreEqual(3, instant.VisibleGlyphs);
        }

        // --- Ende-zu-Ende mit synthetischer Datei ---

        [Test]
        public void EndToEndFromJsonToTypewriter()
        {
            var labels =
                Label(0, "", "") + "," +
                Label(1, "GREET", Word(0, 0, "Hallo, ", -1, 0, 50) + "," + Word(5, 1, "", 0) + "," + Word(7, 3, "Weiter geht es", -1, 0, 120) + "," + Word(0, 7, "Ende"),
                    Tag(0, 1, 0, TagPattern.Word));
            var bank = new MessageBank();
            bank.AddRange(MsbtJsonReader.Parse(Doc(File("german_demo_talk", 5, labels))));
            Assert.IsTrue(bank.TryGetLabel("demo_talk", "GREET", MessageLanguage.Deu, out var label));
            var buffer = new TagWordBuffer();
            buffer.SetText(0, "Robin");
            var msg = new MessageComposer().Compose(label, buffer);
            Assert.AreEqual(3, msg.Lines.Count);
            Assert.AreEqual("Hallo, Robin", msg.Lines[0].Text);
            Assert.AreEqual(MessageEvent.NewLine, msg.Lines[0].EndEvent);
            Assert.AreEqual("Weiter geht es", msg.Lines[1].Text);
            Assert.AreEqual(MessageEvent.ScrollPage, msg.Lines[1].EndEvent);
            Assert.AreEqual("Ende", msg.Lines[2].Text);
            var tw = new MessageTypewriter(msg.Lines[0], MessageSpeed.Fast);
            tw.Advance(0.05f);
            Assert.AreEqual("Hallo", tw.VisibleText);
        }
    }
}
