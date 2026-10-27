"""Modelli di risposta delle route del contratto (``src/api/contract.py``).

Documentano la forma delle risposte senza cambiarla:

- ``extra="allow"``: i campi non dichiarati passano invariati;
- le route con chiavi condizionali usano ``response_model_exclude_unset=True``,
  così un campo opzionale non restituito dall'handler resta assente;
- i tipi sono larghi quanto i dati salvati (una validazione fallita sarebbe un
  500 su dati che oggi passano).

Lo snapshot ``src/test/test_api_contract_responses.py`` verifica che le
risposte restino identiche.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

# Come ``jsonable_encoder``: ``isoformat()`` (``+00:00``, non ``Z``).
IsoDatetime = Annotated[
    datetime, PlainSerializer(lambda d: d.isoformat(), return_type=str)
]


# ``float`` convertirebbe ``3600`` in ``3600.0``: gli interi restano interi.
Number = Union[int, float]


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class ConversationCreated(_Open):
    id: str
    tenant_id: str
    user_id: str
    profile_slug: str
    title: Optional[str] = None
    message_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


class ChatStopResponse(_Open):
    ok: bool
    conversation_id: str
    session_id: str = Field(description="Stesso valore di conversation_id (legacy).")


class StreamStatus(_Open):
    """Con ``active=false`` gli altri campi sono assenti."""

    active: bool
    assistant_message_id: Optional[str] = None
    user_message_id: Optional[str] = None
    profile_name: Optional[str] = None
    started_at: Optional[Number] = Field(
        default=None, description="Inizio del turno, epoch in secondi."
    )


class StepOut(_Open):
    id: str
    name: str
    type: str
    input: Optional[str] = None
    output: Optional[str] = None
    is_error: bool = False
    metadata_json: Optional[str] = Field(
        default=None, description="JSON serializzato come stringa, non parsificato."
    )
    created_at: Optional[IsoDatetime] = None


class ArtifactOut(_Open):
    id: str
    storage_key: str
    original_name: str
    mime: str
    size_bytes: int
    kind: str
    created_at: Optional[IsoDatetime] = None


# Segmenti della timeline generati dal server (``TimelineBuilder``,
# ``reconstruct_timeline_from_legacy``). ``strict`` evita conversioni: un
# segmento che non corrisponde (es. scritto dal client con
# ``PATCH .../timeline``) passa come dict, invariato.
class _Segment(_Open):
    model_config = ConfigDict(extra="allow", strict=True)


class ReasoningSegment(_Segment):
    kind: Literal["reasoning"]
    id: str
    content: str


class TextSegment(_Segment):
    kind: Literal["text"]
    id: str
    content: str


class ToolSegment(_Segment):
    kind: Literal["tool"]
    id: str
    name: str
    input: Any = None
    output: Optional[str] = None
    status: Literal["running", "done", "error"]
    isError: Optional[bool] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None


class ArtifactSegment(_Segment):
    kind: Literal["artifact"]
    id: str
    title: str
    artType: str
    buffer: str = ""
    savedPath: Optional[str] = None
    version: Optional[int] = None
    execution: Optional[str] = None


class StatusSegment(_Segment):
    kind: Literal["status"]
    id: str
    content: str
    tone: Literal["info", "warning"]
    outcomeCode: Optional[str] = None
    outcomeDetails: Optional[Dict[str, Any]] = None


TimelineSegment = Annotated[
    Union[ReasoningSegment, TextSegment, ToolSegment, ArtifactSegment, StatusSegment],
    Field(discriminator="kind"),
]


class MessageOut(_Open):
    id: str
    role: str
    content: str
    reasoning: Optional[str] = None
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    created_at: Optional[IsoDatetime] = None
    seq: int
    steps: List[StepOut] = Field(default_factory=list)
    artifacts: List[ArtifactOut] = Field(default_factory=list)
    rating: Optional[int] = None
    feedback_comment: Optional[str] = None
    archived: Optional[bool] = Field(
        default=None, description="Presente (true) solo se il messaggio è archiviato."
    )
    archived_reason: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Presente solo se il messaggio ha metadata."
    )
    timeline: Optional[List[Union[TimelineSegment, Dict[str, Any]]]] = Field(
        default=None, description="Solo per role=assistant."
    )


class MessagesResponse(_Open):
    messages: List[MessageOut]


class UpdatedResponse(_Open):
    updated: bool
    message_id: str


class ChartOut(_Open):
    """Grafico in coda; un elemento Redis non decodificabile diventa ``{raw}``."""

    query: Optional[str] = None
    data: Optional[List[Any]] = None
    chart_kind: Optional[str] = None
    x_key: Optional[str] = None
    series_keys: Optional[List[str]] = None
    stacked: Optional[bool] = None
    legend_off: Optional[bool] = None
    y_label: Optional[str] = None
    range_seconds: Optional[Number] = None
    step_seconds: Optional[Number] = None
    raw: Optional[str] = None


class ChartsResponse(_Open):
    charts: List[ChartOut]


class StepSummary(_Open):
    id: str
    name: str
    type: str
    input: Optional[str] = None
    output: Optional[str] = None
    parent_id: Optional[str] = None


class StepsResponse(_Open):
    data: List[StepSummary]


class ProfileSummary(_Open):
    name: str
    description: Optional[str] = None
    slug: str
    skills: List[Any] = Field(default_factory=list)
    mcp_servers: List[Any] = Field(default_factory=list)
    native_tool_groups: List[Any] = Field(default_factory=list)
    critical_skills: List[Any] = Field(default_factory=list)
