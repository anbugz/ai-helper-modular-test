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
    topics = get_all_knowledge_with_ids()
    if not topics:
        await message.answer("📭 Пусто.")
        return
    lines = [f"[{t['id']}] {t['topic'][:80]}" for t in topics]
    text = "<b>База знаний (ID — тема):</b>\n" + "\n".join(lines)
    text += "\n\n<i>Для удаления: /forget ID или /forget часть_темы</i>"
    # Разбиваем на части если длинный
    if len(text) > 3800:
        for i in range(0, len(lines), 50):
            chunk = "<b>Темы:</b>\n" + "\n".join(lines[i:i+50])
            await message.answer(chunk)
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
            await message.answer(f"✅ Запись #{arg} удалена.")
        else:
            await message.answer(f"❌ Запись #{arg} не найдена.")
    else:
        count = delete_knowledge_by_topic(arg)
        if count:
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

    from services.embeddings import get_embedding, embedding_to_blob

    # Флаг --whole: сохранить без разбивки
    if mode.get("whole"):
        await message.answer("💾 Сохраняю и вычисляю embedding...")
        # Для поиска используем тему + начало контента
        emb_text = f"{mode['topic']}\n{mode['content'][:2000]}"
        emb_vector = await get_embedding(emb_text)
        emb_blob = embedding_to_blob(emb_vector) if emb_vector else None
        record_id = save_knowledge(
            mode["topic"], mode["content"], "",
            message.from_user.username or str(uid),
            embedding=emb_blob,
        )
        size = len(mode["content"])
        emb_status = "✅ embedding" if emb_blob else "⚠️ без embedding"
        await message.answer(
            f"✅ «{mode['topic']}» сохранено целиком ({size} символов). {emb_status}\n"
            f"ID записи: {record_id}"
        )
        return

    # Разбиваем документ на секции по заголовкам
    from utils.text import split_document_to_sections
    sections = split_document_to_sections(mode["content"], default_topic=mode["topic"])

    if len(sections) > 1:
        await message.answer(f"💾 Сохраняю {len(sections)} секций, вычисляю embeddings...")
        # Вычисляем embedding для каждой секции
        embeddings = []
        for topic, content in sections:
            emb_text = f"{topic}\n{content[:2000]}"
            vec = await get_embedding(emb_text)
            embeddings.append(embedding_to_blob(vec) if vec else None)
        emb_count = sum(1 for e in embeddings if e)
        count = save_knowledge_sections(
            sections, message.from_user.username or str(uid), embeddings=embeddings
        )
        topics_preview = "\n".join(f"  • {t[:60]}" for t, c in sections[:10])
        await message.answer(
            f"✅ Документ «{mode['topic']}» разбит на {count} секций "
            f"({emb_count} с embedding):\n{topics_preview}"
        )
    else:
        await message.answer("💾 Сохраняю, вычисляю embedding...")
        topic, content = sections[0]
        emb_text = f"{topic}\n{content[:2000]}"
        vec = await get_embedding(emb_text)
        emb_blob = embedding_to_blob(vec) if vec else None
        record_id = save_knowledge(
            topic, content, "",
            message.from_user.username or str(uid),
            embedding=emb_blob,
        )
        emb_status = "✅ embedding" if emb_blob else "⚠️ без embedding"
        await message.answer(f"✅ «{topic}» сохранено. {emb_status} ID: {record_id}")


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

@router.message(Command("reindex"))
async def cmd_reindex(message: Message):
    """Вычисляет embeddings для записей БЗ у которых их нет."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return

    from services.embeddings import get_embedding, embedding_to_blob

    pending = get_knowledge_without_embeddings()
    if not pending:
        await message.answer("✅ Все записи уже имеют embeddings.")
        return

    await message.answer(f"🔄 Начинаю индексацию {len(pending)} записей...")
    done = 0
    failed = 0
    for rec in pending:
        emb_text = f"{rec['topic']}\n{rec['content'][:2000]}"
        vec = await get_embedding(emb_text)
        if vec:
            blob = embedding_to_blob(vec)
            update_knowledge_embedding(rec["id"], blob)
            done += 1
        else:
            failed += 1

    result = f"✅ Проиндексировано: {done}"
    if failed:
        result += f"\n⚠️ Не удалось: {failed} (нет ответа от API)"
    await message.answer(result)


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
