"""
handlers/voice.py — обработка голосовых сообщений.
TODO: перенести handle_voice из старого handlers.py
"""
from aiogram import types, F
from aiogram.types import Message
from bot_instance import dp
from services.stt import speech_to_text
from config import logger
import asyncio
import os

@dp.message(F.voice)
async def handle_voice(message: Message):
    """
    Обработчик голосовых сообщений.
    TODO: полный перенос из старого handlers.py
    """
    user_id = message.from_user.id
    logger.info(f"User {user_id}: голосовое сообщение")
    
    # Скачиваем файл
    voice = message.voice
    file = await message.bot.get_file(voice.file_id)
    ogg_path = f"/tmp/voice_{user_id}_{voice.file_id}.ogg"
    await message.bot.download_file(file.file_path, ogg_path)
    
    # Распознаём
    recognized = await asyncio.to_thread(speech_to_text, ogg_path)
    os.remove(ogg_path)
    
    if not recognized:
        await message.answer("❌ Не удалось распознать голосовое.")
        return
    
    await message.answer(f"🎤 Распознано: {recognized}")
    # TODO: передать в handle_text для обработки
