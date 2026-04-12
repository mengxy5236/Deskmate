import os
from dataclasses import dataclass, field
from typing import List

import httpx
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Message:
    role: str # "user" 或 "assistant"
    content: str

@dataclass
class LLMEngine:
    api_key: str = os.getenv("LLM_API_KEY")
    model: str = "/mnt/PublicStorage/lym/Qwen3.5-27B-GPTQ-Int4"
    base_url: str = "http://172.28.9.59:11234/v1"
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
                json={"model": self.model, "messages": messages},
            )
            response.raise_for_status()
            result = response.json()
            reply = result["choices"][0]["message"]["content"]

        self.add_assistant_message(reply)
        return reply

    def clear_history(self) -> None:
        self.history.clear()