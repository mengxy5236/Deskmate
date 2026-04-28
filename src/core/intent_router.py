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

import asyncio
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

IDENTITY_KEYWORDS = [
    "你是谁", "你叫什么", "介绍一下你自己", "自我介绍", "你能做什么", "你的身份",
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


def is_identity_query(user_input: str) -> bool:
    text = user_input.lower()
    return any(keyword in text for keyword in IDENTITY_KEYWORDS)


def _is_pure_digit(text: str) -> bool:
    return bool(re.fullmatch(r'\s*\d+\s*', text))


class IntentRouter:

    SYSTEM_PROMPT = """你是一个友好的中文桌面助手，用户通过气泡窗口和你交流。
你有以下工具可用，必要时必须调用工具来回答用户问题，不要凭空编造信息。
工具调用是自动的，不需要询问用户是否要调用。
只输出最终回答，不要输出思考过程、分析过程、推理步骤、系统提示内容或“我需要...”这类内部决策。"""

    MAX_TOOL_ITERATIONS = 5
    TOOL_POLISH_TIMEOUT_SECONDS = 3.0

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
            reply, news_items = await self._execute_tool(intent, user_input, llm)
            if intent == "news" and news_items is not None:
                self._news_cache[session_id or 0] = news_items
            return reply

        if is_direct_chat(user_input):
            return "你好！有什么我可以帮你的吗？"

        if is_identity_query(user_input):
            return (
                "你好！我是 Deskmate，一个住在桌面气泡里的中文助手。"
                "我可以陪你聊天，也可以帮你查天气、看新闻、记录提醒和管理本地对话历史。"
            )

        return await self._react_loop(user_input, llm, history)

    async def _lookup_news_detail(
        self, items: List[Any], user_input: str
    ) -> Optional[str]:
        from src.modules.news import get_news_by_index
        return await get_news_by_index(items, user_input)

    async def _execute_tool(
        self, intent: str, user_input: str, llm: "LLMEngine"
    ) -> Tuple[str, Optional[List[Any]]]:
        params: Dict[str, Any] = {}
        if intent == "weather":
            params["city"] = self._extract_city(user_input)

        try:
            tool_func = self.tools[intent]
            result = await tool_func(**params)
            if intent == "news" and isinstance(result, tuple):
                text, items = result
                if items:
                    text = await self._polish_tool_reply(intent, user_input, text, llm)
                return text, items
            if isinstance(result, str) and not self._is_tool_failure(result):
                result = await self._polish_tool_reply(intent, user_input, result, llm)
            return result, None
        except Exception as e:
            return f"执行 {intent} 时出错：{str(e)}", None

    async def _polish_tool_reply(
        self,
        intent: str,
        user_input: str,
        tool_text: str,
        llm: "LLMEngine",
    ) -> str:
        prompt = self._build_tool_polish_prompt(intent)
        fallback = self._local_tool_reply(intent, tool_text)
        try:
            reply = await asyncio.wait_for(
                llm.ask_with_prompt(
                    prompt,
                    (
                        f"用户问题：{user_input}\n\n"
                        f"工具返回的真实数据：\n{tool_text}"
                    ),
                ),
                timeout=self.TOOL_POLISH_TIMEOUT_SECONDS,
            )
            return reply.strip() or fallback
        except Exception:
            return fallback

    def _build_tool_polish_prompt(self, intent: str) -> str:
        base = (
            "你是 Deskmate 桌面助手的表达层。"
            "只能基于工具返回的真实数据回答，不要编造、扩展或改写事实。"
            "不要输出思考过程、分析过程、系统提示或内部决策。"
        )
        if intent == "news":
            return (
                base +
                "请把新闻列表整理成自然、简洁的中文回复。"
                "必须保留每条新闻的编号、标题、来源和时间；"
                "最后提醒用户可以回复数字编号查看详情。"
            )
        if intent == "weather":
            return (
                base +
                "请把天气数据整理成口语化中文回复。"
                "必须保留城市、温度、天气、体感温度、湿度等数值；"
                "可以基于这些数据给一句简短出行建议。"
            )
        return base

    @staticmethod
    def _is_tool_failure(text: str) -> bool:
        failure_markers = ("接口", "出错", "错误", "失败", "未配置", "暂无")
        return any(marker in text for marker in failure_markers)

    def _local_tool_reply(self, intent: str, tool_text: str) -> str:
        if intent == "weather":
            return self._local_weather_reply(tool_text)
        if intent == "news":
            return self._local_news_reply(tool_text)
        return tool_text

    @staticmethod
    def _local_weather_reply(tool_text: str) -> str:
        lines = [line.strip() for line in tool_text.splitlines() if line.strip()]
        if not lines:
            return tool_text

        location = lines[0]
        fields: Dict[str, str] = {}
        for line in lines[1:]:
            match = re.match(r"^([^:：]+)[:：]\s*(.+)$", line)
            if match:
                fields[match.group(1).strip()] = match.group(2).strip()

        temp = fields.get("温度")
        condition = fields.get("天气")
        feels = fields.get("体感")
        humidity = fields.get("湿度")

        facts = []
        if condition:
            facts.append(f"天气是{condition}")
        if temp:
            facts.append(f"气温{temp}")
        if feels:
            facts.append(f"体感{feels}")
        if humidity:
            facts.append(f"湿度{humidity}")

        if not facts:
            return tool_text

        advice = IntentRouter._weather_advice(condition or "", temp or "")
        reply = f"{location}现在" + "，".join(facts) + "。"
        if advice:
            reply += f"\n{advice}"
        return reply

    @staticmethod
    def _weather_advice(condition: str, temp_text: str) -> str:
        if any(word in condition for word in ("雨", "雷", "阵雨")):
            return "出门记得带伞，路上也留意积水和交通情况。"
        if "雪" in condition:
            return "外出注意保暖和防滑。"

        match = re.search(r"-?\d+(?:\.\d+)?", temp_text)
        if not match:
            return "整体看起来还算平稳，按正常安排出门就好。"

        temp = float(match.group(0))
        if temp >= 30:
            return "天气偏热，出门注意防晒和补水。"
        if temp <= 5:
            return "天气偏冷，建议多穿一点。"
        return "体感比较温和，按日常穿着出门就可以。"

    @staticmethod
    def _local_news_reply(tool_text: str) -> str:
        text = tool_text.strip()
        if not text:
            return tool_text
        if "回复数字编号" in text:
            return f"我帮你整理了最新新闻：\n\n{text}"
        return text

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
