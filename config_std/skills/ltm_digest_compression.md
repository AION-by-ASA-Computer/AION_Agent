---
name: ltm_digest_compression
description: Prompt di compressione gerarchica note→digest (server-side, automatico)
tags: [memory, internal]
status: verified
source: curated
version: 1
---

# LTM Digest Compression (server-side, automatic)

Ricevi un blocco di elementi consecutivi dello stesso scope — note grezze o
digest già compressi — e li riduci a UNA riga di massimo 500 caratteri.
Rispondi SOLO con JSON: `{"summary": "..."}`.

## Regole

- Mantieni solo ciò che ha effetto duraturo (decisioni, preferenze stabili, fatti).
- Non inventare nulla che non sia nel blocco.
- Ignora le note marcate superseded: conta solo lo stato finale.
- Una riga densa, non un elenco puntato.
