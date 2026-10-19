// Speichermodell der BDSP-Laufzeit: eine einzige Stelle, die Gast- in Hostadressen umrechnet.
// Eigener Code.
//
// Variante A (Gate 1, nur Mac): ein festes 12,5-GiB-Fenster bei 0x70_0000_0000, Gastadresse == Hostadresse.
//   G2H(a) = (void *)a, H2G(p) = (uint64_t)p. Der erzeugte Code greift über LD8..ST64 (cpu.h) zu: direkt.
// Variante B (iPad, Gate 2): alle Gastadressen < 4 GiB, ein Fenster bei g_base.
//   G2H(a) = g_base + (uint32_t)a. Der erzeugte Code wird mit -I scripts/recomp/rt32 vor rt/ übersetzt
//   (rt32/cpu.h überschreibt LD*/ST* mit derselben Rechnung), die Module liegen bei Adressen < 4 GiB
//   (gen_all.sh mit anderen Basen), und die Runtime wird mit -DBDSP_REBASE32 gebaut.
//
// Regel für alle Host-Quellen: jede Gastadresse (Register, IPC-Puffer, Tabellen im Gastspeicher) geht durch G2H(),
// jeder Zeiger in den Gastspeicher, der dem Gast zurückgegeben wird, durch H2G(). Keine Umwandlung nach uintptr_t
// außerhalb dieses Headers.
#pragma once
#include <stdint.h>

#ifdef BDSP_REBASE32
extern uint8_t *g_base;  // Basis des 4-GiB-Fensters (derselbe Name wie in rt32/cpu.h, vom Host gesetzt)
#ifndef G2H
#define G2H(a) ((void *)(g_base + (uint32_t)(uint64_t)(a)))
#endif
#define H2G(p) ((uint64_t)((const uint8_t *)(p) - g_base))
#else
#define G2H(a) ((void *)(uintptr_t)(a))
#define H2G(p) ((uint64_t)(uintptr_t)(p))
#endif

#define G2H8(a)  ((uint8_t *)G2H(a))
#define G2H16(a) ((uint16_t *)G2H(a))
#define G2H32(a) ((uint32_t *)G2H(a))
#define G2H64(a) ((uint64_t *)G2H(a))
#define G2HC(a)  ((const char *)G2H(a))
