#!/usr/bin/env python3
"""One-shot: translate Italian agent-facing strings to English (MCP + runtime + tools)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (path relative to ROOT, old, new) — order matters within each file
REPLACEMENTS: list[tuple[str, str, str]] = []


def R(rel: str, old: str, new: str) -> None:
    REPLACEMENTS.append((rel, old, new))


# --- session_sandbox ---
_sb = "mcp_servers_std/session_sandbox/server.py"
R(_sb, "AION_CHAT_SESSION_ID non impostato", "AION_CHAT_SESSION_ID not set")
R(_sb, '"""Elenca file in uploads/', '"""List files under uploads/')
R(_sb, "Errore: subdir deve essere uno tra:", "Error: subdir must be one of:")
R(_sb, 'return f"Errore: {e}"', 'return f"Error: {e}"')
R(
    _sb,
    '"""Legge un file di testo sotto la sessione (limita dimensione)."""',
    '"""Read a text file under the session (size limit)."""',
)
R(_sb, "Errore path:", "Path error:")
R(_sb, 'return "Non è un file."', 'return "Not a file."')
R(_sb, "File troppo grande (max", "File too large (max")
R(_sb, "File scritto con successo in", "File written successfully to")
R(_sb, "Errore durante la scrittura:", "Error while writing:")
R(
    _sb,
    "Modifica chirurgica di un file nel workspace: sostituisce old_string con new_string.",
    "Surgical edit of a workspace file: replace old_string with new_string.",
)
R(
    _sb,
    "OBBLIGATORI (sempre tutti e tre): relative_path, old_string, new_string.",
    "REQUIRED (all three): relative_path, old_string, new_string.",
)
R(
    _sb,
    "Opzionale: replace_all (default false).",
    "Optional: replace_all (default false).",
)
R(
    _sb,
    "- relative_path: path sotto workspace/, es. workspace/script.py",
    "- relative_path: path under workspace/, e.g. workspace/script.py",
)
R(
    _sb,
    "- old_string deve comparire ESATTAMENTE UNA VOLTA nel file (default).",
    "- old_string must appear EXACTLY ONCE in the file (default).",
)
R(
    _sb,
    "- Se compare più volte, usa replace_all=True per sostituire tutte le occorrenze.",
    "- If it appears multiple times, use replace_all=True to replace all occurrences.",
)
R(
    _sb,
    "- Il file originale viene archiviato in workspace/.versions/ prima della modifica.",
    "- The original file is archived in workspace/.versions/ before editing.",
)
R(
    _sb,
    "sandbox_edit_workspace_file opera solo su file sotto workspace/.",
    "sandbox_edit_workspace_file only works on files under workspace/.",
)
R(_sb, "File non trovato:", "File not found:")
R(
    _sb,
    '"""Cerca pattern nei file sotto uploads/',
    '"""Search for a pattern in files under uploads/',
)
R(_sb, "relative_root deve essere uno tra:", "relative_root must be one of:")
R(_sb, "Directory vuota o inesistente", "Empty or missing directory")
R(_sb, "Risultati troncati a", "Results truncated at")
R(_sb, "Affina il pattern.", "Narrow the pattern.")
R(_sb, "Pattern regex non valido:", "Invalid regex pattern:")
R(
    _sb,
    "Usa fixed_string=True per cercare testo letterale.",
    "Use fixed_string=True to search literal text.",
)
R(
    _sb,
    '"""Elenca file che matchano un pattern glob sotto la sessione',
    '"""List files matching a glob pattern under the session',
)
R(
    _sb,
    '"""Legge un chunk di file per righe (file grandi)."""',
    '"""Read a file chunk by line (large files)."""',
)
R(_sb, "argv deve essere una lista non vuota", "argv must be a non-empty list")
R(_sb, "ERRORE: Questo tool è disabilitato.", "ERROR: This tool is disabled.")
R(_sb, "per eseguire codice.", "to run code.")
R(
    _sb,
    "Installa pacchetti PyPI nel venv isolato della sessione",
    "Install PyPI packages into the isolated session venv",
)
R(
    _sb,
    "Non chiedere installazioni manuali all'utente: usa questo tool.",
    "Do not ask the user for manual installs: use this tool.",
)
R(_sb, "Errore validazione:", "Validation error:")
R(
    _sb,
    "Esegue ``python -u <relative_path>`` con working directory = root sessione.",
    "Run ``python -u <relative_path>`` with working directory = session root.",
)
R(_sb, "Usa il Python del **venv sessione**", "Uses the **session venv** Python")
R(_sb, "così valgono i pacchetti installati con", "so packages installed with")
R(
    _sb,
    "Altrimenti l'interprete del processo MCP.",
    "Otherwise the MCP process interpreter.",
)
R(_sb, "Accetta solo path sotto", "Only accepts paths under")
R(_sb, "Argomenti extra vanno in", "Extra arguments go in")
R(
    _sb,
    "Non richiede ``result``: stdout/stderr ed exit code sono nel messaggio di ritorno.",
    "No ``result`` field: stdout/stderr and exit code are in the return message.",
)
R(
    _sb,
    '["non trovato", "non valido", "no such file"]',
    '["not found", "non valido", "no such file"]',
)
R(
    _sb,
    "Assicurati di aver chiamato 'sandbox_write_workspace_file' PRIMA di eseguire lo script.",
    "Make sure you called 'sandbox_write_workspace_file' BEFORE running the script.",
)
R(
    _sb,
    "Assicurati di aver emesso il codice usando un blocco Markdown con metadati (artifact_id) PRIMA della tool call.",
    "Make sure you emitted the code in a Markdown block with metadata (artifact_id) BEFORE the tool call.",
)
R(
    _sb,
    "Assicurati di aver emesso il codice usando il formato <aion_artifact> nella risposta attuale PRIMA della tool call.",
    "Make sure you emitted the code using <aion_artifact> in the current response BEFORE the tool call.",
)
R(_sb, "Errore: {err_msg}\\nSUGGERIMENTO:", "Error: {err_msg}\\nHINT:")

