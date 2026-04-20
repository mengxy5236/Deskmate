"""
数据库层 - SQLite 持久化
支持多会话管理和对话历史存储
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Message:
    """消息数据类"""
    id: int
    session_id: int
    role: str  # 'user' | 'assistant' | 'system'
    content: str
    intent: Optional[str] = None  # 识别的意图类型
    tool_result: Optional[str] = None  # 工具执行结果
    created_at: Optional[str] = None


class Database:
    """SQLite 数据库封装"""

    def __init__(self, db_path: str = "data/deskmate.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库和表结构"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    intent TEXT,
                    tool_result TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id);
                CREATE INDEX IF NOT EXISTS idx_messages_created
                    ON messages(created_at);
            """)
            conn.execute("PRAGMA foreign_keys = ON;")

    # ===== 会话管理 =====

    def create_session(self, title: str = None) -> int:
        """
        创建新会话

        Args:
            title: 会话标题，默认使用时间戳

        Returns:
            新创建的 session_id
        """
        if title is None:
            title = f"对话 {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO sessions (title) VALUES (?)",
                (title,)
            )
            return cursor.lastrowid

    def update_session_title(self, session_id: int, title: str):
        """更新会话标题"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (title, session_id)
            )

    def get_recent_sessions(self, limit: int = 20) -> List[Dict]:
        """
        获取最近会话列表

        Returns:
            [{"id": 1, "title": "对话1", "created_at": "...", "updated_at": "..."}, ...]
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT id, title, created_at, updated_at
                   FROM sessions
                   ORDER BY updated_at DESC
                   LIMIT ?""",
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_session(self, session_id: int):
        """删除会话及其所有消息（级联删除）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    # ===== 消息管理 =====

    def add_message(
        self,
        session_id: int,
        role: str,
        content: str,
        intent: str = None,
        tool_result: Any = None
    ) -> int:
        """
        添加消息到会话

        Args:
            session_id: 会话 ID
            role: 角色 ('user' | 'assistant' | 'system')
            content: 消息内容
            intent: 识别的意图类型（可选）
            tool_result: 工具执行结果（可选，会序列化为 JSON）

        Returns:
            新创建的消息 ID
        """
        tool_result_json = None
        if tool_result is not None:
            tool_result_json = json.dumps(tool_result, ensure_ascii=False)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO messages
                   (session_id, role, content, intent, tool_result)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, role, content, intent, tool_result_json)
            )
            # 更新会话的更新时间
            conn.execute(
                "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,)
            )
            return cursor.lastrowid

    def get_history(self, session_id: int, limit: int = 100) -> List[Message]:
        """
        获取会话历史

        Args:
            session_id: 会话 ID
            limit: 返回消息数量上限

        Returns:
            Message 对象列表，按时间正序
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT id, session_id, role, content, intent, tool_result, created_at
                   FROM messages
                   WHERE session_id = ?
                   ORDER BY created_at ASC
                   LIMIT ?""",
                (session_id, limit)
            ).fetchall()
            return [Message(**dict(row)) for row in rows]

    def clear_history(self, session_id: int):
        """清空会话消息（保留会话本身）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM messages WHERE session_id = ?",
                (session_id,)
            )
            conn.execute(
                "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,)
            )

    def get_message_count(self, session_id: int) -> int:
        """获取会话消息数量"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?",
                (session_id,)
            )
            return cursor.fetchone()[0]