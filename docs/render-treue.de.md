# Render-Treue: 1:1-Ziel (Stand 2026-10-18)

**Vorgabe des Nutzers:** Shader und Effekte müssen **1:1** wie im Original aussehen. Annäherungen reichen nicht.

## Gemessene Eigenschaften des Originals (aus `globalgamemanagers`, nur gelesen)
| Einstellung | Wert im Original |
|---|---|
| Render-Pipeline | **Built-in** (`m_CustomRenderPipeline` leer, keine SRP) |
| Farbraum | **Gamma** (`m_ActiveColorSpace` = 0) |
| Qualitätsstufen | genau eine („Ultra“): Schatten an (Stufe 2), Schattenentfernung 20, **kein MSAA**, VSync-Zähler 2 (= jedes zweite Bild, 30 FPS auf der Switch) |
| Lichtintensität | nicht linear, keine Farbtemperatur |
| GPU-Skinning | an |
| Standard-Fenster | 1024 × 768 (nur Standard, nicht die Switch-Auflösung) |

## Folgerung für die Pipeline
- Wegen der Treue wird **die Built-in-Pipeline** eingesetzt, nicht URP. Die Original-Shader und ihre Beleuchtung gehen von Unitys Built-in-Konventionen (Constant Buffer, Licht, Nebel, Schatten) aus. Mit URP würde sich Beleuchtung und Schatten ändern.
- **Gamma-Farbraum** wie im Original, kein MSAA, kein HDR-Display.
- Risiko (nicht geprüft): Unity kündigt für die Built-in-Pipeline in späteren Versionen das Auslaufen an. Wir pinnen Unity 6.3 LTS und prüfen die Supportdauer.

## Was „1:1“ für die Shader bedeutet
- Die Bundles `Dpr/shaders` (63 Shader) und `Effects/fxparticle` (1 Shader) enthalten nur Switch-Binärcode (Plattform 19) und die geparsten ShaderLab-Daten (Eigenschaften, Passes, Render-States, Tags). Quelltext existiert nicht (`shader-audio-machbarkeit.md`).
- Der **Ryujinx-Cache** enthält dieselben Programme als SPIR-V (5.937 Module, 2.971 Einträge). Das ist die genaueste verfügbare Beschreibung des Verhaltens, weil Ryujinx sie aus dem Switch-Binärcode erzeugt hat. `spirv-cross` übersetzt alle 5.932 Grafikmodule nach MSL.
- Ziel: ein **treuer Port** je Shader (Eigenschaften, Passes, Render-States aus den geparsten Daten; Programmlogik aus SPIR-V), keine neu erfundenen Look-Alikes.
- **Prüfverfahren (differenziell):** Dasselbe Eingabeset (Vertexdaten, Constant Buffer, Texturen) durch das Referenzprogramm (SPIR-V→MSL in einem kleinen Metal-Testprogramm) und durch den portierten Unity-Shader schicken, Ergebnisse pixelweise vergleichen. Zusätzlich Referenzbilder aus Ryujinx, falls der Nutzer welche erzeugt.
- Offen: Wie bilden wir die Constant-Buffer-Layouts der Switch-Shader auf Unity 6 ab? Sie folgen Unity 2019.4; wir müssen die Werte pro Material und Frame selbst liefern. Das ist der aufwendigste Teil und noch nicht untersucht.

## Effekte
Partikel (Bundle `fxparticle`, `Effects/*`), Timeline-Sequenzen und Post-Effekte (Bloom, Tiefenunschärfe) müssen zeitlich und optisch stimmen. Auch dafür gilt die differenzielle Prüfung (feste Zeitpunkte, feste Kamera, Bildvergleich).

## Audio-Vorgabe (Nutzer)
Alle Geräte stehen auf **lautlos und Lautstärke 0 %**. Wir fassen Gerätelautstärke nie an und erzeugen nie Ton. Als Sicherung ist die App standardmäßig **stumm** (`AudioSafety`, Editor-Mute), aktivierbar nur über das Compile-Symbol `XNU_ALLOW_AUDIO`.
