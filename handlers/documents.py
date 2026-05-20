"""
handlers/documents.py — обработка загруженных файлов.
TODO: перенести handle_document из старого handlers.py
"""
from aiogram import types, F
from aiogram.types import Message
from bot_instance import dp
from config import ADMIN_ID, logger

@dp.message(F.document)
async def handle_document(message: Message):
    """
    Обработчик документов.
    Только ADMIN_ID может загружать файлы (rev34).
    """
    user_id = message.from_user.id
    
    if user_id != ADMIN_ID:
        await message.answer("⛔ Загрузка файлов только для администратора.")
        return
    
    doc = message.document
    logger.info(f"Admin {user_id} загрузил файл: {doc.file_name}")
    await message.answer(f"✅ Файл '{doc.file_name}' получен. Обработка...")
    # TODO: полная логика обработки .xlsx
