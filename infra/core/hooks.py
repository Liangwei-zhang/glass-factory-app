from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

AfterCommitHook = Callable[[AsyncSession], Coroutine[Any, Any, None]]
_HOOKS_ATTR = "_registered_after_commit_hooks"


def register_after_commit_hook(session: AsyncSession, hook: AfterCommitHook) -> None:
    hooks = getattr(session, _HOOKS_ATTR, None)
    if hooks is None:
        hooks = []
        setattr(session, _HOOKS_ATTR, hooks)
    hooks.append(hook)


def pop_after_commit_hooks(session: AsyncSession) -> list[AfterCommitHook]:
    hooks = getattr(session, _HOOKS_ATTR, None) or []
    setattr(session, _HOOKS_ATTR, [])
    return hooks


async def execute_after_commit_hooks(session: AsyncSession) -> None:
    for hook in pop_after_commit_hooks(session):
        try:
            await hook(session)
        except Exception:
            # Hooks are best-effort and should not fail the request path.
            continue
