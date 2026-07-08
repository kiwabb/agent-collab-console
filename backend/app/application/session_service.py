from __future__ import annotations

from collections.abc import Awaitable
from inspect import isawaitable
from typing import Protocol
from uuid import uuid4

from app.domain.models import Session


class SessionStore(Protocol):
    def save_session(self, session: Session) -> Awaitable[None] | None: ...

    def load_session(self, session_id: str) -> Awaitable[Session | None] | Session | None: ...

    def list_sessions(self) -> Awaitable[list[dict[str, object]]] | list[dict[str, object]]: ...


async def _maybe_await(value: Awaitable[object] | object) -> object:
    if isawaitable(value):
        return await value
    return value


class SessionService:
    def __init__(self, store: SessionStore | None = None) -> None:
        self.sessions: dict[str, Session] = {}
        self._store = store

    async def _save(self, session: Session) -> None:
        if self._store:
            await _maybe_await(self._store.save_session(session))

    async def create_session(self, title: str) -> Session:
        session = Session(id=str(uuid4()), title=title)
        self.sessions[session.id] = session
        await self._save(session)
        return session

    async def get_session(self, session_id: str) -> Session:
        if self._store and session_id not in self.sessions:
            # Try loading from store
            loaded = await _maybe_await(self._store.load_session(session_id))
            if isinstance(loaded, Session):
                restored = loaded
                self.sessions[session_id] = restored
        return self.sessions[session_id]

    async def update_session(self, session: Session) -> None:
        """Update session in memory and persist."""
        self.sessions[session.id] = session
        await self._save(session)

    async def list_sessions(self) -> list[Session]:
        """Return all sessions, loading from store if needed."""
        if self._store:
            # Load session IDs from store and ensure they're cached
            summaries = await _maybe_await(self._store.list_sessions())
            session_summaries = summaries if isinstance(summaries, list) else []
            for summary in session_summaries:
                session_id = summary.get("id")
                if not isinstance(session_id, str) or session_id in self.sessions:
                    continue
                loaded = await _maybe_await(self._store.load_session(session_id))
                if isinstance(loaded, Session):
                    self.sessions[session_id] = loaded
        return list(self.sessions.values())
