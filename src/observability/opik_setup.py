import os
import logging
import src.aion_env  # noqa: F401 — MUST be first import to load environment variables from .env

# Configurazione del logger locale
logger = logging.getLogger("aion.observability.opik")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Configura le variabili d'ambiente per l'SDK di Opik (Self-Hosted local instance)
# Inietta i valori configurati nel file .env se presenti, altrimenti imposta i default.
OPIK_ENABLED = os.getenv("AION_OPIK_ENABLED", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

if OPIK_ENABLED:
    OPIK_URL = os.getenv("OPIK_URL_OVERRIDE", "http://localhost:5173/api").strip("'\"")
    OPIK_PROJECT = os.getenv("OPIK_PROJECT_NAME", "AION-Agent").strip("'\"")

    os.environ["OPIK_URL_OVERRIDE"] = OPIK_URL
    os.environ["OPIK_PROJECT_NAME"] = OPIK_PROJECT

    # Per l'istanza locale di Opik non è richiesta alcuna API key, ma se il client dovesse richiederla,
    # ne impostiamo una fittizia per evitare errori di validazione del client.
    if not os.getenv("OPIK_API_KEY"):
        os.environ["OPIK_API_KEY"] = "local-self-hosted-placeholder"

    logger.info(
        f"Inizializzazione SDK Opik. Target URL: {OPIK_URL} | Progetto: {OPIK_PROJECT}"
    )

    # Ritarda l'importazione di Opik finché l'ambiente non è configurato correttamente
    try:
        from opik import Opik

        opik_client = Opik()
        OPIK_AVAILABLE = True
    except ImportError:
        OpikException = Exception  # type: ignore[misc, assignment]
        opik_client = None
        OPIK_AVAILABLE = False
        logger.warning(
            "SDK Opik non installato — telemetria Opik disabilitata. "
            "Eseguire: uv pip install -r requirements.txt"
        )
    except Exception as e:
        OpikException = Exception  # type: ignore[misc, assignment]
        opik_client = None
        OPIK_AVAILABLE = False
        logger.error("Errore durante l'inizializzazione del client Opik: %s", e)
else:
    OpikException = Exception  # type: ignore[misc, assignment]
    opik_client = None
    OPIK_AVAILABLE = False
    logger.info("Telemetria Opik disabilitata tramite AION_OPIK_ENABLED=0")


def get_or_create_prompt(
    prompt_name: str, template_content: str, metadata: dict = None
):
    """
    Verifica se un prompt (es. 'agente-core-prompt') esiste già nella Prompt Library di Opik.
    Se non esiste (o se get_prompt ritorna None), lo crea con dei placeholder (es. {{profilo}}, {{user_input}}).
    Recupera e ritorna l'ultima versione del prompt da utilizzare.

    Args:
        prompt_name (str): Il nome del prompt da cercare/creare.
        template_content (str): Il testo del prompt con placeholder jinja-style (es. {{profilo}}).
        metadata (dict, optional): Metadati aggiuntivi associati al prompt.

    Returns:
        opik.objects.prompt.Prompt: L'oggetto Prompt di Opik pronto per essere formattato e tracciato.
    """
    if not OPIK_AVAILABLE or opik_client is None:
        raise RuntimeError("Opik SDK non disponibile")

    prompt = None
    try:
        logger.info(
            f"Tentativo di recupero prompt '{prompt_name}' dalla Prompt Library..."
        )
        # Cerca il prompt per nome
        prompt = opik_client.get_prompt(name=prompt_name)
        if prompt is not None:
            # Se il prompt esiste, verifichiamo se il template è lo stesso.
            # Se è diverso, creiamo una nuova versione (commit) chiamando create_prompt.
            if prompt.prompt != template_content:
                logger.info(
                    f"Template per '{prompt_name}' è cambiato. Creazione di una nuova versione in corso..."
                )
                prompt = opik_client.create_prompt(
                    name=prompt_name, prompt=template_content, metadata=metadata or {}
                )
            else:
                logger.info(
                    f"Prompt '{prompt_name}' recuperato con successo (nessuna modifica)."
                )
            return prompt
        logger.info(
            f"Prompt '{prompt_name}' non trovato (ritornato None). Creazione in corso..."
        )
    except Exception as e:
        logger.info(
            f"Prompt '{prompt_name}' non recuperato ({e}). Creazione in corso..."
        )

    try:
        # Se non esiste o il recupero fallisce, crea il prompt nella libreria
        prompt = opik_client.create_prompt(
            name=prompt_name, prompt=template_content, metadata=metadata or {}
        )
        logger.info(f"Prompt '{prompt_name}' creato con successo.")
        return prompt
    except Exception as create_err:
        logger.error(f"Impossibile creare il prompt '{prompt_name}': {create_err}")
        raise create_err


async def chiudi_sessione_e_valuta(session_id: str):
    """
    Invia metriche a livello di thread (sessione globale) a Opik al termine dell'interazione.

    Args:
        session_id (str): L'ID univoco del thread/sessione.
    """
    try:
        logger.info(
            f"Invio feedback score a livello di thread '{session_id}' ad Opik..."
        )
        opik_client.log_threads_feedback_scores(
            scores=[{"id": session_id, "name": "risoluzione_problema", "value": 1.0}]
        )
        logger.info(
            f"Feedback score per il thread '{session_id}' inviato con successo."
        )
    except Exception as e:
        logger.error(
            f"Errore durante l'invio del feedback score del thread {session_id}: {e}"
        )
