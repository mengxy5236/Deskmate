"""
意图路由模块
根据 LLM 识别的意图，路由到对应的工具函数
"""

import json
import re
from typing import Dict, Any
from src.core.tools.registry import TOOL_REGISTRY, TOOL_DESCRIPTIONS


class IntentRouter:
    """意图路由器：根据识别到的意图调用对应工具"""

    def __init__(self):
        self.tools = TOOL_REGISTRY
        self.tool_descriptions = TOOL_DESCRIPTIONS

    def get_system_prompt(self) -> str:
        """生成系统提示词，让 LLM 知道有哪些工具可用"""
        tools_json = json.dumps(
            list(self.tool_descriptions.values()),
            ensure_ascii=False
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
        # 尝试提取 JSON 部分
        json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # 如果解析失败，返回错误标记
        return {
            "intent": None,
            "parameters": {},
            "direct_reply": response_text
        }


async def process_user_input(user_input: str, llm_engine) -> str:
    """
    处理用户输入的完整流程

    Args:
        user_input: 用户输入的文本
        llm_engine: LLM 引擎实例

    Returns:
        最终回复文本
    """
    router = IntentRouter()

    # 1. 让 LLM 判断意图
    intent_response = await llm_engine.ask_with_prompt(
        router.get_system_prompt(),
        user_input
    )

    # 2. 解析 LLM 返回
    intent_result = IntentRouter.parse_llm_response(intent_response)

    # 3. 路由到对应工具或返回直接回复
    result = await router.route(intent_result)

    return result
