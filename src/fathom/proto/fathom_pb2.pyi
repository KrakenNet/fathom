from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ChangeType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CHANGE_TYPE_UNSPECIFIED: _ClassVar[ChangeType]
    ASSERT: _ClassVar[ChangeType]
    RETRACT: _ClassVar[ChangeType]
CHANGE_TYPE_UNSPECIFIED: ChangeType
ASSERT: ChangeType
RETRACT: ChangeType

class FactInput(_message.Message):
    __slots__ = ("template", "data_json")
    TEMPLATE_FIELD_NUMBER: _ClassVar[int]
    DATA_JSON_FIELD_NUMBER: _ClassVar[int]
    template: str
    data_json: str
    def __init__(self, template: _Optional[str] = ..., data_json: _Optional[str] = ...) -> None: ...

class EvaluateRequest(_message.Message):
    __slots__ = ("session_id", "ruleset", "facts")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    RULESET_FIELD_NUMBER: _ClassVar[int]
    FACTS_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    ruleset: str
    facts: _containers.RepeatedCompositeFieldContainer[FactInput]
    def __init__(self, session_id: _Optional[str] = ..., ruleset: _Optional[str] = ..., facts: _Optional[_Iterable[_Union[FactInput, _Mapping]]] = ...) -> None: ...

class EvaluateResponse(_message.Message):
    __slots__ = ("decision", "reason", "rule_trace", "module_trace", "duration_us")
    DECISION_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    RULE_TRACE_FIELD_NUMBER: _ClassVar[int]
    MODULE_TRACE_FIELD_NUMBER: _ClassVar[int]
    DURATION_US_FIELD_NUMBER: _ClassVar[int]
    decision: str
    reason: str
    rule_trace: _containers.RepeatedScalarFieldContainer[str]
    module_trace: _containers.RepeatedScalarFieldContainer[str]
    duration_us: int
    def __init__(self, decision: _Optional[str] = ..., reason: _Optional[str] = ..., rule_trace: _Optional[_Iterable[str]] = ..., module_trace: _Optional[_Iterable[str]] = ..., duration_us: _Optional[int] = ...) -> None: ...

class AssertFactRequest(_message.Message):
    __slots__ = ("session_id", "template", "data_json")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_FIELD_NUMBER: _ClassVar[int]
    DATA_JSON_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    template: str
    data_json: str
    def __init__(self, session_id: _Optional[str] = ..., template: _Optional[str] = ..., data_json: _Optional[str] = ...) -> None: ...

class AssertFactResponse(_message.Message):
    __slots__ = ("success",)
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    def __init__(self, success: bool = ...) -> None: ...

class QueryRequest(_message.Message):
    __slots__ = ("session_id", "template", "filter_json")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_FIELD_NUMBER: _ClassVar[int]
    FILTER_JSON_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    template: str
    filter_json: str
    def __init__(self, session_id: _Optional[str] = ..., template: _Optional[str] = ..., filter_json: _Optional[str] = ...) -> None: ...

class QueryResponse(_message.Message):
    __slots__ = ("facts_json",)
    FACTS_JSON_FIELD_NUMBER: _ClassVar[int]
    facts_json: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, facts_json: _Optional[_Iterable[str]] = ...) -> None: ...

class RetractRequest(_message.Message):
    __slots__ = ("session_id", "template", "filter_json")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_FIELD_NUMBER: _ClassVar[int]
    FILTER_JSON_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    template: str
    filter_json: str
    def __init__(self, session_id: _Optional[str] = ..., template: _Optional[str] = ..., filter_json: _Optional[str] = ...) -> None: ...

class RetractResponse(_message.Message):
    __slots__ = ("retracted_count",)
    RETRACTED_COUNT_FIELD_NUMBER: _ClassVar[int]
    retracted_count: int
    def __init__(self, retracted_count: _Optional[int] = ...) -> None: ...

class SubscribeRequest(_message.Message):
    __slots__ = ("session_id",)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    def __init__(self, session_id: _Optional[str] = ...) -> None: ...

class FactChange(_message.Message):
    __slots__ = ("change_type", "template", "data_json")
    CHANGE_TYPE_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_FIELD_NUMBER: _ClassVar[int]
    DATA_JSON_FIELD_NUMBER: _ClassVar[int]
    change_type: ChangeType
    template: str
    data_json: str
    def __init__(self, change_type: _Optional[_Union[ChangeType, str]] = ..., template: _Optional[str] = ..., data_json: _Optional[str] = ...) -> None: ...

class ReloadRequest(_message.Message):
    __slots__ = ("ruleset_path", "ruleset_yaml", "signature")
    RULESET_PATH_FIELD_NUMBER: _ClassVar[int]
    RULESET_YAML_FIELD_NUMBER: _ClassVar[int]
    SIGNATURE_FIELD_NUMBER: _ClassVar[int]
    ruleset_path: str
    ruleset_yaml: str
    signature: bytes
    def __init__(self, ruleset_path: _Optional[str] = ..., ruleset_yaml: _Optional[str] = ..., signature: _Optional[bytes] = ...) -> None: ...

class ReloadResponse(_message.Message):
    __slots__ = ("ruleset_hash_before", "ruleset_hash_after", "attestation_token")
    RULESET_HASH_BEFORE_FIELD_NUMBER: _ClassVar[int]
    RULESET_HASH_AFTER_FIELD_NUMBER: _ClassVar[int]
    ATTESTATION_TOKEN_FIELD_NUMBER: _ClassVar[int]
    ruleset_hash_before: str
    ruleset_hash_after: str
    attestation_token: str
    def __init__(self, ruleset_hash_before: _Optional[str] = ..., ruleset_hash_after: _Optional[str] = ..., attestation_token: _Optional[str] = ...) -> None: ...
