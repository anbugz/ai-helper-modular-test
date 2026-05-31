"""
handlers/doc_check.py — Проверка документов ВЭД.

Флоу:
1. Менеджер пишет «проверь инвойс» / «проверь контракт» или /check
2. Бот спрашивает тип (если не указан) и просит прислать файл
3. Менеджер отправляет PDF/фото/DOCX/XLSX
4. Текст извлекается через services/ocr.py
5. DeepSeek проверяет по чеклисту и возвращает отчёт
"""

import os
import tempfile
import asyncio
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command

from config import logger
from services.ai import ask_deepseek
from services.ocr import extract_text

router = Router()

# ─── Чеклисты по типам документов ────────────────────────────────────────────

CHECKLISTS = {
    "invoice": {
        "name": "Инвойс (Invoice)",
        "emoji": "🧾",
        "prompt": """Ты эксперт по ВЭД документам. Проверь инвойс и дай структурированный отчёт.

ПРОВЕРЯЙ:
1. Реквизиты продавца (название, адрес, контакты)
2. Реквизиты покупателя (название, адрес)
3. Номер и дата инвойса
4. Описание товара (наименование, характеристики)
5. Количество и единицы измерения
6. Цена за единицу и общая сумма
7. Валюта
8. Условия поставки (Incoterms: EXW, FOB, CIF и т.д.)
9. Страна происхождения товара
10. Банковские реквизиты для оплаты
11. Подписи и печати

ФОРМАТ ОТВЕТА:
✅ **Что в порядке:**
[список]

⚠️ **Требует внимания:**
[список с пояснениями]

❌ **Отсутствует / критично:**
[список]

📋 **Краткое резюме:**
[1-2 предложения — годен документ или нет]""",
    },
    "packing": {
        "name": "Упаковочный лист (Packing List)",
        "emoji": "📦",
        "prompt": """Ты эксперт по ВЭД документам. Проверь упаковочный лист и дай структурированный отчёт.

ПРОВЕРЯЙ:
1. Соответствие с инвойсом (если можно определить)
2. Номер и дата документа
3. Реквизиты отправителя и получателя
4. Наименование товара
5. Количество мест (коробки, паллеты)
6. Вес каждого места (брутто и нетто)
7. Габариты упаковки
8. Маркировка (номера мест, маркировка опасных грузов если есть)
9. Общий вес и объём
10. Подписи

ФОРМАТ ОТВЕТА:
✅ **Что в порядке:**
[список]

⚠️ **Требует внимания:**
[список с пояснениями]

❌ **Отсутствует / критично:**
[список]

📋 **Краткое резюме:**
[1-2 предложения]""",
    },
    "contract": {
        "name": "Контракт",
        "emoji": "📜",
        "prompt": """Ты эксперт по ВЭД контрактам. Проверь контракт на поставку товара и дай структурированный отчёт.

ПРОВЕРЯЙ:
1. Реквизиты сторон (полные данные продавца и покупателя)
2. Предмет договора (описание товара)
3. Цена и условия оплаты
4. Условия поставки (Incoterms)
5. Сроки поставки
6. Качество и упаковка товара
7. Документы для таможенного оформления
8. Форс-мажор
9. Применимое право и арбитраж
10. Подписи и печати сторон
11. Дата и номер контракта
12. Банковские реквизиты

ФОРМАТ ОТВЕТА:
✅ **Что в порядке:**
[список]

⚠️ **Требует внимания:**
[список с пояснениями]

❌ **Отсутствует / критично:**
[список]

📋 **Краткое резюме:**
[1-2 предложения — рекомендация по документу]""",
    },
    "msds": {
        "name": "MSDS / Паспорт безопасности",
        "emoji": "⚗️",
        "prompt": """Ты эксперт по документации опасных грузов. Проверь MSDS (паспорт безопасности вещества) и дай структурированный отчёт.

ПРОВЕРЯЙ:
1. Идентификация вещества (название, CAS номер)
2. Состав / информация о компонентах
3. Класс опасности (UN номер, класс груза)
4. Меры первой помощи
5. Меры пожаротушения
6. Хранение и транспортировка
7. Требования к упаковке и маркировке
8. Дата документа и актуальность
9. Данные производителя

ФОРМАТ ОТВЕТА:
✅ **Что в порядке:**
[список]

⚠️ **Требует внимания:**
[список с пояснениями]

❌ **Отсутствует / критично:**
[список]

📋 **Краткое резюме:**
[1-2 предложения]""",
    },
    "general": {
        "name": "Общая проверка",
        "emoji": "🔍",
        "prompt": """Ты эксперт по документам ВЭД. Проанализируй документ и дай структурированный отчёт.

Определи тип документа и проверь его на:
1. Полноту (все обязательные поля заполнены)
2. Корректность данных (нет явных ошибок, противоречий)
3. Соответствие стандартам ВЭД
4. Наличие подписей и реквизитов

ФОРМАТ ОТВЕТА:
📄 **Тип документа:** [определи что это]

✅ **Что в порядке:**
[список]

⚠️ **Требует внимания:**
[список с пояснениями]

❌ **Отсутствует / критично:**
[список]

📋 **Краткое резюме:**
[1-2 предложения]""",
    },
}

