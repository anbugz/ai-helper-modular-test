"""
handlers/amo.py — команды для работы с AmoCRM.

Триггеры:
- «найди сделку Ромашка» → поиск сделок
- «покажи реквизиты ООО Ромашка» → поиск контактов/компаний
- «напомни завтра в 10 позвонить клиенту» → создание задачи
- /overdue → просроченные задачи
- /stale → сделки без движения
"""
import re
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from config import logger, ADMIN_ID
from services.amocrm import (
    search_leads, format_lead,
    search_contacts, search_companies,
    create_task, add_note,
    get_overdue_tasks, get_stale_leads,
    get_users,
)

router = Router()

# ─── Триггеры ─────────────────────────────────────────────────────────────────

LEAD_TRIGGERS = [
    "найди сделку", "найти сделку", "поиск сделки", "покажи сделку",
    "сделка ", "по сделке", "статус сделки",
]
CONTACT_TRIGGERS = [
    "найди контакт", "покажи контакт", "реквизиты ", "данные клиента",
    "найди компанию", "покажи компанию", "карточка клиента",
    "найди клиента", "клиент ",
]
TASK_TRIGGERS = [
    "напомни", "создай задачу", "поставь задачу", "задача в crm",
    "задача в амо", "добавь задачу",
]


def is_amo_request(text: str) -> bool:
    t = text.lower()
    return (
        any(tr in t for tr in LEAD_TRIGGERS + CONTACT_TRIGGERS + TASK_TRIGGERS)
        or t.startswith("/overdue")
        or t.startswith("/stale")
    )


# ─── Поиск сделок ─────────────────────────────────────────────────────────────