# --- query_memory (key strings) ---
_qm = "mcp_servers_std/query_memory/server.py"
R(
    _qm,
    "[PROMQL CACHE ONLY] Cerca nella cache di query PromQL validate.",
    "[PROMQL CACHE ONLY] Search the validated PromQL query cache.",
)
R(
    _qm,
    "Questo tool è ESCLUSIVAMENTE riservato alle query Prometheus/PromQL —",
    "This tool is EXCLUSIVELY for Prometheus/PromQL queries —",
)
R(
    _qm,
    "NON usarlo per cercare conversazioni passate o memoria generica.",
    "Do NOT use it to search past conversations or generic memory.",
)
R(
    _qm,
    "Per cercare nello storico delle chat, usa `session_search`.",
    "To search chat history, use `session_search`.",
)
R(
    _qm,
    "Per cercare fatti e preferenze, usa `mempalace_search` sul server mempalace.",
    "To search facts and preferences, use `mempalace_search` on the mempalace server.",
)
R(
    _qm,
    "Confronta `request` (linguaggio naturale) con le query PromQL precedentemente salvate",
    "Compare `request` (natural language) with previously saved PromQL queries",
)
R(
    _qm,
    "tramite cosine similarity sugli embeddings. Ritorna i match ordinati per rilevanza.",
    "via cosine similarity on embeddings. Returns matches sorted by relevance.",
)
R(
    _qm,
    "Nessuna query PromQL simile trovata in cache. Procedi con la generazione di una nuova query PromQL.",
    "No similar PromQL query found in cache. Proceed with generating a new PromQL query.",
)
R(
    _qm,
    "Query PromQL trovate in cache (ordinate per rilevanza). Verifica se qualcuna corrisponde alla richiesta:",
    "PromQL queries found in cache (sorted by relevance). Check whether any match the request:",
)
R(_qm, "✅ Verificata", "✅ Verified")
R(_qm, "⏳ Suggerita", "⏳ Suggested")
R(_qm, "  Richiesta:", "  Request:")
R(
    _qm,
    "[PROMQL CACHE ONLY] Salva una query PromQL verificata nella cache per uso futuro.",
    "[PROMQL CACHE ONLY] Save a verified PromQL query to the cache for future use.",
)
R(
    _qm,
    "Questo tool è ESCLUSIVAMENTE per query Prometheus/PromQL —",
    "This tool is EXCLUSIVELY for Prometheus/PromQL queries —",
)
R(
    _qm,
    "NON usarlo per salvare conversazioni, fatti generici o preferenze utente.",
    "Do NOT use it to save conversations, generic facts, or user preferences.",
)
R(
    _qm,
    "Per persistere fatti e preferenze, usa `mempalace_save` sul server mempalace.",
    "To persist facts and preferences, use `mempalace_save` on the mempalace server.",
)
R(
    _qm,
    "Usa is_verified=True solo se la query PromQL ha già prodotto risultati corretti.",
    "Use is_verified=True only if the PromQL query already produced correct results.",
)
R(_qm, "Salvataggio completato correttamente:", "Saved successfully:")
R(_qm, "Errore durante il salvataggio in memoria.", "Error while saving to memory.")
R(
    _qm,
    "[PROMQL CACHE ONLY] Incrementa il contatore di successo di una query PromQL in cache.",
    "[PROMQL CACHE ONLY] Increment the success counter for a cached PromQL query.",
)
R(
    _qm,
    "Usare solo per confermare che una query PromQL ha prodotto risultati corretti.",
    "Use only to confirm a PromQL query produced correct results.",
)
R(
    _qm,
    "Dopo un certo numero di successi la query verrà verificata automaticamente.",
    "After enough successes the query is verified automatically.",
)
R(_qm, "Successo registrato per la query ID", "Success recorded for query ID")
R(
    _qm,
    "Elimina definitivamente una voce dalla memoria (richiede ID).",
    "Permanently delete a memory entry (requires ID).",
)
R(_qm, "Voce {id} eliminata.", "Entry {id} deleted.")
R(_qm, "Voce non trovata.", "Entry not found.")
R(
    _qm,
    "[CHAT HISTORY SEARCH ONLY] Ricerca full-text (FTS5) sulle conversazioni passate",
    "[CHAT HISTORY SEARCH ONLY] Full-text search (FTS5) on past conversations",
)
R(
    _qm,
    "Usare quando l'utente chiede cosa è stato detto/discusso in sessioni precedenti",
    "Use when the user asks what was said/discussed in past sessions",
)
R(
    _qm,
    "NON usarlo per cercare query PromQL (usa `search_known_query`) né",
    "Do NOT use for PromQL queries (use `search_known_query`) or",
)
R(
    _qm,
    "fatti/preferenze strutturati (usa `mempalace_search`).",
    "structured facts/preferences (use `mempalace_search`).",
)
R(
    _qm,
    "Con summarize=True sintetizza i match trovati con il modello configurato.",
    "With summarize=True synthesizes matches using the configured model.",
)
R(
    _qm,
    "Nessuna conversazione passata trovata per la query.",
    "No past conversations found for the query.",
)
R(_qm, "Trovate {len(matches)} conversazioni:", "Found {len(matches)} conversations:")
R(
    _qm,
    "Sei un assistente di ricerca. Ti vengono forniti estratti di conversazioni passate.",
    "You are a search assistant. You are given excerpts from past conversations.",
)
R(
    _qm,
    "Sintetizza i fatti rilevanti per la QUERY, citando session_id e timestamp quando possibile.",
    "Summarize facts relevant to the QUERY, citing session_id and timestamp when possible.",
)
R(
    _qm,
    "Se i match non rispondono alla query, dillo chiaramente.",
    "If matches do not answer the query, say so clearly.",
)
R(_qm, "ESTRATTI:", "EXCERPTS:")
R(_qm, "[summarization fallita:", "[summarization failed:")
R(
    _qm,
    "Aggiorna una voce PromQL esistente nella memoria.",
    "Update an existing PromQL entry in memory.",
)
R(_qm, "Voce {id} aggiornata.", "Entry {id} updated.")
R(
    _qm,
    "Errore nell'aggiornamento o voce non trovata.",
    "Update error or entry not found.",
)

