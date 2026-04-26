from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.core.chat_backend import ChatBackend
from src.core.database import Message


@dataclass
class SessionDeleteResult:
    current_session_id: Optional[int]
    current_history: list[Message]


class SessionService:
    """Owns current-session state and session-related use cases."""

    DEFAULT_TITLE = "\u6c14\u6ce1\u52a9\u624b"

    def __init__(self, backend: ChatBackend) -> None:
        self._backend = backend
        self._current_session_id: Optional[int] = None

    @property
    def current_session_id(self) -> Optional[int]:
        return self._current_session_id

    def ensure_session(self, title: str | None = None) -> int:
        if self._current_session_id is None:
            self._current_session_id = self._backend.create_session(title or self.DEFAULT_TITLE)
        return self._current_session_id

    def create_new_session(self, title: str | None = None) -> int:
        self._current_session_id = self._backend.create_session(title or self.DEFAULT_TITLE)
        return self._current_session_id

    def switch_session(self, session_id: int) -> list[Message]:
        self._current_session_id = session_id
        return self._backend.get_history(session_id)

    def preview_session(self, session_id: int) -> list[Message]:
        return self._backend.get_history(session_id)

    def get_current_history(self) -> list[Message]:
        if self._current_session_id is None:
            return []
        return self._backend.get_history(self._current_session_id)

    def get_recent_sessions(self, limit: int = 20) -> list[dict]:
        return self._backend.get_recent_sessions(limit)

    def add_message(self, role: str, content: str) -> int:
        session_id = self.ensure_session()
        return self._backend.db.add_message(session_id, role, content)

    def delete_session(self, session_id: int) -> SessionDeleteResult:
        self._backend.delete_session(session_id)

        if self._current_session_id != session_id:
            return SessionDeleteResult(self._current_session_id, self.get_current_history())

        sessions = self.get_recent_sessions()
        if sessions:
            self._current_session_id = sessions[0]["id"]
            return SessionDeleteResult(
                current_session_id=self._current_session_id,
                current_history=self._backend.get_history(self._current_session_id),
            )

        self._current_session_id = None
        return SessionDeleteResult(current_session_id=None, current_history=[])
