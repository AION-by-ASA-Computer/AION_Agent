"""
Modulo di Telemetria e Tracciamento Avanzato OPIK (Comet ML).

Questo modulo fornisce un'implementazione completa e strutturata (production-ready)
per l'integrazione di Opik in modalità SELF-HOSTED per mappare:
1. PROFILI (Traces, tag del profilo e metadati del modello).
2. SKILL (Nested Spans con metriche personalizzate).
3. PROMPT (Prompt Library, versionamento dei template ed associazione alle tracce).
4. TOOL (Spans di tipo "tool" con tracciamento degli input ed output).

REQUISITI DI CONFIGURAZIONE:
Le variabili d'ambiente nel file .env (caricate tramite src.aion_env) controllano la telemetria:
- OPIK_URL_OVERRIDE="http://localhost:5173/api"
- OPIK_PROJECT_NAME="AION-Agent"

Inoltre, per abilitare la chiamata all'LLM (o gli algoritmi di auto-valutazione ed LLM-as-a-judge):
- AION_API_URL (LLM API endpoint, e.g. http://localhost:8000/v1)
- AION_LLM_API_KEY (Chiave di autorizzazione)
- AION_MODEL (Nome del modello da invocare)
"""

import os
import json
import logging
import httpx
import src.aion_env  # noqa: F401 — IMPORTANTE: Deve essere il primo import per caricare .env correttamente!

# Importazione dell'infrastruttura Opik e dei decoratori di tracciamento
from opik import track
from opik.opik_context import update_current_trace, update_current_span
from src.observability.opik_setup import opik_client, get_or_create_prompt

# Logger locale per il tracciamento interno
logger = logging.getLogger("aion.observability.telemetry")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# =============================================================================
# 1. INTEGRAZIONE PROMPT LIBRARY (Punto 1 requisiti)
# =============================================================================

# Definizione del template del prompt con i relativi placeholder dinamici.
# Questo prompt verrà caricato ed inserito nella Prompt Library di Opik se mancante.
CORE_PROMPT_TEMPLATE = (
    "Sei un assistente virtuale basato su AI Agent con il profilo: {{profilo}}.\n"
    "Usa le tue abilità (Skills) e i tuoi strumenti (Tools) per assistere l'utente.\n"
    "Contesto della conversazione: {{contesto}}\n"
    "Richiesta dell'utente: {{user_input}}\n"
    "Fornisci una risposta accurata e strutturata."
)

PROMPT_NAME = "agente-core-prompt"

def check_prompt(profilo: str, contesto: str, user_input: str) -> tuple:
    """
    Verifica se il prompt 'agente-core-prompt' esiste nella Prompt Library di Opik.
    Se non esiste, lo crea con i placeholder corretti.
    Infine, recupera l'ultima versione e la formatta con i dati dinamici.
    
    Returns:
        tuple: (prompt_formattato, prompt_object_originale)
    """
    # Recupera o crea il prompt usando l'helper configurato in opik_setup.py
    prompt_obj = get_or_create_prompt(
        prompt_name=PROMPT_NAME,
        template_content=CORE_PROMPT_TEMPLATE,
        metadata={"ambito": "core-agent", "struttura": "jinja"}
    )
    
    # Formattazione dinamica dei placeholder
    prompt_formattato = prompt_obj.format(
        profilo=profilo,
        contesto=contesto,
        user_input=user_input
    )
    
    return prompt_formattato, prompt_obj

# =============================================================================
# 2. INTEGRAZIONE LLM ED AUTO-VALUTAZIONE (Punto 4 requisiti + feedback utente)
# =============================================================================