# --- skills_hub ---
_sh = "mcp_servers_std/skills_hub/server.py"
R(
    _sh,
    "Cerca skill per nome, tag o descrizione (limitata alle skill del profilo attivo se disponibile).",
    "Search skills by name, tag, or description (limited to active profile skills when available).",
)
R(_sh, " Prova skill_view diretto:", " Try skill_view directly:")
R(_sh, "Nessuna skill corrispondente.", "No matching skills.")
R(_sh, "Trovate {len(results)} skill:", "Found {len(results)} skills:")
R(
    _sh,
    "Usa skill_view(nome) per il corpo completo della skill.",
    "Use skill_view(name) for the full skill body.",
)
R(_sh, "materializzazione scripts fallita", "script materialization failed")
R(
    _sh,
    'usa `skill_view("docx")` prima di `sandbox_exec_allowlisted`.',
    'call `skill_view("docx")` before `sandbox_exec_allowlisted`.',
)
R(
    _sh,
    "scripts office pre-caricati in sessione per:",
    "office scripts pre-loaded in session for:",
)
R(
    _sh,
    "Restituisce il markdown completo di una skill.",
    "Returns the full markdown of a skill.",
)
R(_sh, "sessione corrente", "current session")
R(_sh, "non è abilitata nel profilo attivo", "is not enabled in the active profile")
R(_sh, "Skill consentite:", "Allowed skills:")
R(_sh, "(nessuna)", "(none)")
R(
    _sh,
    "Per la navigazione DB usa `mempalace_search` / drawer del progetto chat-ui,",
    "For DB navigation use `mempalace_search` / chat-ui project drawer,",
)
R(
    _sh,
    "non `skill_view` su skill rimosse dal profilo.",
    "not `skill_view` on skills removed from the profile.",
)
R(_sh, "non trovata.", "not found.")
R(
    _sh,
    "session id assente; scripts non materializzati.",
    "session id missing; scripts not materialized.",
)
R(_sh, "materializzazione fallita:", "materialization failed:")
R(
    _sh,
    "Elenca tutte le skill (nome e descrizione).",
    "List all skills (name and description).",
)
R(
    _sh,
    "Nessuna skill caricata per questo profilo.",
    "No skills loaded for this profile.",
)
R(
    _sh,
    "Crea o aggiorna una skill AION con frontmatter YAML.",
    "Create or update an AION skill with YAML frontmatter.",
)
R(
    _sh,
    "breve descrizione per l'indice (progressive disclosure)",
    "short description for the index (progressive disclosure)",
)
R(
    _sh,
    "corpo Markdown della skill (istruzioni dettagliate)",
    "skill Markdown body (detailed instructions)",
)
R(_sh, "tag utili per la ricerca", "tags useful for search")
R(
    _sh,
    "Errore: la scrittura/eliminazione di skill (AION_SKILL_WRITE_ENABLED) è disabilitata per questo server MCP.",
    "Error: skill write/delete (AION_SKILL_WRITE_ENABLED) is disabled for this MCP server.",
)
R(_sh, "Errore: il nome della skill non è valido.", "Error: invalid skill name.")
R(_sh, "Errore durante il salvataggio in", "Error while saving to")
R(_sh, "salvata con successo in:", "saved successfully to:")
R(_sh, "Registry ricaricato.", "Registry reloaded.")
R(
    _sh,
    "Elimina una skill esistente dal filesystem e dal registry.",
    "Delete an existing skill from the filesystem and registry.",
)
R(_sh, "Errore durante l'eliminazione di", "Error while deleting")
R(_sh, "eliminata con successo da:", "deleted successfully from:")
R(_sh, "eliminata tramite il registry.", "deleted via registry.")

# --- mem0 ---
_m0 = "mcp_servers_std/memory/mem0_server.py"
R(
    _m0,
    "Cerca ricordi e fatti semantici nella memoria a lungo termine dell'agente.",
    "Search semantic memories and facts in the agent long-term memory.",
)
R(
    _m0,
    "Utile per recuperare preferenze dell'utente, decisioni passate o fatti generali.",
    "Useful to retrieve user preferences, past decisions, or general facts.",
)
R(
    _m0,
    "Nessun ricordo semanticamente simile trovato.",
    "No semantically similar memory found.",
)
R(_m0, "Ricordi trovati in memoria:", "Memories found:")
R(_m0, "(Rilevanza:", "(Relevance:")
R(
    _m0,
    "Salva un nuovo fatto o una preferenza nella memoria a lungo termine.",
    "Save a new fact or preference to long-term memory.",
)
R(
    _m0,
    "Usa questo tool quando l'utente comunica qualcosa di importante che deve essere ricordato.",
    "Use when the user shares something important to remember.",
)
R(_m0, "Fatto memorizzato correttamente. ID:", "Fact stored successfully. ID:")
R(
    _m0,
    "Visualizza tutti i fatti memorizzati per l'utente corrente.",
    "List all facts stored for the current user.",
)
R(_m0, "La memoria è attualmente vuota.", "Memory is currently empty.")
R(_m0, "Elenco completo della memoria semantica:", "Full semantic memory list:")
R(
    _m0,
    "Elimina un fatto specifico dalla memoria utilizzando il suo ID.",
    "Delete a specific fact from memory using its ID.",
)
R(
    _m0,
    "Ricordo {fact_id} eliminato con successo.",
    "Memory {fact_id} deleted successfully.",
)
R(
    _m0,
    "ID non trovato o errore durante l'eliminazione.",
    "ID not found or error during deletion.",
)

# --- ocr ---
_ocr = "mcp_servers_std/ocr_mcp/server.py"
R(_ocr, "AION_CHAT_SESSION_ID non impostato", "AION_CHAT_SESSION_ID not set")
R(_ocr, "Errore path:", "Path error:")
R(_ocr, "Il path non è un file.", "Path is not a file.")
R(_ocr, "Errore durante l'OCR del PDF:", "Error during PDF OCR:")
R(_ocr, "Immagine troppo grande (max", "Image too large (max")
R(_ocr, "Errore chiamata OCR:", "OCR call error:")
R(_ocr, "Tipo MIME non supportato per OCR:", "MIME type not supported for OCR:")
R(_ocr, "Usa immagini", "Use images")

