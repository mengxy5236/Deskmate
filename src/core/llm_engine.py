import json
import os
from dataclasses import dataclass, field
from typing import List, Optional, AsyncIterator, Dict, Any, TYPE_CHECKING

import httpx
from dotenv import load_dotenv

load_dotenv()

if TYPE_CHECKING:
    from src.core.database import Message as DBMsg


@dataclass
class Message:
    role: str
    content: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMEngine:
    api_key: str = os.getenv("LLM_API_KEY")
    model: str = os.getenv("LLM_MODEL")
    base_url: str = os.getenv("LLM_BASE_URL")
    reasoning_effort: Optional[str] = os.getenv("LLM_REASONING_EFFORT")
    extra_body: str = os.getenv("LLM_EXTRA_BODY", "")
    history: List[Message] = field(default_factory=list)

    def add_user_message(self, content: str) -> None:
        self.history.append(Message(role="user", content=content))

    def add_assistant_message(self, content: str) -> None:
        self.history.append(Message(role="assistant", content=content))

    def clear_history(self) -> None:
        self.history.clear()

    def _build_payload(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }

        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort

        if self.extra_body.strip():
            try:
                extra = json.loads(self.extra_body)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid LLM_EXTRA_BODY JSON: {exc}") from exc
            if not isinstance(extra, dict):
                raise ValueError("LLM_EXTRA_BODY must be a JSON object")
            payload.update(extra)

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        return payload

    async def _request(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        payload = self._build_payload(messages, tools=tools, stream=stream)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def ask(self, user_input: str) -> str:
        self.add_user_message(user_input)
        messages = [{"role": m.role, "content": m.content} for m in self.history]
        result = await self._request(messages, stream=False)
        reply = result["choices"][0]["message"]["content"]
        self.add_assistant_message(reply)
        return reply

    async def ask_with_prompt(
        self,
        system_prompt: str,
        user_input: str,
        history: Optional[List["DBMsg"]] = None,
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            for msg in history[-10:]:
                messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_input})

        result = await self._request(messages, stream=False)
        return result["choices"][0]["message"]["content"]

    async def ask_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        tool_call_id_to_name: Optional[Dict[str, str]] = None,
    ) -> tuple[Optional[List[ToolCall]], Optional[str]]:
        result = await self._request(messages, tools=tools, stream=False)

        msg = result["choices"][0]["message"]
        content = msg.get("content")
        raw_tool_calls = msg.get("tool_calls", [])
        finish_reason = result["choices"][0].get("finish_reason")

        if not raw_tool_calls:
            return None, content

        tool_calls = []
        for tc in raw_tool_calls:
            func = tc["function"]
            name = func["name"]
            if name is None and tc.get("id") and tool_call_id_to_name:
                name = tool_call_id_to_name.get(tc["id"])
            tool_calls.append(ToolCall(
                id=tc["id"],
                name=name or "",
                arguments=json.loads(func["arguments"]),
            ))
        return tool_calls, None

    async def stream(
        self,
        messages: List[dict],
    ) -> AsyncIterator[str]:
        """
        发起流式 LLM 请求。

        Yields:
            每个 content delta 片段
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=self._build_payload(messages, stream=True),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content_delta = delta.get("content", "")
                    if content_delta:
                        yield content_delta
