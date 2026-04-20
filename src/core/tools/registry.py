"""
工具注册表
统一管理所有可用的工具函数
"""

from src.modules.weather import get_weather
from src.modules.news import get_news

# 工具注册表：名称 -> 异步函数
TOOL_REGISTRY = {
    "weather": get_weather,
    "news": get_news,
}

# 工具描述：用于 LLM 理解何时调用
TOOL_DESCRIPTIONS = {
    "weather": {
        "name": "weather",
        "description": "查询指定城市的天气信息。当用户询问天气、温度、气候、是否下雨等情况时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "要查询天气的城市名称，如'天津'、'北京'等"
                }
            },
            "required": ["city"]
        }
    },
    "news": {
        "name": "news",
        "description": "获取最新新闻资讯。当用户询问新闻、今日新闻、最新消息等情况时使用。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
}
