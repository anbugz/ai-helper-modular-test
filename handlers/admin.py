"""
handlers/admin.py — админские команды.
Перенос из handlers_legacy.py: /brief, /topics, /learn, /done, /updatecodes, /unblock.
"""
from datetime import timedelta
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import Message

from bot_instance import bot
from config import ADMIN_ID, LEARN_MODE, PENDING_CODE_UPDATE, logger
from database import get_knowledge, save_knowledge, save_knowledge_sections, get_dialogs_for_export, create_logs_xlsx
from services.security import unblock_user
from services.currency import get_cbr_rates
from utils.telegram import parse_date_range, safe_send

router = Router()


# ------------------------------------------------------------------
# /brief — краткая справка по ВЭД
# ------------------------------------------------------------------

@router.message(Command("brief"))
async def cmd_brief(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    await message.answer(
        "<b>BRIEF</b>\n"
        "НДС: 22% базовая, 10% льготная.\n"
        "Сбор: шкала ПП РФ №1637. Радио: 73 860 ₽.\n"
        "Валюта: инвойс. Страховка: в ТС."
    )


# ------------------------------------------------------------------
# /topics — список тем базы знаний
# ------------------------------------------------------------------

@router.message(Command("topics"))
async def cmd_topics(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    topics = get_knowledge()
    if not topics:
        await message.answer("📭 Пусто.")
        return
    lines = [f"{i+1}. {t['topic']}" for i, t in enumerate(topics)]
    await message.answer("<b>Темы:</b>\n" + "\n".join(lines))


# ------------------------------------------------------------------
# /learn — режим обучения (добавление знаний)
# ------------------------------------------------------------------

@router.message(Command("learn"))
async def cmd_learn(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    topic = message.text.replace("/learn", "").strip()
    if not topic:
        await message.answer("Использование: /learn <тема>")
        return
    LEARN_MODE[message.from_user.id] = {
        "topic": topic,
        "content": "",
        "questions": [],
        "waiting_for": "content",
    }
    await message.answer(
        f"📚 Режим обучения: {topic}\nПришли текст или файл. /done — выйти."
    )


# ------------------------------------------------------------------
# /done — сохранение знаний
# ------------------------------------------------------------------

@router.message(Command("done"))
async def cmd_done(message: Message):
    uid = message.from_user.id
    if uid not in LEARN_MODE:
        await message.answer("Ты не в режиме обучения.")
        return
    mode = LEARN_MODE.pop(uid)
    if not mode["content"]:
        await message.answer("❌ Нет контента.")
        return
    
    # Разбиваем документ на секции по заголовкам
    from utils.text import split_document_to_sections
    sections = split_document_to_sections(mode["content"], default_topic=mode["topic"])
    
    if len(sections) > 1:
        count = save_knowledge_sections(sections, message.from_user.username or str(uid))
        topics_preview = "\n".join(f"  • {t[:60]}" for t, c in sections[:10])
        await message.answer(
            f"✅ Документ «{mode['topic']}» разбит на {count} секций:\n{topics_preview}"
        )
    else:
        save_knowledge(
            mode["topic"], mode["content"], "", message.from_user.username or str(uid)
        )
        await message.answer(f"✅ «{mode['topic']}» сохранено.")


# ------------------------------------------------------------------
# /updatecodes — обновление кодов ТН ВЭД
# ------------------------------------------------------------------

@router.message(Command("updatecodes"))
async def cmd_updatecodes(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    PENDING_CODE_UPDATE[message.from_user.id] = __import__('datetime').datetime.utcnow() + timedelta(hours=3)
    await message.answer("📥 Пришли .xlsx с кодами ТН ВЭД. Ожидание: 10 мин.")


# ------------------------------------------------------------------
# /unblock — разблокировка пользователя
# ------------------------------------------------------------------

@router.message(Command("unblock"))
async def cmd_unblock(message: Message):
    """Разблокировать пользователя: /unblock 123456789"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    args = message.text.replace("/unblock", "").strip()
    if not args.isdigit():
        await message.answer("Использование: /unblock <user_id>")
        return
    uid = int(args)
    if unblock_user(uid):
        await message.answer(f"✅ Пользователь <code>{uid}</code> разблокирован.")
    else:
        await message.answer(f"ℹ️ Пользователь <code>{uid}</code> не был заблокирован.")


# ------------------------------------------------------------------
# /log — экспорт логов (админ)
# ------------------------------------------------------------------

@router.message(Command("log"))
async def cmd_log(message: Message):
    """Экспорт логов: /log [дата_от [дата_до]]"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    
    # Парсим диапазон дат из текста
    df, dt = parse_date_range(message.text)
    logs = get_dialogs_for_export(df, dt)
    if not logs:
        await message.answer("📭 Пусто.")
        return
    xb = create_logs_xlsx(logs, "logs")
    fn = f"logs_{df or 'all'}_{dt or 'all'}.xlsx"
    await message.answer_document(
        document=types.BufferedInputFile(xb, filename=fn),
        caption=f"📊 {len(logs)} записей",
    )