# --- runtime ---
R(
    "src/runtime/mcp_tooling_prompt.py",
    "## Strumenti MCP — come usarli\n",
    "## MCP tools — how to use them\n",
)
R(
    "src/runtime/mcp_tooling_prompt.py",
    "Ogni tool MCP è già elencato nel contesto del modello con **descrizione breve** e **schema parametri** ",
    "Each MCP tool is already listed in the model context with **short description** and **parameter schema** ",
)
R(
    "src/runtime/mcp_tooling_prompt.py",
    "(standard MCP `list_tools`). Le note qui sotto sono una **mappa concettuale** curata in AION: ",
    "(standard MCP `list_tools`). The notes below are a curated **conceptual map** in AION: ",
)
R(
    "src/runtime/mcp_tooling_prompt.py",
    "non sostituiscono i parametri obbligatori del singolo tool.",
    "they do not replace required parameters of individual tools.",
)
R(
    "src/runtime/mcp_tooling_prompt.py",
    "Documentazione estesa (vendor):",
    "Extended documentation (vendor):",
)

R(
    "src/runtime/skill_profile_gate.py",
    "non è abilitata nel profilo attivo",
    "is not enabled in the active profile",
)
R("src/runtime/skill_profile_gate.py", "Skill consentite:", "Allowed skills:")
R("src/runtime/skill_profile_gate.py", "(nessuna)", "(none)")
R(
    "src/runtime/skill_profile_gate.py",
    "Per la navigazione DB usa `mempalace_search` / drawer del progetto chat-ui,",
    "For DB navigation use `mempalace_search` / chat-ui project drawer,",
)
R(
    "src/runtime/skill_profile_gate.py",
    "non `skill_view` su skill rimosse dal profilo.",
    "not `skill_view` on skills removed from the profile.",
)

R(
    "src/runtime/plan_engine.py",
    "Non sono riuscito a strutturare un piano di esecuzione valido da questa risposta. ",
    "I could not structure a valid execution plan from this response. ",
)
R(
    "src/runtime/plan_engine.py",
    "Puoi riformulare la richiesta o chiedermi di riprovare?",
    "Can you rephrase the request or ask me to try again?",
)
R(
    "src/runtime/plan_engine.py",
    "_Contesto, vincoli e note di sfondo",
    "_Context, constraints, and background notes",
)
R(
    "src/runtime/plan_engine.py",
    "Modifica qui le spiegazioni lunghe._",
    "Edit long explanations here._",
)

R(
    "src/api/orchestration.py",
    "ATTENZIONE: Il piano di esecuzione '{plan_id}' è stato RIFIUTATO dall'utente. Motivo: {body.reason}. Proponi una modifica o chiedi chiarimenti.",
    "ATTENTION: Execution plan '{plan_id}' was REJECTED by the user. Reason: {body.reason}. Propose changes or ask for clarification.",
)

R(
    "src/runtime/turn_compaction.py",
    "[AION: output {tool} troncato — {n} caratteri omessi. Chiedi batch più piccoli o usa filtri.]",
    "[AION: {tool} output truncated — {n} characters omitted. Request smaller batches or use filters.]",
)

R("src/runtime/native_tools/web_providers.py", ": disabilitato", ": disabled")
R(
    "src/runtime/native_tools/web_providers.py",
    "tutti i provider hanno fallito o sono disabilitati",
    "all providers failed or are disabled",
)
R(
    "src/runtime/native_tools/web_providers.py",
    "web_fetch_page non estrae testo dai PDF. Cita l'URL (Fonti da web_search) ",
    "web_fetch_page does not extract text from PDFs. Cite the URL (sources from web_search) ",
)
R(
    "src/runtime/native_tools/web_providers.py",
    "o un tool OCR/documenti se disponibile nel profilo.",
    "or an OCR/document tool if available in the profile.",
)
R(
    "src/runtime/native_tools/web_providers.py",
    "AION_TAVILY_API_KEY mancante",
    "AION_TAVILY_API_KEY missing",
)
R(
    "src/runtime/native_tools/web_providers.py",
    "AION_BRAVE_SEARCH_API_KEY mancante",
    "AION_BRAVE_SEARCH_API_KEY missing",
)
R(
    "src/runtime/native_tools/web_providers.py",
    "AION_SEARXNG_BASE_URL mancante",
    "AION_SEARXNG_BASE_URL missing",
)

R(
    "src/runtime/native_tools/factory_table.py",
    "Ricerca web disattivata per questo messaggio.",
    "Web search disabled for this message.",
)
R(
    "src/runtime/native_tools/factory_table.py",
    "Download pagina disattivato insieme alla ricerca web.",
    "Page download disabled together with web search.",
)
R("src/runtime/native_tools/factory_table.py", "Ricerca sul web", "Web search")
R(
    "src/runtime/native_tools/factory_table.py",
    "Restituisce JSON con results[{title,url,snippet,provider}]. Usa query concise.",
    "Returns JSON with results[{title,url,snippet,provider}]. Use concise queries.",
)
R("src/runtime/native_tools/factory_table.py", "Query di ricerca", "Search query")
R("src/runtime/native_tools/factory_table.py", "Max risultati", "Max results")
R(
    "src/runtime/native_tools/factory_table.py",
    "Codice lingua opzionale",
    "Optional language code",
)
R(
    "src/runtime/native_tools/factory_table.py",
    "Scarica il contenuto testuale di una singola pagina HTTP(S). Preferisci URL già ottenuti da web_search.",
    "Download text content of a single HTTP(S) page. Prefer URLs already obtained from web_search.",
)
R(
    "src/runtime/native_tools/factory_table.py",
    "Restituisce JSON con campo text.",
    "Returns JSON with a text field.",
)

