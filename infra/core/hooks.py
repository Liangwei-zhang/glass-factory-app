from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

AfterCommitHook = Callable[[AsyncSession], Coroutine[Any, Any, None]]
AfterRollbackHook = Callable[[AsyncSession], Coroutine[Any, Any, None]]
_HOOKS_ATTR = "_registered_after_commit_hooks"
_ROLLBACK_HOOKS_ATTR = "_registered_after_rollback_hooks"


def register_after_commit_hook(session: AsyncSession, hook: AfterCommitHook) -> None:
    hooks = getattr(session, _HOOKS_ATTR, None)
    if hooks is None:
        hooks = []
        setattr(session, _HOOKS_ATTR, hooks)
    hooks.append(hook)


def register_after_rollback_hook(session: AsyncSession, hook: AfterRollbackHook) -> None:
    hooks = getattr(session, _ROLLBACK_HOOKS_ATTR, None)
    if hooks is None:
        hooks = []
        setattr(session, _ROLLBACK_HOOKS_ATTR, hooks)
    hooks.append(hook)


def pop_after_commit_hooks(session: AsyncSession) -> list[AfterCommitHook]:
    hooks = getattr(session, _HOOKS_ATTR, None) or []
    setattr(session, _HOOKS_ATTR, [])
    return hooks


def pop_after_rollback_hooks(session: AsyncSession) -> list[AfterRollbackHook]:
    hooks = getattr(session, _ROLLBACK_HOOKS_ATTR, None) or []
    setattr(session, _ROLLBACK_HOOKS_ATTR, [])
    return hooks


async def execute_after_commit_hooks(session: AsyncSession) -> None:
    for hook in pop_after_commit_hooks(session):
        try:
            await hook(session)
        except Exception:
            # Hooks are best-effort and should not fail the request path.
            continue


async def execute_after_rollback_hooks(session: AsyncSession) -> None:
    for hook in pop_after_rollback_hooks(session):
        try:
            await hook(session)
        except Exception:
            continue
