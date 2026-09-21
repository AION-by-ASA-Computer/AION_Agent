"""
LLM-assisted MCP schema & metadata enrichment with guaranteed static fallback.

Analizza i file del server MCP (README, .env.example, codice) tramite LLM locale/remoto
per generare etichette semplici, istruzioni contestuali, tipi e categorie.
In caso di assenza, timeout o errore dell'LLM, esegue il fallback trasparente al
motore semantico a regole.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from .data.engine import get_async_session_maker
from .data.models import McpServerConfig
from .mcp_credential_discovery import (
    CredentialDiscoveryResult,
    discover_mcp_credentials,
    merge_schema_sources,
)
from .mcp_server_files import read_mcp_server_files

logger = logging.getLogger("aion.mcp_llm_enricher")

_LLM_ENRICH_TIMEOUT: float = float(os.getenv("AION_MCP_LLM_ENRICH_TIMEOUT", "15"))


def _clean_json_response(raw_text: str) -> str:
    """Estrae il blocco JSON valido da una risposta markdown o testo libero."""
    text = (raw_text or "").strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Se ci sono blocchi multipli, cerca la prima parentesi graffa
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


async def enrich_mcp_schema_with_llm(
    server_slug: str,
    server_config: Optional[Dict[str, Any]] = None,
    *,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Arricchisce lo schema di un server MCP usando l'LLM con fallback statico garantito.

    1. Calcola sempre prima lo schema di base dal motore a regole statico.
    2. Prova a interrogare l'LLM configurato sul server.
    3. Se l'LLM risponde con successo, unisce e arricchisce i campi (label amichevoli, guide, default).
    4. Se l'LLM fallisce o non è configurato, restituisce immediatamente lo schema statico.
    5. Salva il risultato nel database SQLite (mcp_server_configs).
    """
    cfg = server_config or {}

    # 1. Baseline garantita tramite motore a regole
    baseline_discovery: CredentialDiscoveryResult = discover_mcp_credentials(
        server_slug, cfg
    )
    baseline_schema = list(baseline_discovery.schema or [])
    baseline_mode = baseline_discovery.credential_mode_hint or "none"

    result_payload: Dict[str, Any] = {
        "server_slug": server_slug,
        "display_name": None,
        "description": None,
        "credential_mode": baseline_mode,
        "credential_schema": baseline_schema,
        "enriched_by": "static_rules",
    }

    # 2. Verifica disponibilità file o contesto
    server_files_context = read_mcp_server_files(server_slug)

    # 3. Chiamata LLM
    try:
        from src.runtime.llm_adapter import resolve_llm_credentials

        api_url, model_name, api_key = resolve_llm_credentials()

        # Prompt di sistema strutturato
        system_prompt = (
            "Sei un assistente per la configurazione dei server MCP (Model Context Protocol). "
            "Il tuo obiettivo è analizzare i file sorgente e documentazione di un server MCP (README, .env.example, codice) "
            "e generare uno schema di configurazione chiaro, pulito e semplice per utenti finali non tecnici.\n\n"
            "REGOLE IMPORTANTI:\n"
            "1. Per ogni variabile d'ambiente, genera un'etichetta amichevole in italiano ('label') in linguaggio naturale "
            "es. 'Server Posta in Arrivo (IMAP)', 'Password per le App', 'Chiave API Stripe', 'Scarica Allegati', 'Porta del Servizio'.\n"
            "2. Fornisci una breve 'description' in italiano utile per l'utente, spiegando dove trovare la credenziale o cosa fa.\n"
            "3. Identifica il 'type': 'password' (per secret, token, password, API key, access key), 'boolean' (per flag/attivazioni true/false), "
            "'number' (per porte, timeout, valori numerici) o 'text' (per email, username, url, host, id).\n"
            "4. Assegna 'category': 'basic' (credenziali e parametri essenziali e minimi per far funzionare il server) "
            "o 'advanced' (impostazioni tecniche secondarie: timeout, log level, directory temporanee, flag facoltativi).\n"
            "5. Se noti valori di default nel README o .env.example (es. porta 993, 587, true, https://...), includi 'default_value'.\n"
            "6. Imposta 'required': true per le variabili essenziali di categoria 'basic' senza cui il server non può avviarsi.\n\n"
            "Rispondi ESCLUSIVAMENTE con un oggetto JSON valido nel seguente formato:\n"
            "{\n"
            '  "display_name": "Nome Semplice del Servizio (es. Email IMAP/SMTP, Stripe, GitHub, Notion)",\n'
            '  "description": "Breve descrizione in italiano di cosa fa questa integrazione per l\'utente",\n'
            '  "credential_mode": "org_shared" | "per_user" | "none",\n'
            '  "minimal_setup_guide": "Breve consiglio in 1 riga su cosa serve per iniziare subito",\n'
            '  "fields": [\n'
            "    {\n"
            '      "key": "NOME_VARIABILE_ENV",\n'
            '      "label": "Nome Semplificato in Italiano",\n'
            '      "description": "Istruzioni su dove trovare la chiave o cosa inserire",\n'
            '      "type": "text" | "password" | "boolean" | "number",\n'
            '      "category": "basic" | "advanced",\n'
            '      "required": true | false,\n'
            '      "default_value": "valore opzionale"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        user_content = (
            f"Server Slug: {server_slug}\n\n"
            f"Variabili rilevate dallo scanner statico: {[f.get('key') for f in baseline_schema]}\n\n"
            f"Contesto file del server MCP:\n{server_files_context or '(Nessun file aggiuntivo disponibile)'}"
        )

        import litellm

        llm_model = model_name
        if "/" not in llm_model and not llm_model.startswith("openai/"):
            llm_model = f"openai/{llm_model}"

        response = await litellm.acompletion(
            model=llm_model,
            api_base=api_url,
            api_key=api_key,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            timeout=_LLM_ENRICH_TIMEOUT,
            temperature=0.1,
            max_tokens=1500,
        )

        content = ""
        if response and response.choices and len(response.choices) > 0:
            msg = response.choices[0].message
            content = str(getattr(msg, "content", "") or "")

        cleaned_json = _clean_json_response(content)
        parsed_data = json.loads(cleaned_json)

        if isinstance(parsed_data, dict):
            llm_fields = parsed_data.get("fields") or []
            if isinstance(llm_fields, list) and len(llm_fields) > 0:
                # Unione tra schema statico di base e schema arricchito da LLM
                merged_schema = merge_schema_sources(
                    catalog_schema=llm_fields,
                    discovered_schema=baseline_schema,
                )
                result_payload["credential_schema"] = merged_schema
                result_payload["display_name"] = parsed_data.get("display_name")
                result_payload["description"] = parsed_data.get("description")
                result_payload["minimal_setup_guide"] = parsed_data.get(
                    "minimal_setup_guide"
                )
                if parsed_data.get("credential_mode") in (
                    "per_user",
                    "org_shared",
                    "none",
                ):
                    result_payload["credential_mode"] = parsed_data["credential_mode"]
                result_payload["enriched_by"] = "llm"
                logger.info(
                    "LLM schema enrichment riuscito per %s (%d campi)",
                    server_slug,
                    len(merged_schema),
                )
    except Exception as ex:
        logger.info(
            "LLM enrichment non disponibile o fallito per %s (%s). Uso fallback statico a regole.",
            server_slug,
            ex,
        )

    # 4. Persistenza nel database SQLite (mcp_server_configs)
    try:
        async with get_async_session_maker()() as session:
            row = (
                await session.execute(
                    McpServerConfig.__table__.select().where(
                        McpServerConfig.server_slug == server_slug
                    )
                )
            ).first()

            schema_json = json.dumps(
                result_payload["credential_schema"], ensure_ascii=False
            )
            mode = result_payload["credential_mode"]
            req_user = (
                mode == "per_user" and len(result_payload["credential_schema"]) > 0
            )

            if row:
                stmt = (
                    McpServerConfig.__table__.update()
                    .where(McpServerConfig.server_slug == server_slug)
                    .values(
                        credential_schema_json=schema_json,
                        credential_mode=mode,
                        requires_user_credentials=req_user,
                        display_name=result_payload.get("display_name")
                        or row.display_name,
                        description=result_payload.get("description")
                        or row.description,
                    )
                )
                await session.execute(stmt)
            else:
                from src.data.ids import new_uuid7_str

                new_row = McpServerConfig(
                    id=new_uuid7_str(),
                    server_slug=server_slug,
                    display_name=result_payload.get("display_name")
                    or server_slug.replace("-", " ").title(),
                    description=result_payload.get("description"),
                    credential_mode=mode,
                    requires_user_credentials=req_user,
                    credential_schema_json=schema_json,
                )
                session.add(new_row)
            await session.commit()
    except Exception as db_ex:
        logger.warning(
            "Impossibile salvare schema arricchito per %s in DB: %s",
            server_slug,
            db_ex,
        )

    return result_payload
