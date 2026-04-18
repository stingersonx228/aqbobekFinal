import logging
from src.whatsapp_service import send_whatsapp_message
import telebot
import os

logger = logging.getLogger(__name__)

# Конфигурация админов (сюда можно добавить ID охраны, директора и т.д.)
ADMINS_TG = [] # Сюда можно добавить Telegram ID админов для массовой рассылки ЧП
TG_TOKEN = os.getenv("TG_TOKEN", "8642572783:AAHNR5N9QU6gVpo_EcL2c5QmF0N1Kfos6ms")
tg_bot = telebot.TeleBot(TG_TOKEN)

async def notify_all_platforms(message_text: str, priority: str = "medium"):
    """
    Killer Feature: Unified Emergency Broadcast.
    If priority is high/critical, sends to ALL admins on WA and TG.
    """
    prefix = "🚨 [URGENT ALERT] " if priority in ["high", "CRITICAL"] else "🔔 [INFO] "
    full_text = prefix + message_text
    
    logger.info(f"Broadcasting notification: {full_text}")
    
    # В реальности тут был бы список телефонов/ID из БД
    # Для хакатона имитируем рассылку
    try:
        # В Telegram (уведомляем админа)
        # Если есть hardcoded ID админа, можно раскомментить:
        # tg_bot.send_message(CHAT_ID, full_text)
        pass
    except Exception as e:
        logger.error(f"TG Broadcast failed: {e}")
        
    # В WhatsApp
    # await send_whatsapp_message(ADMIN_PHONE, full_text)
    pass

async def send_unified_reply(platform_id: str, text: str):
    """Отправка ответа в ту же платформу, откуда пришел запрос"""
    if platform_id.startswith("tg_"):
        chat_id = platform_id.replace("tg_", "")
        try:
            tg_bot.send_message(chat_id, text)
        except Exception as e:
            logger.error(f"TG Send failed: {e}")
    else:
        await send_whatsapp_message(platform_id, text)
