import httpx
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("WEA_API_KEY")  # 去 https://www.weatherapi.com/ 免费申请
BASE_URL = os.getenv("WEA_BASE_URL")

async def get_weather(city: str) -> str:
    if not BASE_URL or not API_KEY:
        return "天气接口配置不完整，请检查 .env 文件中的 WEA_API_KEY 和 WEA_BASE_URL"

    url = f"{BASE_URL}/current.json"
    params = {"key": API_KEY, "q": city, "lang": "zh"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        return f"天气接口返回错误: {e.response.status_code}"
    except httpx.RequestError as e:
        return f"天气接口请求失败: {e}"

    location = data["location"]
    current = data["current"]
    return (
        f"{location['name']} {location['country']}\n"
        f"温度: {current['temp_c']}°C\n"
        f"天气: {current['condition']['text']}\n"
        f"体感: {current['feelslike_c']}°C\n"
        f"湿度: {current['humidity']}%"
    )


if __name__ == "__main__":
    import asyncio
    async def main():
        print(await get_weather("Tianjin"))

    asyncio.run(main())