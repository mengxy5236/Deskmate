"""
意图路由
根据 LLM 识别的意图，路由到对应的工具函数
"""

import json
import re
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from src.core.tools.registry import TOOL_REGISTRY, TOOL_DESCRIPTIONS

if TYPE_CHECKING:
    from src.core.database import Message as DBMsg

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

def quick_match_intent(user_input: str) -> Optional[str]:
    """
    快速关键词匹配判断意图

    Args:
        user_input: 用户输入

    Returns:
        意图名称或 None
    """
    text = user_input.lower()

    for intent, keywords in INTENT_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                return intent

    return None

def is_direct_chat(user_input: str) -> bool:
    """
    判断是否为闲聊（直接回复，无需工具）

    Args:
        user_input: 用户输入

    Returns:
        True 表示闲聊，False 表示需要工具
    """
    text = user_input.lower()
    for keyword in CHAT_KEYWORDS:
        if keyword in text:
            return True
    return False

class IntentRouter:
    """根据识别到的意图调用对应工具"""

    def __init__(self):
        self.tools = TOOL_REGISTRY
        self.tool_descriptions = TOOL_DESCRIPTIONS

    def get_system_prompt(self) -> str:
        """生成系统提示词，让 LLM 知道有哪些工具可用"""
        tools_json = json.dumps(
            list(self.tool_descriptions.values()),
            ensure_ascii=False,
            indent=2
        )
        return f"""你是一个智能助手。当用户提问时，你需要判断是否需要调用工具来回答。

可用工具：
{tools_json}

判断规则：
- 如果用户询问天气相关问题（如"天气怎么样"、"今天热吗"、"会下雨吗"等），必须调用 weather 工具。
- 如果用户询问新闻相关问题（如"今天有什么新闻"、"最新消息"等），必须调用 news 工具。
- 如果是一般对话或闲聊，直接回答。

返回格式（JSON）：
{{"intent": "工具名称或null", "parameters": {{"参数名": "参数值"}}, "direct_reply": "直接回复内容（仅当不需要工具时）"}}

示例：
用户："北京今天天气如何？"
返回：{{"intent": "weather", "parameters": {{"city": "北京"}}, "direct_reply": null}}

用户："你好"
返回：{{"intent": null, "parameters": {{}}, "direct_reply": "你好！有什么我可以帮你的吗？"}}

用户："给我看看新闻"
返回：{{"intent": "news", "parameters": {{}}, "direct_reply": null}}"""

    async def route(self, intent_result: Dict[str, Any]) -> str:
        """
        根据意图结果路由到对应工具

        Args:
            intent_result: 包含 intent, parameters, direct_reply 的字典

        Returns:
            工具执行结果或直接回复内容
        """
        intent = intent_result.get("intent")
        parameters = intent_result.get("parameters", {})
        direct_reply = intent_result.get("direct_reply")

        # 如果是直接回复，不需要调用工具
        if direct_reply:
            return direct_reply

        # 如果没有识别到意图，返回默认回复
        if not intent:
            return "抱歉，我不太理解你的问题。请换个方式问我，或者问我天气、新闻相关的内容。"

        # 检查工具是否存在
        if intent not in self.tools:
            return f"抱歉，暂不支持 '{intent}' 功能。"

        try:
            # 调用对应的工具函数
            tool_func = self.tools[intent]
            result = await tool_func(**parameters)
            return result
        except Exception as e:
            import traceback, sys
            sys.stdout.reconfigure(encoding='utf-8')
            traceback.print_exc()
            return f"执行 {intent} 时出错：{str(e)}"

    @staticmethod
    def parse_llm_response(response_text: str) -> Dict[str, Any]:
        """
        解析 LLM 返回的 JSON 响应

        Args:
            response_text: LLM 返回的原始文本

        Returns:
            解析后的字典
        """
        # 先尝试直接解析
        try:
            return json.loads(response_text.strip())
        except json.JSONDecodeError:
            pass

        # 尝试提取花括号内的内容（支持嵌套 JSON）
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # 如果解析失败，返回错误标记
        return {
            "intent": None,
            "parameters": {},
            "direct_reply": response_text.strip()
        }

    async def process(
        self,
        user_input: str,
        llm_engine,
        history: Optional[List["DBMsg"]] = None
    ) -> str:
        """
        处理用户输入的完整流程

        Args:
            user_input: 用户输入的文本
            llm_engine: LLM 引擎实例
            history: 对话历史（用于上下文），来自 database 的 Message 对象

        Returns:
            最终回复文本
        """
        intent = quick_match_intent(user_input)
        if intent is None:
            if is_direct_chat(user_input):
                return "你好！有什么我可以帮你的吗？"

            llm_response = await llm_engine.ask_with_prompt(
                self.get_system_prompt(),
                user_input,
                history
            )
            intent_result = self.parse_llm_response(llm_response)
        else:
            intent_result = self._build_intent_from_keywords(intent, user_input)

        result = await self.route(intent_result)
        return result

    def _build_intent_from_keywords(self, intent: str, user_input: str) -> Dict[str, Any]:
        """
        根据关键词匹配结果构造 intent_result

        Args:
            intent: 意图名称
            user_input: 用户输入

        Returns:
            intent_result 字典
        """
        parameters = {}

        # 从用户输入中提取参数
        if intent == "weather":
            city = self._extract_city(user_input)
            parameters["city"] = city

        return {
            "intent": intent,
            "parameters": parameters,
            "direct_reply": None
        }

    def _extract_city(self, text: str) -> str:
        """
        从文本中提取城市名

        Args:
            text: 用户输入

        Returns:
            城市名，默认为 "天津"
        """
        # 常见城市列表
        cities = [
            "北京", "上海", "天津", "重庆", "广州", "深圳", "成都", "杭州",
            "武汉", "南京", "西安", "苏州", "长沙", "郑州", "青岛", "沈阳",
            "大连", "厦门", "宁波", "济南", "哈尔滨", "长春", "福州", "南昌",
            "合肥", "昆明", "贵阳", "南宁", "石家庄", "太原", "呼和浩特",
            "海口", "三亚", "兰州", "银川", "西宁", "乌鲁木齐", "拉萨",
            "香港", "澳门", "台北"
        ]

        text = text.lower()
        for city in cities:
            if city in text:
                return city

        # 尝试匹配 "X 天气" 模式
        match = re.search(r'([^\s]+)天气', text)
        if match:
            return match.group(1)

        return "天津"  # 默认城市
