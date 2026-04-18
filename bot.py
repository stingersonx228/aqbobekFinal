import telebot
import httpx
import asyncio
import logging
import os
from dotenv import load_dotenv

# Загружаем ключи
load_dotenv()

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("tg_bridge")

# Конфигурация
TG_TOKEN = os.getenv("TG_TOKEN", "8642572783:AAHNR5N9QU6gVpo_EcL2c5QmF0N1Kfos6ms")
BACKEND_URL = "http://127.0.0.1:8001/internal-webhook"

# Senior Note: Using Async TeleBot for better performance
from telebot.async_telebot import AsyncTeleBot
bot = AsyncTeleBot(TG_TOKEN)

@bot.message_handler(commands=['start', 'help'])
async def send_welcome(message):
    welcome_text = (
        "👋 **Aqbobek Lyceum AI**\n\n"
        "Я принимаю отчеты по всем службам:\n"
        "🍽️ Столовая\n"
        "🛠️ Тех. служба / Ремонт\n"
        "⚙️ IT-поддержка\n"
        "📦 Логистика / Снабжение\n"
        "📖 Замены учителей\n"
        "🚨 Экстренные вызовы\n\n"
        "Все данные сразу попадают на дашборд директора!"
    )
    await bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: True)
async def handle_all_messages(message):
    """Асинхронно пересылаем сообщения на бэкенд"""
    payload = {
        "from": f"tg_{message.from_user.id}",
        "body": message.text,
        "platform": "telegram",
        "user_name": message.from_user.first_name
    }
    
    try:
        logger.info(f"Forwarding TG message from {payload['user_name']}")
        async with httpx.AsyncClient() as client:
            response = await client.post(BACKEND_URL, json=payload, timeout=10.0)
            
            if response.status_code != 200:
                logger.error(f"Backend error: {response.status_code}")
                # Мы не спамим юзеру ошибками, бэкенд сам решит когда отвечать
                
    except Exception as e:
        logger.error(f"Failed to connect to backend: {e}")
        await bot.reply_to(message, "⚠️ Проблема со связью с основным сервером.")

async def main():
    logger.info("🚀 Telegram Async Bridge is starting...")
    await bot.infinity_polling()

if __name__ == "__main__":
    asyncio.run(main())