@track(type="llm", name="call_llm_api")
def call_llm_api(prompt_text: str, model_config: dict) -> str:
    """
    Esegue la chiamata reale all'LLM configurato tramite le variabili d'ambiente.
    Viene marcato come span di tipo 'llm' su Opik in modo da tracciare token,
    costo (se applicabile) e l'esatto scambio di messaggi input/output.
    In caso di offline o fallimento, fa il fallback su una risposta simulata (mock).
    """
    try:
        from src.runtime.llm_adapter import resolve_llm_endpoint

        api_url, model_name = resolve_llm_endpoint()
    except ValueError:
        api_url = (os.getenv("AION_API_URL") or "").strip().rstrip("/")
        model_name = (os.getenv("AION_MODEL") or "").strip()
    api_key = os.getenv("AION_LLM_API_KEY", "placeholder-token")
    
    # Costruisce l'URL completo basato su AION_API_URL
    chat_url = f"{api_url.rstrip('/')}/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": prompt_text}
        ],
        "temperature": model_config.get("temperature", 0.7),
        "max_tokens": model_config.get("max_tokens", 2048)
    }
    
    logger.info(f"Invocazione LLM in corso a: {chat_url} (Modello: {model_name})...")
    
    # Mappiamo esplicitamente i parametri su Opik
    update_current_span(
        metadata={
            "model": model_name,
            "temperature": payload["temperature"],
            "max_tokens": payload["max_tokens"],
            "endpoint_endpoint": chat_url
        }
    )
    
    try:
        # Chiamata sincrona all'API dell'LLM
        with httpx.Client(timeout=30.0) as client:
            response = client.post(chat_url, headers=headers, json=payload)
            response.raise_for_status()
            response_data = response.json()
            
            # Estrazione del testo della risposta
            completion_text = response_data["choices"][0]["message"]["content"]
            usage = response_data.get("usage", {})
            
            # Tracciamento dei token consumati nello Span di Opik
            update_current_span(
                usage={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0)
                }
            )
            
            logger.info("Risposta LLM ricevuta ed associata allo span Opik.")
            return completion_text
            
    except Exception as e:
        logger.warning(f"Chiamata LLM fallita o non disponibile ({e}). Esecuzione del Fallback Mock...")
        
        # Risposta simulata in caso di fallimento della connessione
        mock_response = (
            f"[MOCK LLM RESPONSE]\n"
            f"Elaborata richiesta con successo basandomi sul prompt fornito.\n"
            f"Output generato dal modello simulato per il profilo attivo."
        )
        
        # Registra un consumo stimato fittizio per scopi di visualizzazione
        update_current_span(
            usage={
                "prompt_tokens": len(prompt_text) // 4,
                "completion_tokens": len(mock_response) // 4,
                "total_tokens": (len(prompt_text) + len(mock_response)) // 4
            },
            metadata={"warning": "chiamata fallita, utilizzato fallback mock", "error_dettagliato": str(e)}
        )
        
        return mock_response

# =============================================================================
# 3. TRACCIAMENTO DEI TOOL (Punto 4 requisiti)
# =============================================================================

@track(type="tool", name="execute_tool_ricerca")
def execute_tool_ricerca(db_table: str, search_criteria: dict) -> list:
    """
    Rappresenta l'esecuzione di un Tool dell'agente.
    Viene marcato come span di tipo 'tool' in Opik per differenziarlo dalle chiamate LLM.
    """
    logger.info(f"Esecuzione Tool 'execute_tool_ricerca' su tabella '{db_table}'...")
    
    # Iniezione di parametri dello strumento nello span corrente
    update_current_span(
        metadata={
            "tool_name": "execute_tool_ricerca",
            "db_table": db_table,
            "search_criteria": search_criteria
        }
    )
    
    # Simulazione della ricerca nel database
    results = [
        {"id": 101, "prodotto": "Server Rack A1", "stato": "disponibile"},
        {"id": 102, "prodotto": "Switch Managed 24p", "stato": "in_manutenzione"},
        {"id": 103, "prodotto": "Router Edge 5G", "stato": "disponibile"}
    ]
    
    # Filtriamo i risultati in base a un criterio simulato
    filtered_results = [r for r in results if r["stato"] == search_criteria.get("stato", "disponibile")]
    
    # Aggiorna lo span con il numero di record trovati prima di ritornare
    update_current_span(
        metadata={"records_returned": len(filtered_results)}
    )
    
    return filtered_results

# =============================================================================
# 4. TRACCIAMENTO DELLE SKILL (Punto 3 requisiti - Nested Spans)
# =============================================================================

@track(type="general", name="skill_ricerca_db")
def skill_ricerca_db(query_str: str) -> dict:
    """
    Rappresenta una Skill specifica dell'agente: Ricerca sul Database.
    Decorata con @track per essere visualizzata come Span figlio all'interno di run_agent.
    """
    logger.info(f"Skill 'skill_ricerca_db' avviata con query: '{query_str}'")
    
    # Traccia i parametri della skill
    update_current_span(
        metadata={
            "skill_class": "DatabaseCapability",
            "query_originale": query_str
        }
    )
    
    # Chiama un tool interno all'interno della skill (crea un ulteriore livello di nesting)
    tool_results = execute_tool_ricerca("inventario_hardware", {"stato": "disponibile"})
    
    risultato = {
        "status": "success",
        "dati_trovati": tool_results,
        "numero_record": len(tool_results)
    }
    
    # Aggiorna lo span della skill con i risultati intermedi
    update_current_span(
        metadata={
            "records_count": risultato["numero_record"],
            "ricerca_avvenuta": True
        }
    )
    
    return risultato


