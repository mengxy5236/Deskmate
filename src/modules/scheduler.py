import asyncio
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

from src.modules.weather import get_weather
from src.modules.news import get_news


def sync_weather():
    """同步执行异步天气查询（APScheduler 需要同步函数）"""
    result = asyncio.run(get_weather("Tianjin"))
    print(f"[天气推送] {datetime.now()}:\n{result}")
    # 这里可以调用 plyer 发送桌面通知


def sync_news():
    """同步执行异步新闻查询"""
    result = asyncio.run(get_news())
    print(f"[新闻推送] {datetime.now()}:\n{result}")


def create_scheduler():
    """创建调度器"""
    # 1. 配置执行器（线程池）
    executors = {
        'default': ThreadPoolExecutor(10)
    }

    # 2. 创建调度器（后台运行，适合 GUI 应用）
    scheduler = BackgroundScheduler(
        executors=executors,
        jobstore_defaults={'coalesce': False, 'max_instances': 3}
    )

    # 4. 添加定时任务
    # 每天早上 8 点推送天气
    scheduler.add_job(
        sync_weather,
        'cron',
        hour=8, minute=0,
        id='daily_weather',
        replace_existing=True  # 任务存在时替换
    )

    # 每 8 小时推送新闻
    scheduler.add_job(
        sync_news,
        'interval',
        hours=8,
        id='hourly_news',
        replace_existing=True
    )

    # 5. 启动调度器
    scheduler.start()
    print("调度器已启动！")

    return scheduler


if __name__ == "__main__":
    scheduler = create_scheduler()

    # 保持程序运行
    try:
        while True:
            pass
    except KeyboardInterrupt:
        scheduler.shutdown()
        print("调度器已关闭")