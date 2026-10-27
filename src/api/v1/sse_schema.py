"""Eventi SSE di ``POST /v1/chat/stream`` e ``GET /v1/chat/stream/reconnect/{id}``.

Ogni frame ``event: message`` ha nel campo ``data`` un JSON validato da
``ChatStreamEvent`` (union discriminata su ``type``). Gli errori fuori dalla
pipeline arrivano come ``event: error`` con ``SseStreamErrorFrame``.

I modelli documentano il formato e sono usati dai test e dallo schema OpenAPI:
la pipeline continua a emettere dict. ``extra="allow"``: i campi non
dichiarati sono ammessi, i client devono ignorare campi e ``type`` sconosciuti.
Formato del wire e ordine degli eventi: ``docs/api-and-runtime/sse-events.md``.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sse_starlette.sse import EventSourceResponse

Number = Union[int, float]


class _Event(BaseModel):
    model_config = ConfigDict(extra="allow")


# --- turno -----------------------------------------------------------------


class SseTurnStarted(_Event):
    """Sempre il primo evento del turno."""

    type: Literal["turn_started"]
    user_message_id: str
    assistant_message_id: str


class SseToken(_Event):
    type: Literal["token"]
    content: str


class SseReasoning(_Event):
    type: Literal["reasoning"]
    reasoning: str


class SseStreamEnd(_Event):
    """Fine di una chiamata LLM (non del turno)."""

    type: Literal["stream_end"]
    finish_reason: Optional[str] = None


class SseTurnStatus(_Event):
    """Avviso informativo (guardie, memoria, output troncato)."""

    type: Literal["turn_status"]
    phase: str
    message: str
    tool: Optional[str] = None


class SseTurnOutcome(_Event):
    """Esito anomalo del turno (risposta mancante, interruzione)."""

    type: Literal["turn_outcome"]
    code: Optional[str] = None
    message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class SsePromptSnapshot(_Event):
    type: Literal["prompt_snapshot"]
    assistant_message_id: Optional[str] = None
    snapshot: Any = None


class SsePiiMessagesToReplace(_Event):
    type: Literal["pii_messages_to_replace"]
    replacements: List[Any]


class SseError(_Event):
    """Errore del turno; può essere seguito da ``final``."""

    type: Literal["error"]
    content: str


class SseLlmError(_Event):
    """Errore della chiamata LLM, classificato in ``code``."""

    type: Literal["llm_error"]
    code: str
    message: str
    content: str = Field(description="Uguale a message (client legacy).")
    exc_type: Optional[str] = None


class SseFinal(_Event):
    """Ultimo evento dati di un turno concluso; ``text`` è la risposta."""

    type: Literal["final"]
    text: str


# --- tool ------------------------------------------------------------------


class SseToolStart(_Event):
    type: Literal["tool_start"]
    id: Optional[str] = None
    name: Optional[str] = None
    input: Any = None


class SseToolEnd(_Event):
    type: Literal["tool_end"]
    id: Optional[str] = None
    name: Optional[str] = None
    input: Any = None
    output: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    result: Optional[str] = Field(
        default=None, description="Solo per un tool saltato (con error=true)."
    )
    error: Optional[bool] = None


class SseToolError(_Event):
    type: Literal["tool_error"]
    id: Optional[str] = None
    name: Optional[str] = None
    input: Any = None
    error: str


class SseOrchestrationPlanPending(_Event):
    """Piano di esecuzione registrato, in attesa di approvazione."""

    type: Literal["orchestration_plan_pending"]
    plan_id: str
    plan: Optional[Dict[str, Any]] = None
    plan_markdown: Optional[str] = None
    todos: Optional[List[Any]] = None
    annotations: Optional[Dict[str, Any]] = None
    revision: Optional[int] = None
    goal: Optional[str] = None


SseToolEventPayload = Annotated[
    Union[SseToolStart, SseToolEnd, SseToolError, SseOrchestrationPlanPending],
    Field(discriminator="type"),
]


class SseToolEvent(_Event):
    type: Literal["tool_event"]
    event: SseToolEventPayload


# --- artifact --------------------------------------------------------------


class SseArtifactInfo(_Event):
    identifier: str
    type: Optional[str] = None
    title: Optional[str] = None
    auto_execute: Optional[bool] = None
    path: Optional[str] = None
    storage_key: Optional[str] = None
    version: Optional[int] = None
    saved: Optional[bool] = None
    execution: Any = None


class SseArtifactStart(_Event):
    type: Literal["artifact_start"]
    artifact: SseArtifactInfo


class SseArtifactContent(_Event):
    type: Literal["artifact_content"]
    content: str
    artifact_id: Optional[str] = None


class SseArtifactEnd(_Event):
    type: Literal["artifact_end"]
    artifact: SseArtifactInfo


# --- piano -----------------------------------------------------------------


class SsePlanPhase(_Event):
    type: Literal["plan_phase"]
    phase: str
    plan_id: Optional[str] = None
    message: Optional[str] = None


class SsePlanProgress(_Event):
    type: Literal["plan_progress"]
    plan_markdown: str
    plan_id: Optional[str] = None
    revision: Optional[int] = None
    tasks_count: Optional[int] = None


class SsePlanError(_Event):
    type: Literal["plan_error"]
    plan_id: Optional[str] = None
    message: str


# --- contesto --------------------------------------------------------------


class SseContextBudgetPart(_Event):
    key: str
    tokens: int
    pct: Number


class SseContextBudget(_Event):
    """Occupazione della finestra di contesto."""

    type: Literal["context_budget"]
    phase: str
    total: int
    max_prompt: int
    trigger: int
    message_count: int
    pct: Number
    parts: List[SseContextBudgetPart]


class SseContextCompacting(_Event):
    type: Literal["context_compacting"]
    active: bool
    tokens: Optional[int] = None
    trigger: Optional[int] = None
    phase: Optional[str] = None
    mid_turn: Optional[bool] = None


class SseContextRecovery(_Event):
    type: Literal["context_recovery"]
    attempt: int
    message: str
    tokens_before: Optional[int] = None
    tokens_after: Optional[int] = None


ChatStreamEvent = Annotated[
    Union[
        SseTurnStarted,
        SseToken,
        SseReasoning,
        SseStreamEnd,
        SseTurnStatus,
        SseTurnOutcome,
        SsePromptSnapshot,
        SsePiiMessagesToReplace,
        SseError,
        SseLlmError,
        SseFinal,
        SseToolEvent,
        SseOrchestrationPlanPending,
        SseArtifactStart,
        SseArtifactContent,
        SseArtifactEnd,
        SsePlanPhase,
        SsePlanProgress,
        SsePlanError,
        SseContextBudget,
        SseContextCompacting,
        SseContextRecovery,
    ],
    Field(discriminator="type"),
]


class SseStreamErrorFrame(BaseModel):
    """``data`` di un frame ``event: error`` (senza ``type``); chiude lo stream."""

    model_config = ConfigDict(extra="allow")

    error: str
    code: Optional[str] = None
    available_slugs: Optional[List[str]] = None


chat_stream_event_adapter: TypeAdapter[Any] = TypeAdapter(ChatStreamEvent)


class EventStreamResponse(EventSourceResponse):
    """Solo per OpenAPI: ``EventSourceResponse`` imposta ``media_type`` nell'istanza,
    FastAPI lo legge dalla classe per il content type della risposta."""

    media_type = "text/event-stream"


def stream_openapi_response() -> Dict[int, Dict[str, Any]]:
    """``responses`` per le route SSE: schema di ``data`` per i due tipi di frame."""
    return {
        200: {
            "model": Union[ChatStreamEvent, SseStreamErrorFrame],
            "description": (
                "Stream SSE. Frame `event: message` con `data` = ChatStreamEvent; "
                "frame `event: error` con `data` = SseStreamErrorFrame. "
                "Vedi docs/api-and-runtime/sse-events.md."
            ),
        }
    }