# skill_discovery_nudge
R(
    "src/runtime/skill_discovery_nudge.py",
    "[Istruzione sistema — skill discovery]",
    "[System instruction — skill discovery]",
)
R(
    "src/runtime/skill_discovery_nudge.py",
    "Prima di scrivere codice o file nel workspace per questo task, devi usare skills_hub:",
    "Before writing code or files in the workspace for this task, you must use skills_hub:",
)
R(
    "src/runtime/skill_discovery_nudge.py",
    "Se `skill_search` non trova risultati ma il profilo elenca la skill, chiama direttamente ",
    "If `skill_search` finds nothing but the profile lists the skill, call ",
)
R(
    "src/runtime/skill_discovery_nudge.py",
    "Dopo `skill_view`, gli script della skill (es. `scripts/office/unpack.py`) sono nella sessione;",
    "After `skill_view`, skill scripts (e.g. `scripts/office/unpack.py`) are in the session;",
)
R(
    "src/runtime/skill_discovery_nudge.py",
    "Solo dopo aver caricato la skill procedi con tool mutanti o artifact.",
    "Only after loading the skill proceed with mutating tools or artifacts.",
)

# turn_diagnostics
R(
    "src/runtime/turn_diagnostics.py",
    "Ho creato il piano di esecuzione nella barra laterale **Plan**. ",
    "I created the execution plan in the **Plan** sidebar. ",
)
R("src/runtime/turn_diagnostics.py", "Rivedi le task", "Review the tasks")
R(
    "src/runtime/turn_diagnostics.py",
    "e approva per avviare l'esecuzione.",
    "and approve to start execution.",
)
R(
    "src/runtime/turn_diagnostics.py",
    "Il turno è terminato senza una risposta testuale completa in chat.",
    "The turn ended without a complete text reply in chat.",
)
R("src/runtime/turn_diagnostics.py", "L'agente ha eseguito", "The agent ran")
R(
    "src/runtime/turn_diagnostics.py",
    "tool call ma non ha scritto un riepilogo finale.",
    "tool calls but did not write a final summary.",
)
R(
    "src/runtime/turn_diagnostics.py",
    "È stato generato ragionamento interno ma nessun testo di risposta visibile.",
    "Internal reasoning was generated but no visible reply text.",
)
R("src/runtime/turn_diagnostics.py", "Persistiti", "Persisted")
R(
    "src/runtime/turn_diagnostics.py",
    "messaggi (es. solo tool), senza testo assistant finale.",
    "messages (e.g. tool-only) with no final assistant text.",
)
R("src/runtime/turn_diagnostics.py", "Esito:", "Outcome:")
R("src/runtime/turn_diagnostics.py", "Sessione molto lunga (~", "Very long session (~")
R(
    "src/runtime/turn_diagnostics.py",
    " messaggi): apri una nuova chat o compatta lo storico.",
    " messages): start a new chat or compact history.",
)
R("src/runtime/turn_diagnostics.py", "Contesto stimato ~", "Estimated context ~")
R(
    "src/runtime/turn_diagnostics.py",
    " token): il modello può troncare o saltare il round finale.",
    " tokens): the model may truncate or skip the final round.",
)
R(
    "src/runtime/turn_diagnostics.py",
    "Raggiunto limite passi agente (",
    "Agent step limit reached (",
)

# db_navigation hooks
R(
    "src/runtime/db_navigation_mempalace_hooks.py",
    "## MemPalace navigazione",
    "## MemPalace navigation",
)
R(
    "src/runtime/db_navigation_mempalace_hooks.py",
    "Progetto impostato da chat-ui: non passare `wing` sui tool MemPalace.",
    "Project set by chat-ui: do not pass `wing` on MemPalace tools.",
)
R(
    "src/runtime/db_navigation_mempalace_hooks.py",
    "Percorsi/JOIN/entry point già verificati — riusa prima di esplorare schema:",
    "Verified paths/JOINs/entry points — reuse before exploring schema:",
)
R(
    "src/runtime/db_navigation_mempalace_hooks.py",
    "Percorso verificato per «",
    "Verified path for «",
)
R(
    "src/runtime/db_navigation_mempalace_hooks.py",
    "Entry point per «",
    "Entry point for «",
)
R("src/runtime/db_navigation_mempalace_hooks.py", "— lezione:", "— lesson:")
R(
    "src/runtime/db_navigation_mempalace_hooks.py",
    "Tabelle coinvolte:",
    "Tables involved:",
)

# agent_pipeline / stream
R(
    "src/agent_pipeline.py",
    "## File disponibili nella sessione (sandbox: scrivi `workspace/*.py` + `sandbox_run_python_file` per esecuzione):",
    "## Files available in the session (sandbox: write `workspace/*.py` + `sandbox_run_python_file` to run):",
)
R(
    "src/agent_pipeline.py",
    "Istruzioni per l'agente basato sul profilo",
    "Instructions for the agent based on profile",
)
R(
    "src/agent_pipeline.py",
    "Richiesta utente: {{user_input}}",
    "User request: {{user_input}}",
)
R(
    "src/agent_pipeline.py",
    "Task segnata completata. Turno interrotto — ",
    "Task marked completed. Turn interrupted — ",
)
R(
    "src/agent_pipeline.py",
    "il server continuerà con la task successiva.",
    "the server will continue with the next task.",
)
R(
    "src/agent_pipeline.py",
    "Il turno è stato interrotto (",
    "The turn was interrupted (",
)
R("src/agent_pipeline.py", ") ma l'agente ", ") but the agent ")
R("src/agent_pipeline.py", "non ha terminato entro ", "did not finish within ")
R(
    "src/agent_pipeline.py",
    "Sto strutturando il piano di esecuzione…",
    "Structuring the execution plan…",
)
R(
    "src/agent_pipeline.py",
    'yield {"type": "error", "content": "Timeout dell\'operazione."}',
    'yield {"type": "error", "content": "Operation timed out."}',
)
R(
    "src/runtime/stream/loop.py",
    "Task segnata completata. Turno interrotto — ",
    "Task marked completed. Turn interrupted — ",
)
R(
    "src/runtime/stream/loop.py",
    "il server continuerà con la task successiva.",
    "the server will continue with the next task.",
)
R("src/runtime/stream/loop.py", "[file aggiornato:", "[file updated:")
R(
    "src/runtime/stream/loop.py",
    "Interrotto automaticamente: nessun progresso rilevato nel turno ",
    "Automatically stopped: no progress detected in turn ",
)

