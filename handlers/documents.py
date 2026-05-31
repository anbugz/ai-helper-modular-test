"""
handlers/documents.py — обработка документов (.xlsx).
Перенос из handlers_legacy.py: handle_document.
"""
import re
from datetime import timedelta
from aiogram import Router, types, F
from aiogram.types import Message

from bot_instance import bot
from config import ADMIN_ID, LEARN_MODE, PENDING_CODE_UPDATE, logger
from database import save_custom_codes
from services.tnved import load_tnved_rows

router = Router()

# Импорт парсеров — с fallback, если parsers.py недоступен
try:
    from parsers import parse_xlsx, parse_txt, parse_docx, _extract_codes_from_rows
except ImportError:
    logger.warning("parsers.py не найден — парсинг .xlsx недоступен")
    parse_xlsx = parse_txt = parse_docx = _extract_codes_from_rows = None


@router.message(F.document)
async def handle_document(message: Message):
    """Обработка загружаемых документов. Только для администратора."""
    # Если пользователь в режиме создания договора или проверки документа — пропускаем
    from handlers.contracts import CONTRACT_STATE
    from handlers.doc_check import CHECK_STATE
    if message.from_user.id in CONTRACT_STATE:
        return
    if message.from_user.id in CHECK_STATE:
        return

    doc = message.document
    user_id = message.from_user.id
    file_name = (doc.file_name or "").lower()

    # === ЗАГРУЗКА ФАЙЛОВ — ТОЛЬКО АДМИН ===
    if user_id != ADMIN_ID:
        await message.answer("⛔ Загрузка файлов только для администратора.")
        return

    if not parse_xlsx:
        await message.answer("❌ Модуль парсеров не доступен.")
        return

    # === РЕЖИМ ОБУЧЕНИЯ ===
    if (
        user_id in LEARN_MODE
        and LEARN_MODE[user_id].get("waiting_for") == "content"
    ):
        if not any(file_name.endswith(ext) for ext in [".txt", ".docx", ".xlsx"]):
            await message.answer("Только .txt, .docx, .xlsx")
            return
        try:
            file = await bot.get_file(doc.file_id)
            bytes_io = await bot.download_file(file.file_path)
            if file_name.endswith(".txt"):
                text = parse_txt(bytes_io)
            elif file_name.endswith(".docx"):
                text = parse_docx(bytes_io)
            else:
                rows = parse_xlsx(bytes_io)
                text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
            if not text.strip():
                await message.answer("Файл пустой.")
                return
            LEARN_MODE[user_id]["content"] = text
            LEARN_MODE[user_id]["waiting_for"] = "questions"
            await message.answer("✅ Сохранено.")
        except Exception as e:
            logger.error(f"Ошибка обработки файла обучения: {e}")
            await message.answer(f"Ошибка: {e}")
        return

    # === ОБРАБОТКА .xlsx ===
    if not file_name.endswith(".xlsx"):
        await message.answer("Только .xlsx")
        return

    now = __import__('datetime').datetime.utcnow() + timedelta(hours=3)
    is_code_update = False
    if user_id in PENDING_CODE_UPDATE:
        pending_time = PENDING_CODE_UPDATE[user_id]
        # PENDING_CODE_UPDATE хранит время в MSK
        if (now - pending_time) < timedelta(minutes=10):
            is_code_update = True
        del PENDING_CODE_UPDATE[user_id]

    try:
        file = await bot.get_file(doc.file_id)
        bytes_io = await bot.download_file(file.file_path)
        data = parse_xlsx(bytes_io)
        logger.info(f"XLSX parsed: {len(data)} rows, first 3: {data[:3]}")
        if not data:
            await message.answer("Не прочитал.")
            return

        # Проверяем, есть ли в файле коды ТН ВЭД
        has_tnved = any(
            isinstance(r[0], str)
            and re.match(r"\d{10}", r[0].replace(" ", ""))
            for r in data
            if r
        )

        # Загрузка кодов ТН ВЭД
        if has_tnved and (is_code_update or user_id == ADMIN_ID):
            load_tnved_rows(data)
            await message.answer(
                f"📋 Загружено: {len(data)} кодов ТН ВЭД в базу данных."
            )
            return  # Выходим — ТН ВЭД загружены успешно

        # Обновление кодов радиоэлектроники (только если нет ТН ВЭД в файле)
        if is_code_update and _extract_codes_from_rows:
            codes = _extract_codes_from_rows(data)
            if not codes:
                await message.answer("❌ Коды не найдены.")
                return
            save_custom_codes(codes)
            await message.answer(
                f"✅ {len(codes)} кодов радиоэлектроники. Примеры: {', '.join(codes[:5])}"
            )
            return

        await message.answer("✅ Файл обработан.")
    except Exception as e:
        logger.error(f"Ошибка обработки документа: {e}")
        await message.answer(f"Ошибка: {e}")
