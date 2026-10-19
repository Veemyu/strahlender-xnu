using System;

namespace Xnu.Battle.Flow
{
    // Die Skriptklassen Strong/Expert/Double entstehen beim Bauen aus dem eigenen Dump (scripts/ai_translate)
    // und liegen nicht im Repo. Ohne sie fehlt dem Trainer die jeweilige KI-Stufe, das Spiel baut trotzdem.
    public static class AiGenerated
    {
        public static AiScriptBase Create(string className)
        {
            var type = typeof(AiScriptBase).Assembly.GetType("Xnu.Battle.Flow." + className);
            return type == null ? null : (AiScriptBase)Activator.CreateInstance(type);
        }

        public static bool Available(string className) => typeof(AiScriptBase).Assembly.GetType("Xnu.Battle.Flow." + className) != null;
    }
}
