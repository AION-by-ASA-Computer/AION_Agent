---
title: Long Run mode & Consolidamento Nativo
sidebar_position: 13
description: "Consolidamento della modalità Long Run: transizione dall'architettura con worker esterno Pi Agent all'esecuzione nativa unificata in AION."
---

# Long Run Mode & Consolidamento Nativo

> [!NOTE]
> **Consolidamento Completato**: La modalità di esecuzione per task lunghi e multi-step è ora **completamente gestita dal runtime nativo di AION** (Harness V2 / Haystack).
>
> Il worker esterno Node.js (`services/pi-long-run`) è stato dismesso in favore di un'architettura unificata in Python che offre prestazioni superiori, minore latenza e persistenza integrata.

---

## Architettura Unificata

Tutti i requisiti per sessioni complesse e di lunga durata sono integrati nel backend nativo:

- **Esecuzione In-Process:** Nessun round-trip di rete extra verso processi Node.js intermedi.
- **Context Offloading (L1):** Output di tool voluminosi salvati automaticamente su file (`src/runtime/tool_offload.py`).
- **Tool Ledger (L2):** Storico sintetico delle azioni iniettato nel contesto (`src/runtime/tool_ledger.py`).
- **Circuit Breaker:** Protezione nativa anti-loop su errori ripetuti (`src/runtime/tool_circuit.py`).
- **Compattazione Dinamica:** Sintesi automatica del contesto con preservazione dei cut-point (`src/memory/context_compressor.py`).

---

## Documenti Correlati

- [Valutazione Tecnica e Consolidamento](./aion-vs-longrun-assessment.md)
- [AION Harness v2](./aion-harness-v2.md)
- [Context Compaction](../memory/context-compaction.md)
- [Context Offloading](./context-offloading.md)
