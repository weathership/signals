from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SignalKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SIGNAL_KIND_UNSPECIFIED: _ClassVar[SignalKind]
    EXTERNAL_NAMESPACE_VIOLATION: _ClassVar[SignalKind]
    UNSATISFIABLE: _ClassVar[SignalKind]
    UNGROUNDED: _ClassVar[SignalKind]
    VERSION_DRIFT: _ClassVar[SignalKind]
    TX_ID_NOT_UUIDV7: _ClassVar[SignalKind]

class Disposition(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DISPOSITION_UNSPECIFIED: _ClassVar[Disposition]
    CORRECTED: _ClassVar[Disposition]
    COINED_LOCAL: _ClassVar[Disposition]
    UNRESOLVABLE: _ClassVar[Disposition]

class YieldReason(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    YIELD_REASON_UNSPECIFIED: _ClassVar[YieldReason]
    YIELD_REASON_PREEMPTED: _ClassVar[YieldReason]
    YIELD_REASON_COMPLETED: _ClassVar[YieldReason]
    YIELD_REASON_ORPHAN: _ClassVar[YieldReason]
    YIELD_REASON_UNIT_STOP: _ClassVar[YieldReason]
SIGNAL_KIND_UNSPECIFIED: SignalKind
EXTERNAL_NAMESPACE_VIOLATION: SignalKind
UNSATISFIABLE: SignalKind
UNGROUNDED: SignalKind
VERSION_DRIFT: SignalKind
TX_ID_NOT_UUIDV7: SignalKind
DISPOSITION_UNSPECIFIED: Disposition
CORRECTED: Disposition
COINED_LOCAL: Disposition
UNRESOLVABLE: Disposition
YIELD_REASON_UNSPECIFIED: YieldReason
YIELD_REASON_PREEMPTED: YieldReason
YIELD_REASON_COMPLETED: YieldReason
YIELD_REASON_ORPHAN: YieldReason
YIELD_REASON_UNIT_STOP: YieldReason

class Candidate(_message.Message):
    __slots__ = ("iri", "label", "kind", "score")
    IRI_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    SCORE_FIELD_NUMBER: _ClassVar[int]
    iri: str
    label: str
    kind: str
    score: float
    def __init__(self, iri: _Optional[str] = ..., label: _Optional[str] = ..., kind: _Optional[str] = ..., score: _Optional[float] = ...) -> None: ...

class BoundarySignal(_message.Message):
    __slots__ = ("kind", "subject", "offending", "reason", "authority")
    KIND_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_FIELD_NUMBER: _ClassVar[int]
    OFFENDING_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    AUTHORITY_FIELD_NUMBER: _ClassVar[int]
    kind: SignalKind
    subject: str
    offending: str
    reason: str
    authority: str
    def __init__(self, kind: _Optional[_Union[SignalKind, str]] = ..., subject: _Optional[str] = ..., offending: _Optional[str] = ..., reason: _Optional[str] = ..., authority: _Optional[str] = ...) -> None: ...

class SignalContext(_message.Message):
    __slots__ = ("candidates", "justification", "anchors", "rules")
    CANDIDATES_FIELD_NUMBER: _ClassVar[int]
    JUSTIFICATION_FIELD_NUMBER: _ClassVar[int]
    ANCHORS_FIELD_NUMBER: _ClassVar[int]
    RULES_FIELD_NUMBER: _ClassVar[int]
    candidates: _containers.RepeatedCompositeFieldContainer[Candidate]
    justification: _containers.RepeatedScalarFieldContainer[str]
    anchors: _containers.RepeatedCompositeFieldContainer[Candidate]
    rules: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, candidates: _Optional[_Iterable[_Union[Candidate, _Mapping]]] = ..., justification: _Optional[_Iterable[str]] = ..., anchors: _Optional[_Iterable[_Union[Candidate, _Mapping]]] = ..., rules: _Optional[_Iterable[str]] = ...) -> None: ...

class RemediationRequest(_message.Message):
    __slots__ = ("capability", "signal", "context", "max_tokens", "temperature")
    CAPABILITY_FIELD_NUMBER: _ClassVar[int]
    SIGNAL_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    MAX_TOKENS_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_FIELD_NUMBER: _ClassVar[int]
    capability: str
    signal: BoundarySignal
    context: SignalContext
    max_tokens: int
    temperature: float
    def __init__(self, capability: _Optional[str] = ..., signal: _Optional[_Union[BoundarySignal, _Mapping]] = ..., context: _Optional[_Union[SignalContext, _Mapping]] = ..., max_tokens: _Optional[int] = ..., temperature: _Optional[float] = ...) -> None: ...

class RemediationResponse(_message.Message):
    __slots__ = ("correction", "disposition", "rationale", "model", "reasoning_content", "completion_tokens", "latency_ms")
    CORRECTION_FIELD_NUMBER: _ClassVar[int]
    DISPOSITION_FIELD_NUMBER: _ClassVar[int]
    RATIONALE_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    REASONING_CONTENT_FIELD_NUMBER: _ClassVar[int]
    COMPLETION_TOKENS_FIELD_NUMBER: _ClassVar[int]
    LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    correction: str
    disposition: Disposition
    rationale: str
    model: str
    reasoning_content: str
    completion_tokens: int
    latency_ms: float
    def __init__(self, correction: _Optional[str] = ..., disposition: _Optional[_Union[Disposition, str]] = ..., rationale: _Optional[str] = ..., model: _Optional[str] = ..., reasoning_content: _Optional[str] = ..., completion_tokens: _Optional[int] = ..., latency_ms: _Optional[float] = ...) -> None: ...

class CompleteRequest(_message.Message):
    __slots__ = ("capability", "prompt", "system_prompt", "max_tokens", "temperature", "json_schema")
    CAPABILITY_FIELD_NUMBER: _ClassVar[int]
    PROMPT_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_PROMPT_FIELD_NUMBER: _ClassVar[int]
    MAX_TOKENS_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_FIELD_NUMBER: _ClassVar[int]
    JSON_SCHEMA_FIELD_NUMBER: _ClassVar[int]
    capability: str
    prompt: str
    system_prompt: str
    max_tokens: int
    temperature: float
    json_schema: str
    def __init__(self, capability: _Optional[str] = ..., prompt: _Optional[str] = ..., system_prompt: _Optional[str] = ..., max_tokens: _Optional[int] = ..., temperature: _Optional[float] = ..., json_schema: _Optional[str] = ...) -> None: ...

class CompleteResponse(_message.Message):
    __slots__ = ("text", "model", "prompt_tokens", "completion_tokens", "latency_ms", "reasoning_content", "finish_reason")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    PROMPT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    COMPLETION_TOKENS_FIELD_NUMBER: _ClassVar[int]
    LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    REASONING_CONTENT_FIELD_NUMBER: _ClassVar[int]
    FINISH_REASON_FIELD_NUMBER: _ClassVar[int]
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    reasoning_content: str
    finish_reason: str
    def __init__(self, text: _Optional[str] = ..., model: _Optional[str] = ..., prompt_tokens: _Optional[int] = ..., completion_tokens: _Optional[int] = ..., latency_ms: _Optional[float] = ..., reasoning_content: _Optional[str] = ..., finish_reason: _Optional[str] = ...) -> None: ...

class StatusRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Endpoint(_message.Message):
    __slots__ = ("capability", "model", "healthy", "gpu_ids", "detail")
    CAPABILITY_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    HEALTHY_FIELD_NUMBER: _ClassVar[int]
    GPU_IDS_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    capability: str
    model: str
    healthy: bool
    gpu_ids: _containers.RepeatedScalarFieldContainer[int]
    detail: str
    def __init__(self, capability: _Optional[str] = ..., model: _Optional[str] = ..., healthy: _Optional[bool] = ..., gpu_ids: _Optional[_Iterable[int]] = ..., detail: _Optional[str] = ...) -> None: ...

class StatusResponse(_message.Message):
    __slots__ = ("project", "endpoints", "total_gpus")
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    ENDPOINTS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_GPUS_FIELD_NUMBER: _ClassVar[int]
    project: str
    endpoints: _containers.RepeatedCompositeFieldContainer[Endpoint]
    total_gpus: int
    def __init__(self, project: _Optional[str] = ..., endpoints: _Optional[_Iterable[_Union[Endpoint, _Mapping]]] = ..., total_gpus: _Optional[int] = ...) -> None: ...

class YieldRequest(_message.Message):
    __slots__ = ("workload_id", "reason", "sentinel_id", "detail")
    WORKLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    SENTINEL_ID_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    workload_id: str
    reason: YieldReason
    sentinel_id: str
    detail: str
    def __init__(self, workload_id: _Optional[str] = ..., reason: _Optional[_Union[YieldReason, str]] = ..., sentinel_id: _Optional[str] = ..., detail: _Optional[str] = ...) -> None: ...

class YieldResponse(_message.Message):
    __slots__ = ("ok", "process_ended", "restore_started", "message")
    OK_FIELD_NUMBER: _ClassVar[int]
    PROCESS_ENDED_FIELD_NUMBER: _ClassVar[int]
    RESTORE_STARTED_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    process_ended: bool
    restore_started: bool
    message: str
    def __init__(self, ok: _Optional[bool] = ..., process_ended: _Optional[bool] = ..., restore_started: _Optional[bool] = ..., message: _Optional[str] = ...) -> None: ...