@track(type="general", name="skill_calcolo_metrico")
def skill_calcolo_metrico(dati_input: list) -> dict:
    """
    Rappresenta un'altra Skill dell'agente: Calcolo Metrico / Analytics.
    Decorata con @track per essere visualizzata come Span figlio.
    """
    logger.info(f"Skill 'skill_calcolo_metrico' avviata su {len(dati_input)} elementi.")
    
    # Traccia le informazioni di input
    update_current_span(
        metadata={
            "skill_class": "AnalyticsCapability",
            "dati_input_count": len(dati_input)
        }
    )
    
    # Simulazione di elaborazione complessa sui dati
    somma_ids = sum(item.get("id", 0) for item in dati_input)
    valore_metric = somma_ids / len(dati_input) if dati_input else 0.0
    
    risultato = {
        "metrica_calcolata": "media_identificatori",
        "valore": valore_metric,
        "elementi_elaborati": len(dati_input)
    }
    
    # Salva il risultato nel contesto dello span corrente
    update_current_span(
        metadata={
            "metric_score": risultato["valore"],
            "calcolo_completato": True
        }
    )
    
    return risultato

# =============================================================================
# 5. TRACCIAMENTO DEI PROFILI (Punto 2 requisiti - Trace principale & Metadata)
# =============================================================================

@track(type="general", name="run_agent")
def run_agent(user_input: str, active_profile: str = "Tecnico_Senior", session_id: str = None) -> str:
    """
    Metodo/Funzione principale dell'Agent.
    Rappresenta il Trace principale (Root Trace) in Opik.
    Associa il profilo attivo come Tag e inietta i parametri del modello nei Metadata.
    """
    logger.info(f"Avvio Agent per input utente. Profilo attivo: {active_profile} | Sessione/Thread: {session_id}")
    
    # Configurazione simulata del modello
    try:
        from src.runtime.llm_adapter import resolve_llm_endpoint

        _, _model_name = resolve_llm_endpoint()
    except ValueError:
        _model_name = (os.getenv("AION_MODEL") or "").strip() or "unknown"
    model_config = {
        "model": _model_name,
        "temperature": 0.4,
        "max_tokens": 1024
    }
    
    # 1. Recupera, verifica ed formatta il prompt dalla Prompt Library
    contesto_simulato = "Sessione di manutenzione infrastruttura hardware."
    prompt_formattato, prompt_originale = check_prompt(
        profilo=active_profile,
        contesto=contesto_simulato,
        user_input=user_input
    )
    
    # 2. Aggiorna la traccia principale corrente con Tag ed i Metadati del Profilo
    update_current_trace(
        thread_id=session_id,
        tags=[active_profile, "AION-Core-Run", "Self-Hosted"],
        metadata={
            "active_profile": active_profile,
            "system_prompt_template": prompt_originale.prompt,
            "model_settings": model_config,
            "conversation_context": contesto_simulato
        },
        # Associa il prompt utilizzato a questa traccia per monitorarne la versione
        prompts=[prompt_originale]
    )
    
    # 3. Esegue la prima Skill dell'agente (Nested Span 1)
    risultato_ricerca = skill_ricerca_db(user_input)
    
    # 4. Esegue la seconda Skill dell'agente (Nested Span 2)
    risultato_metrica = skill_calcolo_metrico(risultato_ricerca["dati_trovati"])
    
    # 5. Chiamata finale all'LLM (LLM Span) includendo i contesti elaborati dalle skills
    prompt_finale = (
        f"{prompt_formattato}\n\n"
        f"--- DATI TROVATI DA SKILL RICERCA ---\n"
        f"{json.dumps(risultato_ricerca['dati_trovati'], indent=2)}\n\n"
        f"--- METRICHE CALCOLATE DA SKILL METRICA ---\n"
        f"{json.dumps(risultato_metrica, indent=2)}\n"
    )
    
    risposta_llm = call_llm_api(prompt_finale, model_config)
    
    logger.info("Elaborazione Agent completata. Traccia Opik salvata.")
    return risposta_llm


