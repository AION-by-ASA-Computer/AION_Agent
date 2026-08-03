---
name: memory_protocol
description: Come e quando l'agente usa memory_note, memory_wake, memory_recall, memory_forget
tags: [memory, ltm]
status: verified
source: curated
version: 1
---

# Memory Protocol (Mnemos)

## Tool disponibili

- **memory_wake** — richiamato automaticamente a inizio sessione dal server; non
  serve chiamarlo salvo quando vuoi rileggere il contesto per uno scope diverso
  (es. cambio di progetto attivo).
- **memory_recall(query, scope?, mode?)** — ricerca testuale su note Mnemos. Default `scope=auto`
  (user + progetto attivo). Usa per fatti/lezioni già memorizzati (es. caratteristiche prodotti).
  **Non** usare `session_search` per questo — quello cerca solo trascrizioni di chat passate.
- **memory_note(text, scope?, category?, importance?)** — usalo quando l'utente
  chiede esplicitamente di ricordare qualcosa ORA nello stesso turno.
  Il server assegna automaticamente `seq` (ordine append-only per scope): **non**
  passare né inventare numeri di sequenza. Per più fatti, chiama `memory_note`
  più volte (anche nello stesso turno); il server serializza gli insert.
- **memory_forget(note_id)** — solo su richiesta esplicita di correzione/cancellazione.

## Scope

Lo scope (`user` / `project` / `global`) è impostato automaticamente dal server in base
al progetto attivo nella conversazione.

## Due layer sullo stesso progetto

| Layer | Tool | Contenuto |
|-------|------|-----------|
| SQL QueryMemory | `sql_memory_*` | Query SELECT validate, fingerprint SQL |
| Mnemos LTM | `memory_*` | Lezioni, pitfall, decisioni, preferenze |

## Cosa NON salvare manualmente

Query SQL (Query Memory), dump di schema, errori di tool transitori,
cronologia già coperta dal salvataggio automatico di fine turno.
