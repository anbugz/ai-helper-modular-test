"""
handlers/voice.py — обработка голосовых сообщений.
Схема: скачивание → STT (Deepgram async) → обработка как текст.
"""
import os
from aiogram import Router, F
from aiogram.types import Message

from bot_instance import bot
from config import logger
from services.stt import speech_to_text
from utils.telegram import check_rate_limit, clear_rate_limit

router = Router()


@router.message(F.voice)
async def handle_voice(message: Message):
    """Голосовое сообщение → распознавание → обработка как текст."""
    user_id = message.from_user.id

    if not check_rate_limit(user_id):
        return

    # Скачиваем голосовое
    ogg_path = f"/tmp/voice_{user_id}_{message.message_id}.ogg"
    try:
        file = await bot.get_file(message.voice.file_id)
        await bot.download_file(file.file_path, ogg_path)
    except Exception as e:
        logger.error(f"Ошибка скачивания голосового: {e}")
        await message.answer("❌ Не удалось скачать голосовое сообщение")
        return

    processing_msg = await message.answer("🎤 Распознаю голосовое...")

    # Распознаём через async Deepgram (не блокирует event loop)
    recognized_text = await speech_to_text(ogg_path)

    # Удаляем временный файл
    try:
        os.remove(ogg_path)
    except Exception:
        pass

    if not recognized_text:
        await processing_msg.edit_text(
            "❌ Не удалось распознать голосовое сообщение. Попробуйте текстом."
        )
        return

    await processing_msg.edit_text(
        f"🎤 <i>Распознано:</i> <b>{recognized_text[:200]}</b>"
    )

    fake_message = message.model_copy(update={"text": recognized_text})
    logger.info(
        f"VOICE DEBUG: fake_message.text={fake_message.text!r}, "
        f"content_type={fake_message.content_type}"
    )

    # Сбрасываем rate limit перед передачей в handle_text
    clear_rate_limit(user_id)

    from handlers.text import handle_text
    await handle_text(fake_message)
