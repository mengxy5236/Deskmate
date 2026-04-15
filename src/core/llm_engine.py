import os
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

import httpx
from dotenv import load_dotenv

load_dotenv()

if TYPE_CHECKING:
    from src.core.database import Message as DBMsg


@dataclass
class Message:
    role: str  # "user" 或 "assistant"
    content: str


@dataclass
class LLMEngine:
    api_key: str = os.getenv("LLM_API_KEY")
    model: str = os.getenv("LLM_MODEL")
    base_url: str = os.getenv("LLM_BASE_URL")
    history: List[Message] = field(default_factory=list)

    def add_user_message(self, content: str) -> None:
        self.history.append(Message(role="user", content=content))

    def add_assistant_message(self, content: str) -> None:
        self.history.append(Message(role="assistant", content=content))

    async def ask(self, user_input: str) -> str:
        self.add_user_message(user_input)

        messages = [
            {"role": m.role, "content": m.content} for m in self.history
        ]

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "thinking": {"type": "disabled"}
                },
            )
            response.raise_for_status()
            result = response.json()
            reply = result["choices"][0]["message"]["content"]

        self.add_assistant_message(reply)
        return reply

    def clear_history(self) -> None:
        self.history.clear()

    async def ask_with_prompt(
        self,
        system_prompt: str,
        user_input: str,
        history: Optional[List["DBMsg"]] = None,
    ) -> str:
        """
        使用自定义系统提示词进行对话

        Args:
            system_prompt: 系统提示词
            user_input: 用户输入
            history: 对话历史（用于上下文），来自 database.Message 对象

        Returns:
            LLM 回复内容
        """
        messages = [{"role": "system", "content": system_prompt}]

        if history:
            for msg in history[-10:]:  # 最近 10 条
                messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": user_input})

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "thinking": {"type": "disabled"}
                },
            )
            response.raise_for_status()
            result = response.json()
            reply = result["choices"][0]["message"]["content"]

        return reply