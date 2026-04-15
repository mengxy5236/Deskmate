import httpx
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("NEW_API_KEY")  # 去 https://newsdata.io/ 申请
URL = os.getenv("NEW_URL")

async def get_news() -> str:
    if not URL or not API_KEY:
        return "新闻接口配置不完整，请检查 .env 文件中的 NEW_API_KEY 和 NEW_URL"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                URL,
                params={
                    "apikey": API_KEY,
                    "language": "zh",
                    "category": "top"
                }
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        return f"新闻接口返回错误: {e.response.status_code}"
    except httpx.RequestError as e:
        return f"新闻接口请求失败: {e}"

    results = data.get("results", [])
    if not results:
        return "暂无新闻"

    lines = ["📰 今日热点新闻：\n"]
    for i, item in enumerate(results[:8], 1):
        lines.append(f"{i}. {item.get('title', '无标题')}")
        if item.get("description"):
            desc = item["description"][:80].replace("\n", " ")
            lines.append(f"   {desc}...")
        lines.append("")

    return "\n".join(lines)

if __name__ == "__main__":
    import asyncio
    result = asyncio.run(get_news())
    print(result)