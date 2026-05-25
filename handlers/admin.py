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
from database import (
    get_knowledge, save_knowledge, save_knowledge_sections,
    get_dialogs_for_export, create_logs_xlsx,
    get_all_knowledge_with_ids, delete_knowledge_by_id, delete_knowledge_by_topic,
    update_knowledge_embedding, get_knowledge_without_embeddings,
    get_knowledge_grouped, delete_knowledge_by_source, clear_knowledge_base,
)
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
    groups = get_knowledge_grouped()
    if not groups:
        await message.answer("📭 База знаний пуста.")
        return
    lines = [g["display"] for g in groups]
    total_sections = sum(len(g["ids"]) for g in groups)
    text = (
        f"<b>База знаний</b> ({len(groups)} документов, {total_sections} секций):\n\n"
        + "\n".join(lines)
        + "\n\n<i>Удалить: /forget название_документа или /forget ID\n"
        + "Очистить всё: /cleardb</i>"
    )
    if len(text) > 3800:
        for i in range(0, len(lines), 40):
            await message.answer("\n".join(lines[i:i+40]))
    else:
        await message.answer(text)


# ------------------------------------------------------------------
# /forget — удаление записи из БЗ
# ------------------------------------------------------------------

@router.message(Command("forget"))
async def cmd_forget(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    arg = message.text.replace("/forget", "").strip()
    if not arg:
        await message.answer("Использование:\n/forget 42 — удалить по ID\n/forget авиа — удалить все с 'авиа' в теме")
        return

    # Попытка удалить по числовому ID
    if arg.isdigit():
        ok = delete_knowledge_by_id(int(arg))
        if ok:
            from services.search import invalidate_index
            invalidate_index()
            await message.answer(f"✅ Запись #{arg} удалена.")
        else:
            await message.answer(f"❌ Запись #{arg} не найдена.")
    else:
        count = delete_knowledge_by_topic(arg)
        if count:
            from services.search import invalidate_index
            invalidate_index()
            await message.answer(f"✅ Удалено {count} записей с темой содержащей «{arg}».")
        else:
            await message.answer(f"❌ Записей с «{arg}» в теме не найдено.")


# ------------------------------------------------------------------
# /learn — режим обучения (добавление знаний)
# ------------------------------------------------------------------

@router.message(Command("learn"))
async def cmd_learn(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    raw = message.text.replace("/learn", "").strip()
    # Флаг --whole: сохранить без разбивки на секции
    whole = "--whole" in raw
    topic = raw.replace("--whole", "").strip()
    if not topic:
        await message.answer(
            "Использование:\n"
            "/learn <тема> — сохранить с разбивкой на секции\n"
            "/learn --whole <тема> — сохранить как единый документ (без разбивки)"
        )
        return
    LEARN_MODE[message.from_user.id] = {
        "topic": topic,
        "content": "",
        "questions": [],
        "waiting_for": "content",
        "whole": whole,  # флаг: не разбивать
    }
    mode_hint = " (без разбивки)" if whole else " (с разбивкой на секции)"
    await message.answer(
        f"📚 Режим обучения: {topic}{mode_hint}\nПришли текст или файл. /done — сохранить."
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

    from services.search import invalidate_index

    # Флаг --whole: сохранить без разбивки
    if mode.get("whole"):
        record_id = save_knowledge(
            mode["topic"], mode["content"], "",
            message.from_user.username or str(uid),
        )
        invalidate_index()
        size = len(mode["content"])
        await message.answer(
            f"✅ «{mode['topic']}» сохранено целиком ({size} символов).\n"
            f"ID записи: {record_id}"
        )
        return

    # Разбиваем документ на секции по заголовкам
    from utils.text import split_document_to_sections
    sections = split_document_to_sections(mode["content"], default_topic=mode["topic"])
    source_doc = mode["topic"]  # имя документа = тема из /learn

    if len(sections) > 1:
        count = save_knowledge_sections(
            sections, message.from_user.username or str(uid),
            source_doc=source_doc,
        )
        invalidate_index()
        await message.answer(
            f"✅ Документ «{source_doc}» сохранён ({count} секций)."
        )
    else:
        topic, content = sections[0]
        record_id = save_knowledge(
            topic, content, "",
            message.from_user.username or str(uid),
            source_doc=source_doc,
        )
        invalidate_index()
        await message.answer(f"✅ «{topic}» сохранено. ID: {record_id}")


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

@router.message(Command("cleardb"))
async def cmd_cleardb(message: Message):
    """Полная очистка базы знаний."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    arg = message.text.replace("/cleardb", "").strip()
    if arg != "confirm":
        await message.answer(
            "⚠️ Это удалит ВСЕ записи из базы знаний.\n"
            "Для подтверждения отправь: /cleardb confirm"
        )
        return
    from database import clear_knowledge_base
    from services.search import invalidate_index
    count = clear_knowledge_base()
    invalidate_index()
    await message.answer(f"✅ База знаний очищена. Удалено записей: {count}")


@router.message(Command("reindex"))
async def cmd_reindex(message: Message):
    """Сбрасывает TF-IDF индекс — он пересчитается при следующем запросе."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    from services.search import invalidate_index
    from database import get_all_knowledge_with_ids
    invalidate_index()
    count = len(get_all_knowledge_with_ids())
    await message.answer(f"✅ Индекс сброшен. При следующем запросе пересчитается по {count} записям.")


# ------------------------------------------------------------------
# /log — выгрузка логов
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
