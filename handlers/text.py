"""
handlers/text.py — обработка текстовых сообщений.
TODO: перенести handle_text из старого handlers.py
"""
from aiogram import types, F
from aiogram.types import Message
from bot_instance import dp, bot
from config import ADMIN_ID, logger
from services.security import full_security_scan, is_blocked, contains_pii, redact_pii
from services.tnved import search_tnved, is_radio_electronics
from services.ai import ask_deepseek
from database import save_message
import re

@dp.message(F.text)
async def handle_text(message: Message):
    """
    Основной обработчик текстовых сообщений.
    TODO: полный перенос из старого handlers.py
    """
    user_id = message.from_user.id
    user_text = message.text or ""
    
    if not user_text or user_text.startswith("/"):
        return
    
    # Security scan
    is_attack, reason = full_security_scan(user_text, user_id)
    if is_attack:
        if reason == "USER_BLOCKED":
            await message.answer("⛔ Ваш аккаунт временно заблокирован.")
            return
        await message.answer("⛔ Запрос отклонён по политике безопасности.")
        return
    
    # TODO: полная логика handle_text
    # Пока простой fallback
    response = await ask_deepseek(user_text)
    await message.answer(response)
