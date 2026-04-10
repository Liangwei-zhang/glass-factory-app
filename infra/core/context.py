from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4


@dataclass(slots=True)
class RequestContext:
    request_id: str
    trace_id: str | None = None
    user_ip: str | None = None
    user_id: str | None = None


_request_context: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)


def create_request_context(trace_id: str | None = None, user_ip: str | None = None) -> RequestContext:
    return RequestContext(request_id=str(uuid4()), trace_id=trace_id, user_ip=user_ip)


def set_request_context(context: RequestContext) -> None:
    _request_context.set(context)


def get_request_context() -> RequestContext | None:
    return _request_context.get()


def clear_request_context() -> None:
    _request_context.set(None)
