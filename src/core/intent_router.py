"""
意图路由 & ReAct 循环执行器

架构：
  process() 是入口，先用关键词快速匹配，匹配不上才走 ReAct 循环。
  ReAct 循环：发消息给 LLM → LLM 决定是否调用工具 →
             执行工具 → 把结果塞回 messages → 循环 →
             LLM 生成自然语言回复 → 返回

新闻详情回查：
  用户输入纯数字（如"1"、"2"）时，从当前 session 的缓存中
  取出对应编号的新闻详情（摘要 + 原文链接）直接返回。
"""

import json
import re
from typing import Dict, Any, Optional, List, Tuple, TYPE_CHECKING

from src.core.tools.registry import TOOL_REGISTRY, TOOL_DESCRIPTIONS

if TYPE_CHECKING:
    from src.core.database import Message as DBMsg
    from src.core.llm_engine import LLMEngine


INTENT_KEYWORDS: Dict[str, List[str]] = {
    "weather": [
        "天气", "气候", "气温", "温度", "下雨", "下雪", "晴天", "阴天",
        "热", "冷", "湿度", "风", "PM2.5", "空气", "多少度"
    ],
    "news": [
        "新闻", "消息", "头条", "资讯", "最新", "今天有什么", "最近发生"
    ],
}

CHAT_KEYWORDS = [
    "你好", "嗨", "hi", "hello", "在吗", "在不在", "早上好", "晚上好",
]


def _is_whole_word_match(text: str, keyword: str) -> bool:
    pattern = r'(?:^|[^\u4e00-\u9fff\w])' + re.escape(keyword) + r'(?:$|[^\u4e00-\u9fff\w])'
    return bool(re.search(pattern, text))


def quick_match_intent(user_input: str) -> Optional[str]:
    text = user_input.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(_is_whole_word_match(text, kw) for kw in keywords):
            return intent
    return None


def is_direct_chat(user_input: str) -> bool:
    text = user_input.lower()
    return any(_is_whole_word_match(text, kw) for kw in CHAT_KEYWORDS)


def _is_pure_digit(text: str) -> bool:
    return bool(re.fullmatch(r'\s*\d+\s*', text))


class IntentRouter:

    SYSTEM_PROMPT = """你是一个友好的中文桌面助手，用户通过气泡窗口和你交流。
你有以下工具可用，必要时必须调用工具来回答用户问题，不要凭空编造信息。
工具调用是自动的，不需要询问用户是否要调用。"""

    MAX_TOOL_ITERATIONS = 5

    def __init__(self):
        self.tools = TOOL_REGISTRY
        self._tool_schemas = self._build_schemas()
        self._news_cache: Dict[int, List[Any]] = {}

    def _build_schemas(self) -> List[Dict[str, Any]]:
        schemas = []
        for name, desc in TOOL_DESCRIPTIONS.items():
            schemas.append({
                "type": "function",
                "function": {
                    "name": desc["name"],
                    "description": desc["description"],
                    "parameters": desc["parameters"],
                }
            })
        return schemas

    async def route(
        self,
        user_input: str,
        llm: "LLMEngine",
        history: Optional[List["DBMsg"]] = None,
        session_id: Optional[int] = None,
    ) -> str:
        if _is_pure_digit(user_input) and session_id is not None:
            cached = self._news_cache.get(session_id, [])
            if cached:
                detail = await self._lookup_news_detail(cached, user_input)
                if detail is not None:
                    return detail

        intent = quick_match_intent(user_input)

        if intent:
            reply, news_items = await self._execute_tool(intent, user_input)
            if intent == "news" and news_items is not None:
                self._news_cache[session_id or 0] = news_items
            return reply

        if is_direct_chat(user_input):
            return "你好！有什么我可以帮你的吗？"

        return await self._react_loop(user_input, llm, history)

    async def _lookup_news_detail(
        self, items: List[Any], user_input: str
    ) -> Optional[str]:
        from src.modules.news import get_news_by_index
        return await get_news_by_index(items, user_input)

    async def _execute_tool(
        self, intent: str, user_input: str
    ) -> Tuple[str, Optional[List[Any]]]:
        params: Dict[str, Any] = {}
        if intent == "weather":
            params["city"] = self._extract_city(user_input)

        try:
            tool_func = self.tools[intent]
            result = await tool_func(**params)
            if intent == "news" and isinstance(result, tuple):
                text, items = result
                return text, items
            return result, None
        except Exception as e:
            return f"执行 {intent} 时出错：{str(e)}", None

    async def _react_loop(
        self,
        user_input: str,
        llm: "LLMEngine",
        history: Optional[List["DBMsg"]],
    ) -> str:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.SYSTEM_PROMPT}
        ]

        if history:
            for msg in history[-10:]:
                messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": user_input})

        tool_iterations = 0

        while tool_iterations < self.MAX_TOOL_ITERATIONS:
            raw = await llm.ask_with_tools(messages, self._tool_schemas)

            tool_calls, text_reply = raw
            assistant_msg: Dict[str, Any] = {}

            if tool_calls:
                assistant_msg = {
                    "role": "assistant",
                    "content": text_reply or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            }
                        }
                        for tc in tool_calls
                    ]
                }
                messages.append(assistant_msg)

                for tc in tool_calls:
                    tool_result = await self._execute_single_tool(tc.name, tc.arguments)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    })

                tool_iterations += 1
                continue

            if text_reply is not None:
                return text_reply

            tool_iterations += 1

        return "抱歉，我处理你的问题时遇到了一些问题，请稍后再试。"

    async def _execute_single_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
    ) -> str:
        if name not in self.tools:
            return f"错误：未找到工具 '{name}'"

        try:
            tool_func = self.tools[name]
            result = await tool_func(**arguments)
            if isinstance(result, tuple):
                return result[0]
            return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return f"工具 '{name}' 执行出错：{str(e)}"

    def _extract_city(self, text: str) -> str:
        cities = [
            "北京", "上海", "天津", "重庆", "广州", "深圳", "成都", "杭州",
            "武汉", "南京", "西安", "苏州", "长沙", "郑州", "青岛", "沈阳",
            "大连", "厦门", "宁波", "济南", "哈尔滨", "长春", "福州", "南昌",
            "合肥", "昆明", "贵阳", "南宁", "石家庄", "太原", "呼和浩特",
            "海口", "三亚", "兰州", "银川", "西宁", "乌鲁木齐", "拉萨",
            "香港", "澳门", "台北",
        ]
        text_lower = text.lower()
        for city in cities:
            if city in text_lower:
                return city

        match = re.search(r'([^\s]+)天气', text_lower)
        if match:
            return match.group(1)
        return "天津"

    async def process(
        self,
        user_input: str,
        llm: "LLMEngine",
        history: Optional[List["DBMsg"]] = None,
        session_id: Optional[int] = None,
    ) -> str:
        return await self.route(user_input, llm, history, session_id)
