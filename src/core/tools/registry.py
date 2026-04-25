"""
工具注册表

统一管理所有可用的工具函数及其 OpenAI-compatible schema。
"""

from src.modules.weather import get_weather
from src.modules.news import get_news


TOOL_REGISTRY = {
    "weather": get_weather,
    "news": get_news,
}

# OpenAI tools schema 格式。
# type 固定为 "function"，function 内包含 name / description / parameters。
TOOL_DESCRIPTIONS = {
    "weather": {
        "name": "weather",
        "description": "查询指定城市的当前天气信息，包括温度、天气状况、体感温度和湿度。"
                       "当用户询问天气、气温、是否下雨/下雪、冷热程度时必须使用此工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "要查询天气的城市名称（中文），例如'北京'、'上海'、'天津'"
                }
            },
            "required": ["city"]
        }
    },
    "news": {
        "name": "news",
        "description": "获取最新的中文新闻头条资讯。当用户询问新闻、头条、最新消息、最近发生了什么时必须使用此工具。",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
}
