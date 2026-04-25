import httpx
import os
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import List, Optional, Tuple

load_dotenv()

API_KEY = os.getenv("TIANAPI_KEY")
URL = "http://apis.tianapi.com/generalnews/index"


@dataclass
class NewsItem:
    index: int
    title: str
    source: str
    ctime: str
    description: str
    url: str


async def get_news(num: int = 8) -> Tuple[str, List[NewsItem]]:
    """
    获取新闻列表。

    Returns:
        (格式化文本, NewsItem列表)
    """
    if not API_KEY:
        return "新闻接口未配置，请先在 .env 中设置 TIANAPI_KEY（申请地址：https://www.tianapi.com/）", []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                URL,
                params={"key": API_KEY, "num": num}
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        return f"新闻接口返回错误: {e.response.status_code}", []
    except httpx.RequestError as e:
        return f"新闻接口请求失败: {e}", []

    if data.get("code") != 200:
        return f"新闻接口出错: {data.get('msg', '未知错误')} (code={data.get('code')})", []

    newslist = data.get("result", {}).get("newslist", [])
    if not newslist:
        return "暂无新闻", []

    items: List[NewsItem] = []
    lines = ["📰 今日热点新闻：\n"]
    for i, raw in enumerate(newslist[:num], 1):
        item = NewsItem(
            index=i,
            title=raw.get("title", "无标题"),
            source=raw.get("source", ""),
            ctime=raw.get("ctime", ""),
            description=raw.get("description", ""),
            url=raw.get("url", ""),
        )
        items.append(item)
        lines.append(f"{i}. {item.title}")
        if item.source:
            lines.append(f"   来源：{item.source}" + (f" | {item.ctime}" if item.ctime else ""))
        lines.append("")

    lines.append("回复数字编号（如 1、2、3...）可查看详情。")
    return "\n".join(lines), items


async def get_news_by_index(
    items: List[NewsItem], user_input: str
) -> Optional[str]:
    """
    根据用户输入的数字编号，从已有列表中返回详情。

    Args:
        items: 之前的新闻列表
        user_input: 用户输入（如 "8" 或 "  8  "）

    Returns:
        详情文本，或 None（输入不是有效编号）
    """
    text = user_input.strip()
    if not text.isdigit():
        return None

    idx = int(text)
    for item in items:
        if item.index == idx:
            parts = [f"📄 {item.title}"]
            if item.source:
                parts.append(f"来源：{item.source}" + (f" | {item.ctime}" if item.ctime else ""))
            if item.description:
                parts.append(f"\n摘要：{item.description}")
            if item.url:
                parts.append(f"\n🔗 原文链接：{item.url}")
            return "\n".join(parts)

    return None


if __name__ == "__main__":
    import asyncio

    async def main():
        text, items = await get_news(8)
        print(text)
        print("---")
        detail = await get_news_by_index(items, "1")
        if detail:
            print(detail)

    asyncio.run(main())