async def handle_lead_search(message: Message, query: str):
    status = await message.answer("🔍 Ищу в AmoCRM...")
    try:
        leads = await search_leads(query, limit=5)
        if not leads:
            await status.edit_text(f"❌ Сделок по запросу «{query}» не найдено.")
            return

        text = f"📋 <b>Найдено сделок: {len(leads)}</b> по запросу «{query}»\n\n"
        for lead in leads:
            text += format_lead(lead) + "\n\n"
        await status.edit_text(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Lead search error: {e}")
        await status.edit_text(f"❌ Ошибка поиска: {str(e)[:100]}")


# ─── Поиск контактов/компаний ────────────────────────────────────────────────

async def handle_contact_search(message: Message, query: str):
    status = await message.answer("🔍 Ищу контакты в AmoCRM...")
    try:
        contacts = await search_contacts(query, limit=3)
        companies = await search_companies(query, limit=3)

        if not contacts and not companies:
            await status.edit_text(f"❌ Контактов/компаний по запросу «{query}» не найдено.")
            return

        text = f"👥 <b>Результаты поиска по «{query}»</b>\n\n"

        if companies:
            text += "🏢 <b>Компании:</b>\n"
            for c in companies:
                text += f"• <b>{c['name']}</b> (ID: {c['id']})\n"
                for fname, fval in list(c['fields'].items())[:5]:
                    text += f"  {fname}: {fval}\n"
            text += "\n"

        if contacts:
            text += "👤 <b>Контакты:</b>\n"
            for c in contacts:
                text += f"• <b>{c['name']}</b> (ID: {c['id']}, сделок: {c['leads_count']})\n"
                for fname, fval in list(c['fields'].items())[:5]:
                    text += f"  {fname}: {fval}\n"

        await status.edit_text(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Contact search error: {e}")
        await status.edit_text(f"❌ Ошибка поиска: {str(e)[:100]}")


# ─── Парсинг задачи ───────────────────────────────────────────────────────────

def parse_task_datetime(text: str) -> tuple[str, datetime]:
    """Парсит дату/время из текста задачи. Возвращает (текст_задачи, datetime)."""
    now = datetime.now()
    due = now + timedelta(days=1)
    due = due.replace(hour=10, minute=0, second=0, microsecond=0)

    # Убираем триггер
    for tr in TASK_TRIGGERS:
        text = re.sub(tr, '', text, flags=re.IGNORECASE).strip()

    # Ищем время: "в 15:30", "в 10", "в 9"
    time_match = re.search(r'в\s+(\d{1,2})(?::(\d{2}))?', text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        due = due.replace(hour=hour, minute=minute)
        text = text[:time_match.start()] + text[time_match.end():]

    # Ищем день: "завтра", "послезавтра", "через N дней", "в пн/вт/..."
    if 'послезавтра' in text.lower():
        due = now + timedelta(days=2)
        due = due.replace(hour=due.hour, minute=0, second=0, microsecond=0)
        text = re.sub(r'послезавтра', '', text, flags=re.IGNORECASE)
    elif 'завтра' in text.lower():
        due = now + timedelta(days=1)
        due = due.replace(hour=10, minute=0, second=0, microsecond=0)
        text = re.sub(r'завтра', '', text, flags=re.IGNORECASE)
    elif 'сегодня' in text.lower():
        due = now
        text = re.sub(r'сегодня', '', text, flags=re.IGNORECASE)

    days_match = re.search(r'через\s+(\d+)\s+дн', text)
    if days_match:
        due = now + timedelta(days=int(days_match.group(1)))
        text = text[:days_match.start()] + text[days_match.end():]

    # Применяем время если нашли
    if time_match:
        due = due.replace(hour=int(time_match.group(1)),
                         minute=int(time_match.group(2)) if time_match.group(2) else 0,
                         second=0, microsecond=0)

    text = re.sub(r'\s+', ' ', text).strip()
    text = text.strip(',. ')
    return text or "Задача из Telegram", due


async def handle_task_create(message: Message, raw_text: str):
    task_text, due_dt = parse_task_datetime(raw_text)
    status = await message.answer("⏳ Создаю задачу в AmoCRM...")
    try:
        from services.amocrm import get_amo_user_id
        responsible_id = get_amo_user_id(message.from_user.id)

        task = await create_task(
            text=task_text,
            due_dt=due_dt,
            responsible_user_id=responsible_id,
        )
        if task.get("id"):
            due_str = due_dt.strftime("%d.%m.%Y в %H:%M")
            await status.edit_text(
                f"✅ <b>Задача создана в AmoCRM</b>\n\n"
                f"📝 {task_text}\n"
                f"🕐 Срок: {due_str}\n"
                f"🆔 ID задачи: {task['id']}",
                parse_mode="HTML"
            )
        else:
            await status.edit_text("❌ Не удалось создать задачу. Проверь настройки AmoCRM.")
    except Exception as e:
        logger.error(f"Task create error: {e}")
        await status.edit_text(f"❌ Ошибка: {str(e)[:100]}")


# ─── Просроченные задачи ─────────────────────────────────────────────────────

@router.message(Command("overdue"))
async def cmd_overdue(message: Message):
    status = await message.answer("⏳ Загружаю просроченные задачи...")
    try:
        from services.amocrm import get_amo_user_id
        amo_user_id = get_amo_user_id(message.from_user.id)
        tasks = await get_overdue_tasks(responsible_user_id=amo_user_id)
        if not tasks:
            await status.edit_text("✅ Просроченных задач нет!")
            return

        text = f"⚠️ <b>Просроченные задачи: {len(tasks)}</b>\n\n"
        for t in tasks[:10]:
            entity = f"Сделка {t['entity_id']}" if t.get('entity_id') else "Без сделки"
            text += (
                f"• <b>{t['text'][:60]}</b>\n"
                f"  📅 Срок: {t['due']} | 👤 {t['responsible']} | 🔗 {entity}\n\n"
            )
        await status.edit_text(text, parse_mode="HTML")
    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {str(e)[:100]}")


# ─── Сделки без движения ──────────────────────────────────────────────────────

@router.message(Command("stale"))
async def cmd_stale(message: Message):
    status = await message.answer("⏳ Загружаю сделки без движения...")
    try:
        from services.amocrm import get_amo_user_id
        amo_user_id = get_amo_user_id(message.from_user.id)
        leads = await get_stale_leads(days=7, responsible_user_id=amo_user_id)
        if not leads:
            await status.edit_text("✅ Все сделки активны!")
            return

        text = f"😴 <b>Сделки без движения 7+ дней: {len(leads)}</b>\n\n"
        for lead in leads[:10]:
            text += (
                f"• <b>{lead['name']}</b> (ID: {lead['id']})\n"
                f"  📊 {lead['pipeline']} → {lead['status']}\n"
                f"  👤 {lead['responsible']} | ⏱ {lead['days_ago']} дней\n\n"
            )
        await status.edit_text(text, parse_mode="HTML")
    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {str(e)[:100]}")


# ─── Главная точка входа (вызывается из text.py) ─────────────────────────────

async def handle_amo_request(message: Message, user_text: str):
    """Обрабатывает запросы к AmoCRM из text.py."""
    text_lower = user_text.lower()

    # Поиск сделок
    if any(tr in text_lower for tr in LEAD_TRIGGERS):
        # Убираем триггер из запроса
        query = user_text
        for tr in LEAD_TRIGGERS:
            query = re.sub(tr, '', query, flags=re.IGNORECASE).strip()
        if not query:
            await message.answer("Укажи что искать. Например: «найди сделку Ромашка»")
            return
        await handle_lead_search(message, query)

    # Поиск контактов/компаний
    elif any(tr in text_lower for tr in CONTACT_TRIGGERS):
        query = user_text
        for tr in CONTACT_TRIGGERS:
            query = re.sub(tr, '', query, flags=re.IGNORECASE).strip()
        if not query:
            await message.answer("Укажи что искать. Например: «реквизиты ООО Ромашка»")
            return
        await handle_contact_search(message, query)

    # Создание задачи
    elif any(tr in text_lower for tr in TASK_TRIGGERS):
        await handle_task_create(message, user_text)

    else:
        await message.answer("Не понял запрос к CRM. Попробуй: «найди сделку», «реквизиты клиента», «напомни завтра в 10»")
