# 🗄️ Agent DB (Structured Autonomous Memory)

Agent DB è il sistema di persistenza strutturata di AION che permette agli agenti di creare, gestire e interrogare database SQLite dedicati per ogni utente in modo autonomo.

## Perché usare Agent DB?

A differenza della memoria semantica (RAG) o del LTM (Long Term Memory) basato su testo, Agent DB offre:
- **Precisione Matematica**: Perfetto per dati contabili, finanziari e tabelle.
- **Query Complesse**: Supporta join, aggregazioni e filtri SQL avanzati.
- **Ispezionabilità**: Gli amministratori possono monitorare la salute dei database dal pannello Admin.

## Come funziona

Ogni utente ha un file `.db` isolato situato in `data/agent_dbs/<tenant_id>/<user_id>.db`. L'agente interagisce con questo database tramite il server MCP `agent_db`.

### Workflow di Ingestion

1. **Upload File**: L'utente carica un Excel o CSV.
2. **Analisi Schema**: L'agente analizza i tipi di dato e propone uno schema SQL.
3. **Persistenza**: I dati vengono inseriti in batch per massimizzare le performance.
4. **Validazione**: Vengono eseguiti check di integrità e foreign key.

## Sicurezza e Approvazioni

Le operazioni distruttive (come `DROP TABLE` o `ALTER TABLE`) sono protette da un sistema di **Security Trust**. 
- Per operazioni critiche, l'agente deve richiedere l'approvazione esplicita dell'utente tramite il DB centrale `aion.db`.
- Le policy di approvazione sono configurabili in `src/data/models.py`.

## Monitoraggio Admin

Accedendo alla sezione **Agent DB** del pannello di controllo, è possibile:
- Visualizzare l'elenco dei database attivi.
- Ispezionare gli schemi (tabelle e colonne).
- Vedere un'anteprima dei dati reali.
- Eseguire un **Integrity Check** per rilevare tabelle orfane o errori di integrità SQLite.