# plan_execution handler
R(
    "src/plan_execution/handler.py",
    "Avvio esecuzione piano…",
    "Starting plan execution…",
)
R("src/plan_execution/handler.py", "esecuzione interrotta", "execution interrupted")
R("src/plan_execution/handler.py", "— errore", "— error")
R(
    "src/plan_execution/handler.py",
    "Esecuzione piano annullata.",
    "Plan execution cancelled.",
)
R(
    "src/plan_execution/handler.py",
    "vedi piano nel pannello Plan.",
    "see plan in the Plan panel.",
)
R("src/plan_execution/handler.py", "Obiettivo:", "Goal:")
R("src/plan_execution/handler.py", "## Piano completato —", "## Plan completed —")
R("src/plan_execution/handler.py", "Piano completato", "Plan completed")
R(
    "src/plan_execution/handler.py",
    "Esecuzione piano interrotta (riavvio server o sessione persa). ",
    "Plan execution interrupted (server restart or lost session). ",
)
R(
    "src/plan_execution/handler.py",
    "Riapprova o avvia di nuovo dal pannello Plan.",
    "Re-approve or restart from the Plan panel.",
)
R(
    "src/plan_execution/handler.py",
    "Write a mandatory final comment for the user in Italian (markdown).",
    "Write a mandatory final comment for the user in English (markdown).",
)
R(
    "src/plan_execution/handler.py",
    "non completata dopo retry — saltata",
    "not completed after retry — skipped",
)

# tools - bulk Italian errors
for _f in [
    "src/tools/session_exec.py",
    "src/tools/session_venv.py",
    "src/tools/session_fs_tools.py",
    "src/tools/session_code.py",
    "src/tools/skill_materialize.py",
]:
    R(_f, "Errore:", "Error:")
    R(_f, "File non trovato:", "File not found:")
    R(_f, "non trovato", "not found")
    R(_f, "non trovata", "not found")
    R(_f, "non valido", "invalid")
    R(_f, "non consentito", "not allowed")
    R(_f, "disabilitat", "disabled")

R("src/tools/session_exec.py", "argv vuoto", "empty argv")
R("src/tools/session_exec.py", "Eseguibile", "Executable")
R(
    "src/tools/session_exec.py",
    "non in allowlist. Contatta il team",
    "not in allowlist. Contact the team",
)
R(
    "src/tools/session_exec.py",
    "python richiede almeno lo script come primo argomento",
    "python requires at least the script as the first argument",
)
R("src/tools/session_exec.py", "non consentito", "not allowed")
R(
    "src/tools/session_exec.py",
    "usa sandbox_run_python_file",
    "use sandbox_run_python_file",
)
R("src/tools/session_exec.py", "deve essere sotto scripts/", "must be under scripts/")
R("src/tools/session_exec.py", "è fuori dalla sessione.", "is outside the session.")
R(
    "src/tools/session_exec.py",
    "Esecuzione exec disabilitata",
    "Exec execution disabled",
)
R("src/tools/session_exec.py", "Esegui prima skill_view", "Run skill_view first")
R(
    "src/tools/session_exec.py",
    "Script non trovato in sessione:",
    "Script not found in session:",
)
R(
    "src/tools/session_exec.py",
    "Comando terminato per timeout",
    "Command terminated due to timeout",
)
R("src/tools/session_exec.py", "Eseguibile non trovato:", "Executable not found:")

R("src/tools/session_venv.py", "python -m venv fallito", "python -m venv failed")
R(
    "src/tools/session_venv.py",
    "venv creato ma interprete non trovato",
    "venv created but interpreter not found",
)
R(
    "src/tools/session_venv.py",
    "Installazione pacchetti disabilitata",
    "Package installation disabled",
)
R("src/tools/session_venv.py", "elenco pacchetti vuoto.", "empty package list.")
R("src/tools/session_venv.py", "troppi pacchetti", "too many packages")
R(
    "src/tools/session_venv.py",
    "interprete venv non trovato",
    "venv interpreter not found",
)
R(
    "src/tools/session_venv.py",
    "uv richiesto ma non presente sul PATH.",
    "uv required but not on PATH.",
)
R("src/tools/session_venv.py", "Installazione fallita:", "Installation failed:")
R(
    "src/tools/session_venv.py",
    "OK installazione in venv sessione.",
    "OK installation in session venv.",
)

R(
    "src/tools/session_fs_tools.py",
    "File troppo grande per edit",
    "File too large to edit",
)
R(
    "src/tools/session_fs_tools.py",
    "Usa sandbox_write_workspace_file per riscrivere il file intero.",
    "Use sandbox_write_workspace_file to rewrite the entire file.",
)
R(
    "src/tools/session_fs_tools.py",
    "non è testo UTF-8 valido.",
    "is not valid UTF-8 text.",
)
R(
    "src/tools/session_fs_tools.py",
    "old_string non trovata nel file",
    "old_string not found in file",
)
R("src/tools/session_fs_tools.py", "Anteprima file", "File preview")
R(
    "src/tools/session_fs_tools.py",
    "Suggerimento: verifica whitespace",
    "Hint: check whitespace",
)
R("src/tools/session_fs_tools.py", "old_string trovata", "old_string found")
R("src/tools/session_fs_tools.py", "volte", "times")
R(
    "src/tools/session_fs_tools.py",
    "Occorrenze trovate alle righe:",
    "Matches at lines:",
)
R("src/tools/session_fs_tools.py", "Edit completato:", "Edit completed:")
R("src/tools/session_fs_tools.py", "sostituzione/i", "replacement(s)")
R(
    "src/tools/session_fs_tools.py",
    "Versione precedente archiviata in .versions/.",
    "Previous version archived in .versions/.",
)
R(
    "src/tools/session_fs_tools.py",
    "pattern non può essere vuoto",
    "pattern cannot be empty",
)
R("src/tools/session_fs_tools.py", "[TRONCATO:", "[TRUNCATED:")
R("src/tools/session_fs_tools.py", "risultati]", "results]")
R("src/tools/session_fs_tools.py", "Errore lettura", "Read error")

