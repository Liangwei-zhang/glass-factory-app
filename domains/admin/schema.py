from __future__ import annotations

from pydantic import BaseModel


class RuntimeStatus(BaseModel):
    status: str
    message: str = ""
