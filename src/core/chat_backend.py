from typing import List, Optional, AsyncIterator

from src.core.database import Database, Message
from src.core.llm_engine import LLMEngine
from src.core.intent_router import IntentRouter


class ChatBackend:

    def __init__(self, db_path: str = "data/deskmate.db"):
        self.db = Database(db_path)
        self.llm = LLMEngine()
        self.router = IntentRouter()

    async def send_message(
        self,
        content: str,
        session_id: Optional[int] = None
    ) -> tuple[str, int]:
        if session_id is None:
            session_id = self.db.create_session()

        self.db.add_message(session_id, "user", content)

        history = self.db.get_history(session_id)

        reply = await self.router.process(content, self.llm, history, session_id)

        self.db.add_message(session_id, "assistant", reply)

        return reply, session_id

    def get_history(self, session_id: int, limit: int = 100) -> List[Message]:
        return self.db.get_history(session_id, limit)

    def create_session(self, title: Optional[str] = None) -> int:
        return self.db.create_session(title)

    def clear_history(self, session_id: int):
        self.db.clear_history(session_id)

    def get_recent_sessions(self, limit: int = 20) -> List[dict]:
        return self.db.get_recent_sessions(limit)

    def delete_session(self, session_id: int):
        self.db.delete_session(session_id)

    async def send_message_stream(self, content: str, session_id: Optional[int] = None) -> AsyncIterator[str]:
        """
        流式发送消息。

        Yield:
            每个流式 token 片段
        """
        if session_id is None:
            session_id = self.db.create_session()

        self.db.add_message(session_id, "user", content)

        history = self.db.get_history(session_id)

        reply = await self.router.process(content, self.llm, history, session_id)

        for chunk in _stream_text(reply):
            yield chunk

        self.db.add_message(session_id, "assistant", reply)


def _stream_text(text: str, chunk_size: int = 3) -> AsyncIterator[str]:
    """将文本拆分成小块，用于打字机效果。"""
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]