R("src/tools/session_code.py", "import '", "import '")  # noop guard
R(
    "src/tools/session_code.py",
    "non consentito nella sandbox.",
    "not allowed in the sandbox.",
)
R("src/tools/session_code.py", "Esempi consentiti:", "Allowed examples:")
R("src/tools/session_code.py", "file troppo grande", "file too large")
R(
    "src/tools/session_code.py",
    "scrittura consentita solo sotto workspace/",
    "writing allowed only under workspace/",
)
R(
    "src/tools/session_code.py",
    "usa un path relativo alla sessione",
    "use a session-relative path",
)
R(
    "src/tools/session_code.py",
    "uploads/ è in sola lettura; usa workspace/",
    "uploads/ is read-only; use workspace/",
)
R("src/tools/session_code.py", "codice Python vuoto.", "empty Python code.")
R(
    "src/tools/session_code.py",
    "impossibile risolvere path script:",
    "unable to resolve script path:",
)
R(
    "src/tools/session_code.py",
    "Suggerimento: per librerie non in whitelist",
    "Hint: for libraries not on the whitelist",
)
R(
    "src/tools/session_code.py",
    "eseguire solo script sotto workspace/",
    "only run scripts under workspace/",
)
R(
    "src/tools/session_code.py",
    "il path deve terminare con .py",
    "path must end with .py",
)
R(
    "src/tools/session_code.py",
    "Node.js non trovato sul server. Installa Node o imposta AION_NODE_PATH.",
    "Node.js not found on the server. Install Node or set AION_NODE_PATH.",
)

R(
    "src/tools/skill_materialize.py",
    "non ha scripts/ da materializzare.",
    "has no scripts/ to materialize.",
)
R(
    "src/tools/skill_materialize.py",
    "Scripts già materializzati",
    "Scripts already materialized",
)
R("src/tools/skill_materialize.py", "(invariati).", "(unchanged).")
R(
    "src/tools/skill_materialize.py",
    "Scripts materializzati per",
    "Scripts materialized for",
)
R("src/tools/skill_materialize.py", "(sessione).", "(session).")
R(
    "src/tools/skill_materialize.py",
    "Esempi path (cwd = session root):",
    "Example paths (cwd = session root):",
)
R(
    "src/tools/skill_materialize.py",
    "Dopo unpack usa workspace/unpacked/",
    "After unpack use workspace/unpacked/",
)
R(
    "src/tools/skill_materialize.py",
    "legi XML con sandbox_read_text_file",
    "read XML with sandbox_read_text_file",
)
R(
    "src/tools/skill_materialize.py",
    "Nessuno script sul server:",
    "No scripts on server:",
)

R("src/research/handler.py", "ricerca interrotta", "research interrupted")

R("src/runtime/slash.py", "Errore TTC:", "TTC error:")
R(
    "src/runtime/slash.py",
    "Comando /clear: archivia questa conversazione dal client e creane una nuova (integrazione UI in corso).",
    "Command /clear: archive this conversation from the client and start a new one (UI integration in progress).",
)
R(
    "src/runtime/slash.py",
    "Compattazione contesto programmata per il prossimo messaggio in questa chat ",
    "Context compaction scheduled for the next message in this chat ",
)
R(
    "src/runtime/slash.py",
    "Avvia task con Test-Time Compute",
    "Start task with Test-Time Compute",
)

R(
    "src/runtime/orchestration_tools.py",
    "(nessuna task nel markdown)",
    "(no tasks in markdown)",
)

R(
    "src/runtime/llm_health.py",
    "Errore di connettività: impossibile raggiungere l'endpoint del modello ",
    "Connectivity error: unable to reach the model endpoint ",
)
R(
    "src/runtime/llm_health.py",
    "Verifica la connessione",
    "Check the network connection",
)

R(
    "src/runtime/mcp_health.py",
    "Profilo '{profile_name}' non trovato.",
    "Profile '{profile_name}' not found.",
)
R(
    "src/runtime/mcp_health.py",
    "aggiorna il token/chiave per questo connettore, oppure disattivalo nel profilo.",
    "update the token/key for this connector, or disable it in the profile.",
)
R(
    "src/runtime/mcp_health.py",
    "o disattiva temporaneamente l'integrazione dal profilo.",
    "or temporarily disable the integration from the profile.",
)

R(
    "src/runtime/subagent_tools.py",
    "Delega un compito a un altro profilo agente specializzato.",
    "Delegate a task to another specialized agent profile.",
)
R(
    "src/runtime/subagent_tools.py",
    "Il sub-agente lavorerà in una sessione isolata",
    "The sub-agent works in an isolated session",
)
R(
    "src/runtime/subagent_tools.py",
    "Delega un compito a un sub-agente specializzato",
    "Delegate a task to a specialized sub-agent",
)
R(
    "src/runtime/subagent_tools.py",
    "Richiede il nome del profilo e il compito.",
    "Requires profile name and task.",
)
R(
    "src/runtime/subagent_tools.py",
    "Nome o slug del profilo agente da attivare.",
    "Name or slug of the agent profile to activate.",
)
R(
    "src/runtime/subagent_tools.py",
    "Descrizione del compito da affidare al sub-agente.",
    "Description of the task to assign to the sub-agent.",
)

R(
    "src/doc_processor.py",
    "(Errore durante l'estrazione da",
    "(Error while extracting from",
)