# Триггеры для определения типа из текста
DOC_TYPE_TRIGGERS = {
    "invoice":  ["инвойс", "invoice", "счёт-фактура", "счет-фактура", "счёт фактура"],
    "packing":  ["упаковочный", "packing list", "packing", "паккинг"],
    "contract": ["контракт", "договор поставки", "договор на поставку", "внешнеторговый договор"],
    "msds":     ["msds", "паспорт безопасности", "sds", "safety data"],
}

# Общий триггер входа в режим проверки
CHECK_TRIGGERS = [
    "проверь документ", "проверь файл", "проверь инвойс", "проверь контракт",
    "проверь упаковочный", "проверь msds", "проверить документ",
    "проверить инвойс", "проверить контракт", "анализ документа",
    "проверь доку", "чекни документ",
]

# Состояния: user_id → {'step': 'wait_file'|'wait_type', 'doc_type': str}
CHECK_STATE: dict = {}


def is_check_request(text: str) -> bool:
    t = text.lower()
    return any(tr in t for tr in CHECK_TRIGGERS)


def detect_doc_type(text: str) -> str | None:
    t = text.lower()
    for doc_type, triggers in DOC_TYPE_TRIGGERS.items():
        if any(tr in t for tr in triggers):
            return doc_type
    return None


def get_type_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"{v['emoji']} {v['name']}", callback_data=f"doccheck_{k}")]
        for k, v in CHECKLISTS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── Команда /check ────────────────────────────────────────────────────────────

@router.message(Command("check"))
async def cmd_check(message: Message):
    await start_check_flow(message, None)


async def start_check_flow(message: Message, doc_type: str | None):
    """Запускает флоу проверки документа."""
    user_id = message.from_user.id

    if doc_type:
        CHECK_STATE[user_id] = {"step": "wait_file", "doc_type": doc_type}
        info = CHECKLISTS[doc_type]
        await message.answer(
            f"{info['emoji']} <b>Проверка: {info['name']}</b>\n\n"
            "📎 Пришли файл — PDF, фото, DOCX или XLSX.\n"
            "Поддерживаются сканы и фотографии.",
            parse_mode="HTML"
        )
    else:
        CHECK_STATE[user_id] = {"step": "wait_type"}
        await message.answer(
            "🔍 <b>Проверка документа</b>\n\nВыбери тип документа:",
            parse_mode="HTML",
            reply_markup=get_type_keyboard()
        )


@router.callback_query(F.data.startswith("doccheck_"))
async def handle_type_selection(callback: CallbackQuery):
    user_id = callback.from_user.id
    doc_type = callback.data.replace("doccheck_", "")

    if doc_type not in CHECKLISTS:
        await callback.answer("Неизвестный тип")
        return

    CHECK_STATE[user_id] = {"step": "wait_file", "doc_type": doc_type}
    info = CHECKLISTS[doc_type]

    await callback.message.edit_text(
        f"{info['emoji']} <b>Проверка: {info['name']}</b>\n\n"
        "📎 Пришли файл — PDF, фото, DOCX или XLSX.\n"
        "Поддерживаются сканы и фотографии.",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(F.document | F.photo)
async def handle_check_file(message: Message):
    """Обрабатывает файл в режиме проверки документа."""
    user_id = message.from_user.id
    state = CHECK_STATE.get(user_id)
    if not state or state.get("step") != "wait_file":
        return  # не в режиме проверки — пропускаем

    doc_type = state.get("doc_type", "general")
    info = CHECKLISTS[doc_type]

    status = await message.answer(f"⏳ Извлекаю текст из файла...")
    tmp_path = None

    try:
        from bot_instance import bot

        if message.document:
            tg_doc = message.document
            file_obj = await bot.get_file(tg_doc.file_id)
            ext = os.path.splitext(tg_doc.file_name or "file")[1].lower() or ".pdf"
        else:
            tg_photo = message.photo[-1]
            file_obj = await bot.get_file(tg_photo.file_id)
            ext = ".jpg"

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp_path = tmp.name
            await bot.download_file(file_obj.file_path, destination=tmp_path)

        raw_text = await extract_text(tmp_path)

        if not raw_text or len(raw_text.strip()) < 30:
            await status.edit_text(
                "❌ Не удалось извлечь текст из файла.\n\n"
                "Попробуй:\n"
                "• Прислать файл в другом формате (PDF → DOCX)\n"
                "• Сфотографировать с лучшим освещением\n"
                "• Вставить текст напрямую"
            )
            CHECK_STATE.pop(user_id, None)
            return

        await status.edit_text(f"🧠 Анализирую {info['name']}...")

        messages = [
            {
                "role": "system",
                "content": "Ты эксперт по документам внешнеэкономической деятельности (ВЭД). Отвечай на русском языке."
            },
            {
                "role": "user",
                "content": f"{info['prompt']}\n\n---\nДОКУМЕНТ:\n{raw_text[:8000]}"
            }
        ]

        result = await ask_deepseek(messages)

        await status.delete()
        await message.answer(
            f"{info['emoji']} <b>Результат проверки: {info['name']}</b>\n\n{result}",
            parse_mode="HTML"
        )

        CHECK_STATE.pop(user_id, None)

    except Exception as e:
        logger.error(f"[DocCheck] error: {e}")
        await status.edit_text(f"❌ Ошибка при проверке: {str(e)[:150]}")
        CHECK_STATE.pop(user_id, None)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
