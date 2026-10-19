// Muster der Bruecke zwischen Logik (Assembly mit asmdef, hier Xnu.Bridge) und den generierten Stubs in Assembly-CSharp.
// Assembly-CSharp darf autoReferenced-asmdef-Assemblies verwenden, die Gegenrichtung gibt es nicht. Deshalb liegen
// Schnittstellen und Logik in der asmdef-Assembly; ein handgeschriebener partial-Teil jedes Stubs (Assembly-CSharp)
// implementiert die Schnittstelle und meldet sich in Awake/OnEnable/OnDestroy an der Logik an.
using System.Collections.Generic;

namespace Xnu.Bridge
{
    /// <summary>Wird von handgeschriebenen partial-Teilen der Stubs implementiert (Assembly-CSharp).</summary>
    public interface IBridgeHost
    {
        /// <summary>Anzahl der im Stub deklarierten Instanzfelder (nur fuer den Test).</summary>
        int BridgeFieldCount { get; }
    }

    /// <summary>Logikseite: kennt nur die Schnittstelle, nie die Stub-Klassen.</summary>
    public static class BridgeHub
    {
        public static readonly List<IBridgeHost> Hosts = new List<IBridgeHost>();
        public static int Notified;

        public static void Attach(IBridgeHost host) { Notified++; Hosts.Add(host); }
        public static void Detach(IBridgeHost host) { Hosts.Remove(host); }

        public static int SumFields(IEnumerable<IBridgeHost> hosts)
        {
            int n = 0;
            foreach (var h in hosts) n += h.BridgeFieldCount;
            return n;
        }
    }
}