# =============================================================================
# 6. ROUTINE DI SIMULAZIONE E TESTING LOCALE
# =============================================================================

if __name__ == "__main__":
    import sys
    import uuid
    import asyncio
    from src.observability.opik_setup import chiudi_sessione_e_valuta

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("\n" + "="*80)
    print(" AVVIO SIMULAZIONE DI TELEMETRIA OPIK (AION_Agent)")
    print("="*80)
    
    # Genera un ID di sessione univoco per tracciare il Thread multi-turno
    session_id = f"test-session-{uuid.uuid4()}"
    profilo_test = "Tecnico_Senior"
    
    # Turno 1
    test_input_1 = "Mostrami lo stato dei router e calcola la metrica degli ID"
    print(f"\n1. Inizio TURNO 1 dell'Agent con Profilo: '{profilo_test}'")
    print(f"   Sessione/Thread ID: {session_id}")
    print(f"   Input Utente 1: '{test_input_1}'")
    
    try:
        # Avvia l'esecuzione tracciata per il Turno 1
        risposta_1 = run_agent(test_input_1, active_profile=profilo_test, session_id=session_id)
        
        print("\n" + "="*80)
        print(" RISPOSTA GENERATA DALL'AGENTE (TURNO 1):")
        print("="*80)
        print(risposta_1)
        print("="*80)
        
        # Turno 2 (sequenziale sullo stesso thread)
        test_input_2 = "Grazie, ora effettua un calcolo sui router rimanenti"
        print(f"\n2. Inizio TURNO 2 dell'Agent sullo STESSO Thread")
        print(f"   Input Utente 2: '{test_input_2}'")
        
        # Avvia l'esecuzione tracciata per il Turno 2
        risposta_2 = run_agent(test_input_2, active_profile=profilo_test, session_id=session_id)
        
        print("\n" + "="*80)
        print(" RISPOSTA GENERATA DALL'AGENTE (TURNO 2):")
        print("="*80)
        print(risposta_2)
        print("="*80)
        
        # Valutazione finale del thread / chiusura sessione
        print("\n3. Chiusura sessione e invio feedback score del Thread...")
        asyncio.run(chiudi_sessione_e_valuta(session_id))
        
        print("\n[SUCCESSO] La simulazione multi-turno è terminata con successo. I dati e i feedback scores sono stati inviati ad Opik.")
        
    except Exception as e:
        print(f"\n[ERRORE] Errore durante l'esecuzione del test: {e}")
        
    print("\n" + "="*80)
    print(" GUIDA ALLA NAVIGAZIONE NELLA UI LOCALE DI OPIK")
    print("="*80)
    print("Apri il browser all'indirizzo del tuo pannello di controllo Opik locale")
    print("(e.g. http://localhost:5173 or your configured frontend port):")
    print("\n1. SEZIONE 'Prompt Library':")
    print(f"   - Troverai un prompt chiamato '{PROMPT_NAME}'.")
    print("   - All'interno puoi vedere il template con i placeholder {{profilo}}, {{user_input}}.")
    print("   - Ad ogni esecuzione, Opik tiene traccia del commit/versione del prompt usato.")
    print("\n2. SEZIONE 'Traces' (Tracce):")
    print("   - Troverai una traccia principale chiamata 'run_agent'.")
    print(f"   - Nei TAGS vedrai '{profilo_test}', 'AION-Core-Run' e 'Self-Hosted'.")
    print("   - Nei METADATA vedrai le impostazioni del modello (temperatura, max_tokens) e il profilo.")
    print("\n3. SEZIONE 'Threads':")
    print("   - Troverai una sessione di chat / thread con ID associato.")
    print("   - Potrai visualizzare la conversazione completa su più turni e il relativo feedback score.")
    print("\n4. ALBERO DEI NESTED SPANS (Spans Nidificati):")
    print("   - Cliccando sulla traccia 'run_agent', vedrai l'albero di esecuzione:")
    print("     ├── skill_ricerca_db (Span della Skill di ricerca)")
    print("     │    └── execute_tool_ricerca (Span di tipo TOOL con input/output del DB)")
    print("     ├── skill_calcolo_metrico (Span della Skill di calcolo)")
    print("     └── call_llm_api (Span di tipo LLM con token, parametri ed input/output del modello)")
    print("="*80 + "\n")
