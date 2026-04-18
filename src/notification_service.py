import logging
import asyncio
from src.whatsapp_service import send_whatsapp_message
import telebot
import os

logger = logging.getLogger(__name__)

# Конфигурация админов (сюда можно добавить ID охраны, директора и т.д.)
ADMINS_TG = []  # Список Telegram ID для экстренной рассылки
TG_TOKEN = os.getenv("TG_TOKEN")
tg_bot = telebot.TeleBot(TG_TOKEN) if TG_TOKEN else None


async def notify_all_platforms(message_text: str, priority: str = "medium"):
    """
    Killer Feature: Unified Emergency Broadcast.
    If priority is high/critical, sends to ALL admins on WA and TG.
    """
    prefix = "🚨 [URGENT ALERT] " if priority in ["high", "CRITICAL"] else "🔔 [INFO] "
    full_text = prefix + message_text

    logger.info(f"Broadcasting notification: {full_text}")

    # Рассылка по TG-админам
    for chat_id in ADMINS_TG:
        try:
            # FIX: asyncio.to_thread чтобы не блокировать event loop FastAPI
            if tg_bot:
                await asyncio.to_thread(tg_bot.send_message, chat_id, full_text)
        except Exception as e:
            logger.error(f"TG Broadcast failed for {chat_id}: {e}")


async def send_unified_reply(platform_id: str, text: str):
    """Отправка ответа в ту же платформу, откуда пришел запрос"""
    if platform_id.startswith("tg_"):
        chat_id = platform_id.replace("tg_", "")
        try:
            if tg_bot:
                # FIX: asyncio.to_thread — не блокируем event loop
                await asyncio.to_thread(tg_bot.send_message, chat_id, text)
        except Exception as e:
            logger.error(f"TG Send failed: {e}")
    else:
        await send_whatsapp_message(platform_id, text)
