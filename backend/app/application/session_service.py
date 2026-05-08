from uuid import uuid4

from app.domain.models import Session


class SessionService:
    def __init__(self, store=None):
        self.sessions: dict[str, Session] = {}
        self._store = store

    async def _save(self, session: Session):
        if self._store:
            await self._store.save_session(session)

    async def create_session(self, title: str) -> Session:
        session = Session(id=str(uuid4()), title=title)
        self.sessions[session.id] = session
        await self._save(session)
        return session

    async def get_session(self, session_id: str) -> Session:
        if self._store and session_id not in self.sessions:
            # Try loading from store
            restored = await self._store.load_session(session_id)
            if restored:
                self.sessions[session_id] = restored
        return self.sessions[session_id]

    async def update_session(self, session: Session):
        """Update session in memory and persist."""
        self.sessions[session.id] = session
        await self._save(session)

    async def list_sessions(self) -> list[Session]:
        """Return all sessions, loading from store if needed."""
        if self._store:
            # Load session IDs from store and ensure they're cached
            session_summaries = await self._store.list_sessions()
            for summary in session_summaries:
                if summary["id"] not in self.sessions:
                    restored = await self._store.load_session(summary["id"])
                    if restored:
                        self.sessions[summary["id"]] = restored
        return list(self.sessions.values())
