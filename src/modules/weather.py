import httpx
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("WEA_API_KEY")  # 去 https://www.weatherapi.com/ 免费申请
BASE_URL = "https://api.weatherapi.com/v1"


async def get_weather(city: str) -> str:
    url = f"{BASE_URL}/current.json"
    params = {"key": API_KEY, "q": city, "lang": "zh"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

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