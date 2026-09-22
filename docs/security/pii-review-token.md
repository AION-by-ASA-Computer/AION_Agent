---
sidebar_position: 3
title: PII review token
description: Come il token di conferma PII viene propagato dal browser fino al gateway SmartRoute attraverso tutta la catena AION.
---

# PII review token — catena di propagazione completa

Quando l'utente conferma la revisione di contenuti PII nel chat-ui, un **token di conferma** (`aion_pii_review_token`) viene generato e deve raggiungere il gateway SmartRoute per sbloccare la richiesta bloccata dal filtro privacy.

Questa pagina documenta i passaggi esatti della catena, i file coinvolti e le trappole in cui è facile cadere.

---

## Schema della catena

```
Browser (chat-ui)
    │  opts.aion_pii_review_token
    ▼
ChatWorkspace.tsx  →  runChatRequest(message, { aion_pii_review_token })
    │  campo nel payload JSON
    ▼
lib/api/aion.ts  →  postChatStream({ …, aion_pii_review_token })
    │  HTTP POST /chat-ui/conversations/:id/messages
    ▼
src/api/v1/chat.py  →  ChatStreamBody.aion_pii_review_token
    │  inserito in metadata{}
    ▼
src/agent_pipeline.py  →  extra_body["aion_pii_review_token"]
    │  HTTP POST /v1/chat/completions (→ SmartRoute)
    ▼
SmartRoute: aion/gateway/routers/chat.py  →  ChatCompletionRequest.aion_pii_review_token
    │  passato a RoutingContext.pii_review_token
    ▼
Filtro privacy / logica di bypass ✓
```

---

## Passaggi dettagliati

### 1. Chat-UI — `ChatWorkspace.tsx`

Il componente chiama `runChatRequest` passando il token nelle opzioni:

```tsx
// components/chat/ChatWorkspace.tsx
void runChatRequest(finalPrompt, {
  aion_pii_review_token: piiToken,
});
```

`runChatRequest` accetta `opts.aion_pii_review_token` e lo include nel payload
della chiamata `postChatStream`:

```tsx
const stream = await postChatStream(
  {
    // …altri campi…
    aion_privacy_filter_review_content: piiReviewEnabled,
    aion_pii_review_token: opts?.aion_pii_review_token,   // ← obbligatorio
  },
  token,
  abortRef.current.signal
);
```

:::caution
Se `aion_pii_review_token` non viene passato in `opts` **e** aggiunto esplicitamente
al payload di `postChatStream`, il campo non arriva al backend
(Pydantic scarta i campi non dichiarati).
:::

### 1.1 Riscrittura del messaggio originale (In-place replace)

Quando il token viene inviato con l'azione di conferma (`confirm`), il frontend **non crea un nuovo messaggio utente**. Al contrario, sostituisce il testo del messaggio originale con il testo censurato per evitare duplicazioni nella chat.
Questo avviene tramite due meccanismi:

1. **Frontend State**: La funzione `handlePiiAction` risale al `user_message_id` originale (cercando il messaggio utente che precede il turno dell'assistente). Questo ID viene passato come `userMessageIdOverride` a `runChatRequest`, che aggiorna la *bubble* utente esistente in-place.
2. **Backend Storage**: Il backend riceve la nuova richiesta (`postChatStream`) con lo stesso `user_message_id`. L'API (`POST /chat-ui/conversations/{conv_id}/messages` tramite `saveChatMessage` e successivamente durante il processing della pipeline) esegue un **upsert** (aggiornamento) del contenuto nel DB, sovrascrivendo permanentemente il messaggio originale non censurato.

### 2. Tipo TypeScript — `lib/api/aion.ts`

Il tipo `ChatStreamRequest` deve dichiarare il campo:

```ts
// lib/api/aion.ts
export type ChatStreamRequest = {
  // …
  aion_privacy_filter_review_content?: boolean;
  aion_pii_review_token?: string;   // ← deve essere presente
};
```

### 3. Backend FastAPI — `src/api/v1/chat.py`

Il modello Pydantic `ChatStreamBody` deve dichiarare il campo; senza
dichiarazione esplicita il valore viene silenziosamente scartato dal parser:

```python
# src/api/v1/chat.py
class ChatStreamBody(BaseModel):
    # …
    aion_privacy_filter_review_content: Optional[bool] = Field(default=None)
    aion_pii_review_token: Optional[str] = Field(default=None)   # ← obbligatorio
```

Il valore viene poi iniettato nel dict `metadata` passato alla pipeline:

```python
metadata={
    **(body.metadata or {}),
    **({"aion_privacy_filter_review_content": body.aion_privacy_filter_review_content}
       if body.aion_privacy_filter_review_content is not None else {}),
    **({"aion_pii_review_token": body.aion_pii_review_token}
       if getattr(body, "aion_pii_review_token", None) is not None else {}),
},
```

### 4. Pipeline agente — `src/agent_pipeline.py`

Prima di ogni chiamata al modello LLM, la pipeline costruisce `extra_body` da
allegare alla request verso SmartRoute. **Entrambi** i flag PII devono essere
copiati da `metadata` in `extra_body`:

```python
# src/agent_pipeline.py  ~L1774
if metadata and metadata.get("aion_privacy_filter_review_content") is not None:
    eb = dict(gen_kw.get("extra_body") or {})
    eb["aion_privacy_filter_review_content"] = metadata["aion_privacy_filter_review_content"]
    gen_kw["extra_body"] = eb

if metadata and metadata.get("aion_pii_review_token") is not None:
    eb = dict(gen_kw.get("extra_body") or {})
    eb["aion_pii_review_token"] = metadata["aion_pii_review_token"]
    gen_kw["extra_body"] = eb
```

:::warning
Questi due blocchi sono **separati e indipendenti**: se aggiungi un nuovo campo
PII in futuro, ricordati di aggiungere anche il relativo blocco qui.
Il token non viene mai copiato automaticamente — il passaggio va esplicitato.
:::

### 5. Gateway SmartRoute — `aion/gateway/routers/chat.py`

`ChatCompletionRequest` (con `model_config = ConfigDict(extra="allow")`) riceve
il token nell'`extra_body` e lo espone come attributo dichiarato:

```python
class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    # …
    aion_privacy_filter_review_content: bool | None = None
    aion_pii_review_token: str | None = None   # ← deve essere dichiarato
```

Viene poi passato al `RoutingContext`:

```python
ctx = RoutingContext(
    # …
    privacy_filter_review_content=body.aion_privacy_filter_review_content,
    pii_review_token=body.aion_pii_review_token,
)
```

---

## Checklist — quando aggiungi un nuovo flag PII-like

Segui questi 5 step nell'ordine:

1. **`ChatStreamRequest`** in `chat-ui/lib/api/aion.ts` — aggiungi il campo nel tipo TS
2. **`runChatRequest` opts** in `ChatWorkspace.tsx` — aggiungi il campo nel tipo `opts`
3. **payload `postChatStream`** in `ChatWorkspace.tsx` — includi il campo nel body
4. **`ChatStreamBody`** in `src/api/v1/chat.py` — dichiara il campo Pydantic
5. **`extra_body` merge** in `src/agent_pipeline.py` — copia il campo da `metadata` in `gen_kw["extra_body"]`
6. **`ChatCompletionRequest`** in SmartRoute — dichiara il campo nel modello gateway

---

## Debug rapido

| Sintomo | Causa più probabile |
|---------|---------------------|
| Campo `None` nel log del backend AION | Non dichiarato in `ChatStreamBody` (step 4) |
| Campo assente dal log del gateway | Non copiato in `extra_body` in `agent_pipeline.py` (step 5) |
| Campo correttamente nel log del gateway ma non in `RoutingContext` | Non dichiarato in `ChatCompletionRequest` nel gateway (step 6) |
| Campo TypeScript `undefined` | Manca dalla dichiarazione del tipo `ChatStreamRequest` (step 1) |
