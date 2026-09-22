# Introduzione di Oggetti AION Custom per PII Review
Questo documento descrive il piano di migrazione per sostituire le fittizie risposte Assistant/OpenAI usate per comunicare gli alert privacy (`pii_review` e `pii_replacements`) con un oggetto custom proprietario di AION.

## Analisi del Problema Attuale
Attualmente, quando il Privacy Filter rileva dei dati sensibili, genera un artefatto XML (es. `<aion_artifact type="pii_review"...>`) e lo maschera come un normale messaggio `assistant` all'interno di un oggetto compatibile OpenAI (`chat.completion` o `chat.completion.chunk`).
Sebbene questo permetta la comunicazione con i client, causa problemi significativi:
1. **Inquinamento del Contesto (Chat History):** Il frontend tenderà a salvare questo oggetto tra i messaggi scambiati e al turno successivo verrà rinviato all'LLM (il quale si troverebbe a leggere strani tag XML fuori contesto, potendo dar luogo ad allucinazioni).
2. **Ambiguità Semantica:** Confondere metadati di sistema (un alert di privacy) con la risposta del modello è semanticamente scorretto e fragile da gestire via Regex nel client.

## Nuova Struttura dell'Oggetto
Restituiremo un oggetto puro JSON fuori dallo standard di un `ChatCompletion`. In questo modo il frontend intercetterà l'oggetto riconoscendone l'identità univoca. 
Lo schema proposto è:
```json
{
  "object": "aion.event",
  "event_type": "pii_review", // oppure "pii_replacements"
  "data": {
    "censored_prompt": "...",
    "pii_review_token": "..."
  }
}
```

> [!CAUTION]
> **Problematiche Identificate (Da considerare sul lato Client / Frontend):**
> Sebbene il backend sia in grado di erogare questo oggetto senza problemi, **un client che usa librerie rigorose** (es. l'SDK ufficiale OpenAI in Python/Node che usa validazione Pydantic o Zod) **crasha istantaneamente** (lanciando un `ValidationError`), perché il parametro `object` differisce da `chat.completion`. 
> Poiché `aion_privacy_filter_review_content=True` è inviato *solamente* dal tuo client AION Agent (estensione), questo va bene. Assicurati che lato AION Agent la serializzazione JSON dell'SSE sia fatta con parsing flessibile, e non tramite SDK OpenAI restrittivi.

---

## Modifiche Proposte (AionRouter)

### 1. `aion/routing/engine.py` (PII Review)
#### [MODIFY] `engine.py`
Sostituire la logica che genera `artifact_xml` e restituisce il dummy stream con il nuovo payload.
```python
aion_event = {
    "object": "aion.event",
    "event_type": "pii_review",
    "data": {
        "censored_prompt": censored_messages_text,
        "pii_review_token": pii_token
    }
}
if ctx.stream:
    async def _event_stream():
        yield aion_event
    return _event_stream()
else:
    return aion_event
```

### 2. `aion/routing/engine.py` (Cost Tracking)
#### [MODIFY] `engine.py`
Evitare che il sistema di tracciamento costi cerchi di estrarre `usage` o `choices` da questo evento custom.
```diff
- if isinstance(response, dict):
+ if isinstance(response, dict) and response.get("object") != "aion.event":
      await self.cost_tracker.record( ... )
```

### 3. `aion/routing/engine.py` (PII Replacements in Stream)
#### [MODIFY] `engine.py`
Allineare anche la notifica delle replacement iniettate alla fine dello stream, sostituendo il finto `chatcmpl-pii-replacements`.
```python
_pii_extra_chunk = {
    "object": "aion.event",
    "event_type": "pii_replacements",
    "data": {
        "replacements": [
            {
                "message_index": replacement.message_index,
                "role": replacement.role,
                "censored_content": replacement.censored_content,
            }
        ]
    }
}
```

### 4. Gestione Gateway e Normalizer (`aion/gateway/response_normalize.py`)
> [!NOTE]
> Il modulo `response_normalize.py` è già protetto, siccome usa `chunk.get("choices") or []`. Se elaborerà il nostro `aion.event` si limiterà a skippare l'operazione di pulizia tool_calls e lo lascerà inalterato. In `chat.py`, il modulo SSE restituirà regolarmente `data: {"object": "aion.event", ...}`. Nessuna ulteriore modifica necessaria ai wrapper FastAPI.

## Open Questions
- **AION Agent (Client)**: Il tuo AION Agent è già in grado di intercettare oggetti SSE stream che non corrispondono a `chat.completion.chunk`? In caso negativo ti ritroveresti l'interfaccia bloccata finché non lo allinei a ricevere la prop `event_type`. Confermi di voler procedere a restituire `{"object": "aion.event", ...}`?
