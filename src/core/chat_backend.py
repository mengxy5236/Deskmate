from typing import List, Optional
from src.core.database import Database, Message
from src.core.llm_engine import LLMEngine
from src.core.intent_router import IntentRouter


class ChatBackend:
    """聊天后端"""

    def __init__(self, db_path: str = "data/deskmate.db"):
        """
        初始化聊天后端

        Args:
            db_path: 数据库文件路径
        """
        self.db = Database(db_path)
        self.llm = LLMEngine()
        self.router = IntentRouter()

    async def send_message(
        self,
        content: str,
        session_id: Optional[int] = None
    ) -> tuple[str, int]:
        """
        发送消息并获取回复

        Args:
            content: 用户输入
            session_id: 会话 ID（None 表示创建新会话）

        Returns:
            (assistant 回复内容, session_id)
        """
        # 1. 创建或获取会话
        if session_id is None:
            session_id = self.db.create_session()

        # 2. 保存用户消息
        self.db.add_message(session_id, "user", content)

        # 3. 获取对话历史用于上下文
        history = self.db.get_history(session_id)

        # 4. 意图路由处理（传入历史以便 LLM 理解上下文）
        reply = await self.router.process(content, self.llm, history)

        # 5. 保存助手回复
        self.db.add_message(session_id, "assistant", reply)

        return reply, session_id

    def get_history(self, session_id: int, limit: int = 100) -> List[Message]:
        """
        获取对话历史

        Args:
            session_id: 会话 ID
            limit: 返回消息数量上限

        Returns:
            Message 对象列表
        """
        return self.db.get_history(session_id, limit)

    def create_session(self, title: Optional[str] = None) -> int:
        """
        创建新会话

        Args:
            title: 会话标题

        Returns:
            session_id
        """
        return self.db.create_session(title)

    def clear_history(self, session_id: int):
        """
        清空会话历史

        Args:
            session_id: 会话 ID
        """
        self.db.clear_history(session_id)

    def get_recent_sessions(self, limit: int = 20) -> List[dict]:
        """
        获取最近会话列表

        Args:
            limit: 返回数量上限

        Returns:
            会话列表
        """
        return self.db.get_recent_sessions(limit)

    def delete_session(self, session_id: int):
        """
        删除会话

        Args:
            session_id: 会话 ID
        """
        self.db.delete_session(session_id)
