namespace Xnu.Battle.Flow
{
    // ActPri: 32-Bit-Sortierschluessel einer Aktion (Spezifikation 4, Abschnitt 3). Groesser = frueher.
    // Bits 25-27 Vorrang (Unterbrechungen), 22-24 Aktionsart, 16-21 Attackenprioritaet (+7), 13-15 Sonderprioritaet, 0-12 Initiative.
    public static class ActPri
    {
        public static uint Make(uint dominant, uint operation, uint wazaPri, uint spPri, uint agility)
            => (dominant & 7) << 25 | (operation & 7) << 22 | (wazaPri & 0x3F) << 16 | (spPri & 7) << 13 | agility & 0x1FFF;

        public static uint ChangeAgility(uint pri, uint agility) => pri & 0xFFFFE000 | agility & 0x1FFF;

        public static uint ChangeWazaPriority(uint pri, uint wazaPri) => pri & 0xFFC00000 | pri & 0xFFFF | (wazaPri & 0x3F) << 16;

        public static uint GetWazaPri(uint pri) => pri >> 16 & 0x3F;

        public static uint GetSpPri(uint pri) => pri >> 13 & 7;

        public static uint GetOperationPri(uint pri) => pri >> 22 & 7;

        public static uint GetDominantPri(uint pri) => pri >> 25 & 7;

        public static uint SetDominantPri(uint pri, uint dominant) => pri & 0xF0000000 | pri & 0x1FFFFFF | (dominant & 7) << 25;

        public static uint SetSpPri(uint pri, uint spPri) => pri & 0xFFFF0000 | pri & 0x1FFF | (spPri & 7) << 13;

        public static uint ToHandlerPri(uint pri) => pri & 0x3FFFFF;

        public static int ToWazaOrgPri(uint pri) => (int)(pri >> 16 & 0x3F) - 7;
    }

    // BtlAction des Originals.
    public enum ActionKind
    {
        Null = 0,
        Fight = 1,
        Item = 2,
        Change = 3,
        Escape = 4,
        Skip = 5,
        GStart = 6,
        Cheer = 7,
        RecplayTimeover = 8,
        RecplayError = 9,
    }

    // BtlSpecialPri: Sonderprioritaet innerhalb gleicher Attackenprioritaet (Vorlaeufer-/Nachzuegler-Items und Faehigkeiten).
    public static class SpecialPri
    {
        public const uint Low = 0;
        public const uint Default = 1;
        public const uint High = 2;
    }
}
