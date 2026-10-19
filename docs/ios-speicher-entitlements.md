# iPadOS: Speicher-Entitlements und Adressraum (Recherche 2026-10-18)

Zweck: Entscheidungsgrundlage für `ap-ipad-perf` und `ap-recomp-feasibility`. Quellen sind verlinkt, Sicherheit steht je Aussage dabei. Das ist keine Rechtsberatung und kein Messergebnis auf unserem Gerät.

## Befunde
| Frage | Befund | Sicherheit |
|---|---|---|
| **Extended Virtual Addressing** (`com.apple.developer.kernel.extended-virtual-addressing`) | Boolesches Entitlement für einen erweiterten Adressraum, Beispiel bei Apple: Spiele, die Assets per Memory-Map für die GPU streamen. Verfügbar ab iOS, iPadOS und tvOS 14.0, macOS nicht gelistet. Capability in Xcode: „Extended Virtual Addressing“. | belegt |
| EVA mit **kostenlosem Team** | In Apples Tabelle „Supported capabilities (iOS)“ nur für das bezahlte Programm (ADP) und Enterprise, in der Spalte für kostenlose Accounts leer. | belegt (Tabelle gelesen) |
| Adressraumgröße ohne/mit EVA | Apple nennt keine Zahl. | nicht verifiziert |
| **Increased Memory Limit** (`com.apple.developer.kernel.increased-memory-limit`) | Erlaubt, das Standardlimit auf unterstützten Geräten zu überschreiten, ab iOS/iPadOS 15.0. Der reale Wert kommt aus `os_proc_available_memory()`. | belegt |
| Increased Memory Limit mit kostenlosem Team | Steht nicht in Apples Tabelle. **Beobachtet (Nutzer, 2026-10-18):** Die Capability lässt sich mit dem kostenlosen Personal Team in Xcode hinzufügen, die App baut, wird signiert und läuft auf dem iPad Pro (M2, iPadOS 26.4.2). Der erreichte Speicherwert ist gemessen: 8192 MiB statt 5120 MiB ohne Entitlement (`docs/ipad-messung-1.md`). | beobachtet und gemessen (widerlegt die frühere Vermutung „eher unwahrscheinlich“) |
| **Increased Debugging Memory Limit** | Nur für Entwicklung, Ad hoc und TestFlight intern, vor der Verteilung zu entfernen. Nur für ADP/Enterprise gelistet. | belegt |
| Jetsam-Limit ohne Entitlement | Ein Nutzerbericht nennt etwa 5 GB auf M1-iPads. **Gemessen auf dem iPad Pro M2 (8 GB): 5120 MiB** (`docs/ipad-messung-1.md`). | gemessen |
| Fester Multi-GB-Bereich (z. B. 12,5 GB bei `0x70_0000_0000`) ohne EVA | Kein Beleg, dass das geht. Ein Test auf einem iPhone 17 Pro zeigt `mmap` ohne Entitlement scheitert mit „Cannot allocate memory“, mit EVA oder Increased Memory Limit läuft es (Einzelbericht). Ältere iOS-Versionen erlaubten nur einen schmalen Bereich. | vermutet, einzelner Bericht |
| macOS | Eigener, großzügigerer Pfad plausibel, Apple-Quelle dafür nicht gefunden. | nicht verifiziert |

## Quellen
- EVA: https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.kernel.extended-virtual-addressing
- Capability-Tabelle: https://developer.apple.com/help/account/reference/supported-capabilities-ios/
- Increased Memory Limit: https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.kernel.increased-memory-limit
- Debugging-Limit: https://developer.apple.com/help/glossary/increased-debugging-memory-limit/
- `os_proc_available_memory`: https://developer.apple.com/documentation/os/os_proc_available_memory
- Praxisbericht mmap: https://zenn.dev/mtfum/articles/ios_memory_entitlements?locale=en
- Historischer Adressraum (PPSSPP, 2017): http://blog.henrikrydgard.com/ios-address-space/
- Go-Issue zu iOS-Adressraum: https://github.com/golang/go/issues/46860

## Folgerungen für uns
1. Mit dem kostenlosen Team sind EVA und das Debugging-Limit nach Apples Tabelle nicht verfügbar. **Increased Memory Limit funktioniert laut Nutzer trotzdem** (hinzufügen, signieren, starten). Die Vorgabe aus `goal.md` („no high virtual memory requirements for iOS“) bleibt wegen EVA bestehen.
2. Ein festes 12,5-GB-Gastfenster wie in LASRecomp (`runtime/rt.h`) ist auf dem iPad nicht verlässlich möglich. Eine Rekompilation brauchte Pointer-Rebasing, kleine Fenster oder 32-Bit-Offsets und ein Speicherbudget zur Laufzeit.
3. Der Unity-Weg ist davon weniger betroffen, weil Unity den Speicher normal verwaltet. Dort zählt das Gesamtbudget (Bundles, Texturen) gegen das Jetsam-Limit.
4. Budget zur Laufzeit mit `os_proc_available_memory()` steuern und auf dem echten iPad Pro (M2) messen. Das ist die einzige verlässliche Zahl.
5. **Gemessen (2026-10-19, `docs/ipad-messung-1.md`):** Limit ohne Entitlement 5120 MiB, mit Increased Memory Limit 8192 MiB (`os_proc_available_memory() + phys_footprint`); das Entitlement wirkt auch mit dem kostenlosen Team. Der Post-Build-Schritt `unity/Assets/Scripts/Build/Editor/IosPostBuild.cs` trägt es bei jedem Unity-iOS-Build automatisch ein (Standard an; abschaltbar per Symbol `XNU_NO_INCREASED_MEMORY`).
