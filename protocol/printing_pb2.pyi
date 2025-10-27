from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class PrintRequest(_message.Message):
    __slots__ = ("client_id", "message_content", "lamport_timestamp", "request_number")
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_CONTENT_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    REQUEST_NUMBER_FIELD_NUMBER: _ClassVar[int]
    client_id: int
    message_content: str
    lamport_timestamp: int
    request_number: int
    def __init__(self, client_id: _Optional[int] = ..., message_content: _Optional[str] = ..., lamport_timestamp: _Optional[int] = ..., request_number: _Optional[int] = ...) -> None: ...

class PrintResponse(_message.Message):
    __slots__ = ("success", "confirmation_message", "lamport_timestamp")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    CONFIRMATION_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    success: bool
    confirmation_message: str
    lamport_timestamp: int
    def __init__(self, success: bool = ..., confirmation_message: _Optional[str] = ..., lamport_timestamp: _Optional[int] = ...) -> None: ...

class AccessRequest(_message.Message):
    __slots__ = ("client_id", "lamport_timestamp", "request_number")
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    REQUEST_NUMBER_FIELD_NUMBER: _ClassVar[int]
    client_id: int
    lamport_timestamp: int
    request_number: int
    def __init__(self, client_id: _Optional[int] = ..., lamport_timestamp: _Optional[int] = ..., request_number: _Optional[int] = ...) -> None: ...

class AccessResponse(_message.Message):
    __slots__ = ("access_granted", "lamport_timestamp")
    ACCESS_GRANTED_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    access_granted: bool
    lamport_timestamp: int
    def __init__(self, access_granted: bool = ..., lamport_timestamp: _Optional[int] = ...) -> None: ...

class AccessRelease(_message.Message):
    __slots__ = ("client_id", "lamport_timestamp", "request_number")
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    REQUEST_NUMBER_FIELD_NUMBER: _ClassVar[int]
    client_id: int
    lamport_timestamp: int
    request_number: int
    def __init__(self, client_id: _Optional[int] = ..., lamport_timestamp: _Optional[int] = ..., request_number: _Optional[int] = ...) -> None: ...