# query_memory SQL section - read rest of file for more strings
_qm2 = [
    (
        "[SQL QUERY MEMORY ONLY] Cerca query PostgreSQL (SELECT) validate nel cassetto QueryMemory.",
        "[SQL QUERY MEMORY ONLY] Search validated PostgreSQL (SELECT) queries in the QueryMemory drawer.",
    ),
    (
        "NON usare per PromQL (usa search_known_query) né per chat history (session_search).",
        "Do NOT use for PromQL (use search_known_query) or chat history (session_search).",
    ),
    (
        "Chiamare SEMPRE prima di esplorare information_schema o inventare SQL da zero.",
        "ALWAYS call before exploring information_schema or inventing SQL from scratch.",
    ),
    (
        "`project` = slug cassetto (es. vendite, tecnico); default da configurazione se vuoto.",
        "`project` = drawer slug (e.g. sales, tech); defaults from config if empty.",
    ),
    (
        "[SQL QUERY MEMORY ONLY] Salva una query SQL PostgreSQL verificata nel cassetto.",
        "[SQL QUERY MEMORY ONLY] Save a verified PostgreSQL query to the drawer.",
    ),
    (
        "NON usare per PromQL. Usa is_verified=True solo dopo risultati corretti.",
        "Do NOT use for PromQL. Use is_verified=True only after correct results.",
    ),
    (
        "[SQL ONLY] Incrementa successi; auto-verifica dopo soglia configurata.",
        "[SQL ONLY] Increment successes; auto-verify after configured threshold.",
    ),
    (
        "Elimina una query SQL dalla cache del progetto attivo.",
        "Delete a SQL query from the active project cache.",
    ),
    (
        "Aggiorna richiesta NL, SQL o flag verificata nel progetto attivo.",
        "Update NL request, SQL, or verified flag in the active project.",
    ),
]
for old, new in _qm2:
    R(_qm, old, new)

_ch = "mcp_servers_std/charts/server.py"
R(
    _ch,
    "Crea un grafico per la sessione corrente. Consente di visualizzare i dati interattivamente in chat-ui (Recharts).",
    "Create a chart for the current session. Displays data interactively in chat-ui (Recharts).",
)
R(_ch, "Parametri:", "Parameters:")
R(
    _ch,
    "Il titolo descrittivo del grafico o una query PromQL (se si interroga Prometheus).",
    "Descriptive chart title or PromQL query (when querying Prometheus).",
)
R(
    _ch,
    "Lista o stringa JSON di dizionari/record per tracciare dati arbitrari",
    "List or JSON string of dicts/records for arbitrary data",
)
R(_ch, "Il tipo di grafico:", "Chart type:")
R(_ch, "confronto/tempo", "comparison/time")
R(_ch, "volumi", "volumes")
R(_ch, "distribuzioni/barre", "distributions/bars")
R(_ch, "La chiave del record da usare per l'asse X", "Record key for the X axis")
R(
    _ch,
    "Lista o stringa JSON delle colonne da visualizzare",
    "List or JSON string of columns to display",
)
R(_ch, "default: tutte tranne x_key", "default: all except x_key")
R(_ch, "Se impostato a True, impila le serie", "If True, stack series")
R(_ch, "rilevante per 'area' e 'bar'", "relevant for 'area' and 'bar'")
R(_ch, "Se True, nasconde la legenda.", "If True, hide the legend.")
R(_ch, "Etichetta dell'asse Y.", "Y-axis label.")
R(
    _ch,
    "Nessun dato Prometheus trovato per la query:",
    "No Prometheus data found for query:",
)
R(
    _ch,
    "Istruzione incompleta: 'data' non fornito e server Prometheus non configurato.",
    "Incomplete instruction: 'data' not provided and Prometheus server not configured.",
)

_lr = "mcp_servers_std/legacy_rag/server.py"
R(
    _lr,
    "Cerca informazioni nei documenti caricati",
    "Search information in uploaded documents",
)
R(
    _lr,
    "Nessun contesto documento fornito per la ricerca.",
    "No document context provided for search.",
)
R(_lr, "--- Estratto Documento ---", "--- Document Excerpt ---")
R(
    _lr,
    "Nessuna corrispondenza trovata nei documenti forniti.",
    "No match found in the provided documents.",
)

_ocr2 = "mcp_servers_std/ocr_mcp/server.py"
R(_ocr2, "Estrae testo da un file nella sessione", "Extract text from a session file")
R(
    _ocr2,
    "Usa SEMPRE il modello OCR vision-based",
    "ALWAYS use the vision-based OCR model",
)

R(
    "src/runtime/mcp_integration_helpers.py",
    "Chiedi all'amministratore di configurare questo server MCP in Hub.",
    "Ask the administrator to configure this MCP server in Hub.",
)
R(
    "src/runtime/mcp_integration_helpers.py",
    "L'amministratore deve abilitare questa integrazione per gli utenti in MCP Hub.",
    "The administrator must enable this integration for users in MCP Hub.",
)
R(
    "src/runtime/mcp_integration_helpers.py",
    "Configura le credenziali personali per usare questo strumento.",
    "Configure your personal credentials to use this tool.",
)

R("src/plan_execution/handler.py", "in corso", "in progress")
R("src/plan_execution/handler.py", "completata", "completed")
R("src/plan_execution/handler.py", "fallita — saltata", "failed — skipped")
R(
    "src/plan_execution/handler.py",
    "Scrittura commento finale…",
    "Writing final comment…",
)
R("src/plan_execution/handler.py", "In corso…", "In progress…")
R(
    "src/plan_execution/handler.py",
    "Scrivo file nel workspace",
    "Writing file to workspace",
)
R("src/plan_execution/handler.py", "Leggo file", "Reading file")
R("src/plan_execution/handler.py", "Modifico file", "Editing file")
R("src/plan_execution/handler.py", "Segno task completata", "Marking task completed")
R("src/plan_execution/handler.py", "Consulto MemPalace", "Querying MemPalace")
R("src/plan_execution/handler.py", "Cerco nel codebase", "Searching codebase")
R("src/plan_execution/handler.py", "Interrogo metriche", "Querying metrics")
R("src/plan_execution/handler.py", "Eseguo", "Running")
R("src/plan_execution/handler.py", "— fatto", "— done")
R("src/plan_execution/handler.py", "✅ Piano", "✅ Plan")


def main() -> int:
    by_file: dict[str, list[tuple[str, str]]] = {}
    for rel, old, new in REPLACEMENTS:
        by_file.setdefault(rel, []).append((old, new))

    changed = 0
    for rel, pairs in sorted(by_file.items()):
        path = ROOT / rel
        if not path.is_file():
            print(f"skip missing {rel}", file=sys.stderr)
            continue
        text = path.read_text(encoding="utf-8")
        orig = text
        for old, new in pairs:
            if old in text:
                text = text.replace(old, new)
        if text != orig:
            path.write_text(text, encoding="utf-8")
            changed += 1
            print(f"updated {rel}")

    print(f"done: {changed} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
