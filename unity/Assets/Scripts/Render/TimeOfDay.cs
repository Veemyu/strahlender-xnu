using System;

namespace Xnu.Render
{
    public enum PeriodOfDay { Morning = 0, Daytime = 1, Evening = 2, Night = 3, Midnight = 4 }

    // Tageszeit des Spiels: GameManager.get_elapsedTimeOfDay / get_currentPeriodOfDay / get_currentPeriodOfDayEx
    // (Herleitung in docs/shader-globals.md, Abschnitt 3). Rein, ohne UnityEngine.
    public static class TimeOfDay
    {
        public const long TicksPerDay = 864000000000L;

        // Uhrzeit in Stunden [0, 24): ((Versatz + Skala · (jetzt mod Tag)) mod Tag) / Tag · 24.
        // Die Quellwerte (Systemuhr, GameManager.tickOffset, timeScale) liefert das Spiel.
        public static float ElapsedHours(long nowTicks, long tickOffset, long timeScale)
        {
            var t = (tickOffset + timeScale * (nowTicks % TicksPerDay)) % TicksPerDay;
            return (float)t / 8.64e11f * 24.0f;
        }

        public static PeriodOfDay CurrentPeriod(float hours)
        {
            if (hours < 2.0f) return PeriodOfDay.Night;
            if (hours < 4.0f) return PeriodOfDay.Midnight;
            if (hours < 10.0f) return PeriodOfDay.Morning;
            if (hours < 17.0f) return PeriodOfDay.Daytime;
            return hours < 20.0f ? PeriodOfDay.Evening : PeriodOfDay.Night;
        }

        // (Abschnitt, Fortschritt im Abschnitt 0..1, Überblendgewicht zum nächsten Abschnitt 0..1).
        // Das Gewicht steigt nur in den letzten 10 Minuten jedes Abschnitts von 0 auf 1.
        public static (PeriodOfDay period, float progress, float weight) CurrentPeriodEx(float hours)
        {
            PeriodOfDay period;
            float p, minutes;
            if (hours < 2.0f) { period = PeriodOfDay.Night; p = (hours + 4.0f) / 6.0f; minutes = 360.0f; }
            else if (hours < 4.0f) { period = PeriodOfDay.Midnight; p = (hours - 2.0f) * 0.5f; minutes = 120.0f; }
            else if (hours < 10.0f) { period = PeriodOfDay.Morning; p = (hours - 4.0f) / 6.0f; minutes = 360.0f; }
            else if (hours < 17.0f) { period = PeriodOfDay.Daytime; p = (hours - 10.0f) / 7.0f; minutes = 420.0f; }
            else if (hours < 20.0f) { period = PeriodOfDay.Evening; p = (hours - 17.0f) / 3.0f; minutes = 180.0f; }
            else { period = PeriodOfDay.Night; p = (hours - 20.0f) / 6.0f; minutes = 360.0f; }
            var w = Math.Max((p * minutes - (minutes - 10.0f)) * 0.1f, 0.0f);
            return (period, p, w);
        }

        public static PeriodOfDay Next(PeriodOfDay p) => (PeriodOfDay)(((int)p + 1) % 5);
        public static PeriodOfDay Previous(PeriodOfDay p) => (PeriodOfDay)(((int)p + 4) % 5);
    }
}
