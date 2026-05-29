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
import asyncio
from datetime import datetime, timedelta, timezone as _tz
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from config import logger, ADMIN_ID
from services.amo_leads import parse_deal_number, is_deal_number_request, format_lead_card
from services.amocrm import (
    search_leads_by_number,
    search_leads, format_lead,
    search_contacts, search_companies,
    create_task, add_note,
    get_overdue_tasks, get_stale_leads,
    get_users, get_lead_tasks,
)

router = Router()

# ─── Триггеры ─────────────────────────────────────────────────────────────────

LEAD_TRIGGERS = [
    "найди сделку", "найти сделку", "поиск сделки", "покажи сделку",
    "сделка ", "по сделке", "статус сделки",
    "найди поделку", "что у нас с поделкой", "что по сделке",
    "поделка ", "по поделке", "что со сделкой", "что с поделкой",
    "найди закрытую", "найди реализованную",
]
CONTACT_TRIGGERS = [
    "найди контакт", "покажи контакт", "реквизиты ", "данные клиента",
    "найди компанию", "покажи компанию", "карточка клиента",
    "найди клиента", "клиент ",
]
TASK_TRIGGERS = [
    "напомни", "напомнить", "напоминание", "напомню", "напомнишь",
    "создай задачу", "создать задачу", "сделай задачу",
    "поставь задачу", "поставить задачу", "поставь задание",
    "задача в crm", "задача в амо", "добавь задачу",
    "запиши задачу", "задачу по", "задачу на",
    "поставь задач",  # поставь задачу / поставь задание
    "задач перезвон", "задач позвон", "задач провер",
    "сделай задач", "создай напоминание", "поставь напоминание",
    "добавь напоминание", "нужно позвонить", "надо позвонить",
    "перезвонить через", "позвонить через",
]

NOTE_TRIGGERS = [
    "добавь примечание", "добавить примечание", "запиши примечание",
    "примечание по", "примечание к", "добавь заметку", "запиши заметку",
    "заметка по", "прокомментируй сделку", "добавь комментарий",
]

CREATE_TRIGGERS = [
    "создай сделку", "создать сделку", "новая сделка", "новая заявка",
    "добавь сделку", "добавить сделку", "заведи сделку", "завести сделку",
    "создай заявку", "создать заявку", "добавь заявку",
]

MYTASKS_TRIGGERS = [
    "мои задачи crm", "мои задачи црм", "задачи crm", "задачи црм",
    "задачи amocrm", "задачи амо", "amocrm задачи", "амо задачи",
    "задачи из crm", "задачи из црм", "покажи задачи crm",
    "мои дела crm", "мои дела црм", "/tasks", "/mytasks",
]

CONTACT_SEARCH_TRIGGERS = [
    "найди контакт", "найти контакт", "поиск контакта", "контакт ",
    "найди клиента", "найти клиента", "реквизиты контакта",
    "телефон клиента", "email клиента", "почта клиента",
]

# Дополнительная проверка — глагол + "задачу" в любом порядке
def _has_task_intent(text: str) -> bool:
    t = text.lower()
    if any(tr in t for tr in TASK_TRIGGERS):
        return True
    # "поставь ... задачу", "создай ... задачу" — глагол и слово задачу в тексте
    task_verbs = ("поставь", "поставить", "создай", "создать", "добавь", "запиши", "поставь")
    has_verb = any(v in t for v in task_verbs)
    has_noun = "задач" in t
    return has_verb and has_noun


def is_amo_request(text: str) -> bool:
    if text.startswith("/"):
        return False
    t = text.lower()
    if is_deal_number_request(text):
        return True
    if _has_task_intent(text):
        return True
    if any(tr in t for tr in NOTE_TRIGGERS):
        return True
    if any(tr in t for tr in CREATE_TRIGGERS):
        return True
    if any(tr in t for tr in MYTASKS_TRIGGERS):
        return True
    if any(tr in t for tr in CONTACT_SEARCH_TRIGGERS):
        return True
    return any(tr in t for tr in LEAD_TRIGGERS + CONTACT_TRIGGERS)


# ─── Поиск сделок ─────────────────────────────────────────────────────────────


async def handle_mytasks(message: Message):
    """Показывает все незакрытые задачи пользователя."""
    from services.amocrm import get_amo_user_id, _async_request
    from datetime import datetime, timedelta

    responsible_id = get_amo_user_id(message.from_user.id)
    params = {"filter[is_completed]": 0, "limit": 50}
    if responsible_id:
        params["filter[responsible_user_id][]"] = responsible_id

    resp = await _async_request("GET", "/tasks", params=params)
    tasks = resp.get("_embedded", {}).get("tasks", [])

    if not tasks:
        await message.answer("✅ Нет открытых задач!")
        return

    now = datetime.now()
    today_end = now.replace(hour=23, minute=59, second=59)
    tomorrow_end = today_end + timedelta(days=1)

    # Загружаем названия сделок
    lead_cache = {}
    for t in tasks:
        eid = t.get("entity_id")
        if eid and t.get("entity_type") == "leads" and eid not in lead_cache:
            lr = await _async_request("GET", f"/leads/{eid}")
            lead_cache[eid] = lr.get("name", "")

    overdue, today_tasks, tomorrow_tasks, later_tasks = [], [], [], []
    for t in tasks:
        due_ts = t.get("complete_till", 0)
        due_dt = datetime.fromtimestamp(due_ts) if due_ts else None
        eid = t.get("entity_id")
        item = {
            "text": t.get("text", "—"),
            "due": due_dt.strftime("%d.%m %H:%M") if due_dt else "—",
            "due_dt": due_dt,
            "lead": lead_cache.get(eid, "") if eid else "",
            "lead_id": eid,
        }
        if not due_dt:
            later_tasks.append(item)
        elif due_dt < now:
            overdue.append(item)
        elif due_dt <= today_end:
            today_tasks.append(item)
        elif due_dt <= tomorrow_end:
            tomorrow_tasks.append(item)
        else:
            later_tasks.append(item)

    def fmt(items, amo_domain=""):
        from collections import defaultdict
        grouped = defaultdict(list)
        order = []
        for t in items[:15]:
            key = (t["lead_id"], t["lead"] or "⚪ Без сделки")
            if key not in order:
                order.append(key)
            grouped[key].append(t)
        lines = []
        for (lead_id, lead_name) in order:
            if lead_id and lead_name != "⚪ Без сделки":
                url = f"https://{amo_domain}/leads/detail/{lead_id}"
                lines.append(f"\n🔗 <a href=\'{url}\'><b>{lead_name[:60]}</b></a>")
            else:
                lines.append(f"\n⚪ Без сделки")
            for t in grouped[(lead_id, lead_name)]:
                lines.append(f"  • {t['text'][:70]}\n    🕐 {t['due']}")
        return "\n".join(lines).strip()

    import os as _os
    _domain = _os.getenv("AMO_DOMAIN", "westasia.amocrm.ru")

    parts = []
    if overdue:
        parts.append(f"🔴 <b>Просроченные: {len(overdue)}</b>\n{fmt(overdue, _domain)}")
    if today_tasks:
        parts.append(f"🟡 <b>Сегодня: {len(today_tasks)}</b>\n{fmt(today_tasks, _domain)}")
    if tomorrow_tasks:
        parts.append(f"🔵 <b>Завтра: {len(tomorrow_tasks)}</b>\n{fmt(tomorrow_tasks, _domain)}")
    if later_tasks:
        parts.append(f"⚪ <b>Позже: {len(later_tasks)}</b>\n{fmt(later_tasks, _domain)}")

    await message.answer(
        f"📋 <b>Твои задачи ({len(tasks)}):</b>\n\n" + "\n\n".join(parts),
        parse_mode="HTML"
    )


async def handle_contact_search_full(message: Message, raw_text: str):
    """Ищет контакт по имени/телефону/email и показывает его сделки."""
    from services.amocrm import _async_request, get_pipelines, get_users

    query = raw_text
    for tr in CONTACT_SEARCH_TRIGGERS:
        query = re.sub(tr, "", query, flags=re.IGNORECASE).strip()
    query = query.strip(" :,-")

    if not query:
        await message.answer("Укажи имя или телефон. Пример: «найди контакт Антон Костюк»")
        return

    await message.answer(f"🔍 Ищу контакт: {query}...")
    resp = await _async_request("GET", "/contacts", params={
        "query": query, "limit": 3, "with": "leads,custom_fields",
    })
    contacts = resp.get("_embedded", {}).get("contacts", [])

    if not contacts:
        await message.answer(f"❌ Контакт <b>{query}</b> не найден.", parse_mode="HTML")
        return

    pipelines = await get_pipelines()

    for c in contacts:
        lines = [f"👤 <b>{c.get('name', '—')}</b>\n"]
        for f in c.get("custom_fields_values", []) or []:
            fid = f.get("field_id")
            vals = [v.get("value", "") for v in f.get("values", [])]
            val_str = ", ".join(filter(None, vals))
            if fid == 578354:
                lines.append(f"📞 {val_str}")
            elif fid == 578356:
                lines.append(f"📧 {val_str}")
        lead_ids = [l["id"] for l in c.get("_embedded", {}).get("leads", [])]
        if lead_ids:
            lines.append(f"\n📋 <b>Сделки ({len(lead_ids)}):</b>")
            for lid in lead_ids[:5]:
                lr = await _async_request("GET", f"/leads/{lid}")
                if lr.get("id"):
                    pipeline_id = lr.get("pipeline_id", 0)
                    status_id = lr.get("status_id", 0)
                    pipeline = pipelines.get(pipeline_id, {})
                    status = pipeline.get("statuses", {}).get(status_id, "—")
                    lines.append(f"  • <b>{lr.get('name','—')}</b> — {pipeline.get('name','—')} → {status}")
        await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("tasks"))
async def cmd_tasks(message: Message):
    await handle_mytasks(message)

async def handle_deal_number_search(message: Message, deal: dict):
    """Поиск сделки по номеру (64К, 73М и т.д.)."""
    await message.answer(f"🔍 Ищу сделку {deal['full']}...")
    try:
        leads = await search_leads_by_number(deal['search_query'])
        if not leads:
            await message.answer(
                f"❌ Активных сделок с номером <b>{deal['full']}</b> не найдено.\n"
                f"Если нужно найти закрытую — напиши «найди закрытую {deal['full']}»",
                parse_mode="HTML"
            )
            return

        from services.amocrm import get_pipelines, get_users, _async_request
        pipelines = await get_pipelines()
        users = await get_users()

        if len(leads) == 1:
            full = await _async_request(
                "GET", f"/leads/{leads[0]['id']}",
                params={"with": "contacts,custom_fields"}
            )
            if full.get("id"):
                full["_active_tasks"] = await get_lead_tasks(full["id"])
                from services.amocrm import get_amo_user_id as _get_amo_id
                _viewer_id = _get_amo_id(message.from_user.id)
                text = format_lead_card(full, pipelines, users, viewer_amo_id=_viewer_id)
                await message.answer(text, parse_mode="HTML")
                return

        # Несколько — список
        text = f"{deal['emoji']} <b>Найдено сделок с номером {deal['full']}: {len(leads)}</b>\n\n"
        for lead in leads:
            text += format_lead(lead) + "\n\n"
        await message.answer(text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Deal number search error: {e}")
        await message.answer(f"❌ Ошибка поиска: {str(e)[:100]}")


async def handle_lead_search(message: Message, query: str):
    await message.answer("🔍 Ищу в AmoCRM...")
    try:
        include_closed = any(w in query.lower() for w in ("закрыт", "реализован", "архив"))
        leads = await search_leads(query, limit=5, include_closed=include_closed)
        if not leads:
            await message.answer(f"❌ Сделок по запросу «{query}» не найдено.")
            return

        from services.amocrm import get_pipelines, get_users, _async_request
        pipelines = await get_pipelines()
        users = await get_users()

        # Одна сделка — полная карточка с чеклистом
        if len(leads) == 1:
            full = await _async_request("GET", f"/leads/{leads[0]['id']}", params={"with": "contacts,custom_fields"})
            if full.get("id"):
                full["_active_tasks"] = await get_lead_tasks(full["id"])
                from services.amocrm import get_amo_user_id as _get_amo_id
                _viewer_id = _get_amo_id(message.from_user.id)
                text = format_lead_card(full, pipelines, users, viewer_amo_id=_viewer_id)
                await message.answer(text, parse_mode="HTML")
                return

        # Несколько — краткий список
        text = f"📋 <b>Найдено сделок: {len(leads)}</b> по запросу «{query}»\n\n"
        for lead in leads:
            text += format_lead(lead) + "\n\n"
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Lead search error: {e}")
        await message.answer(f"❌ Ошибка поиска: {str(e)[:100]}")


# ─── Поиск контактов/компаний ────────────────────────────────────────────────

async def handle_contact_search(message: Message, query: str):
    try:
        contacts = await search_contacts(query, limit=3)
        companies = await search_companies(query, limit=3)

        if not contacts and not companies:
            await message.answer(f"❌ Контактов/компаний по запросу «{query}» не найдено.")
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

        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Contact search error: {e}")
        await message.answer(f"❌ Ошибка поиска: {str(e)[:100]}")


# ─── Парсинг задачи ───────────────────────────────────────────────────────────

def parse_task_datetime(text: str) -> tuple:
    """Парсит дату/время и номер сделки из текста задачи.
    Возвращает (текст_задачи, datetime, deal_info_or_None, explicit_time: bool)
    explicit_time=True если пользователь назвал конкретное время или «через N минут/часов»
    """
    from services.amo_leads import parse_deal_number
    _MSK = _tz(timedelta(hours=3))  # МСК UTC+3
    now = datetime.now(_MSK).replace(tzinfo=None)
    due = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    explicit_time = False  # по умолчанию — долгосрочная, напоминать за 30 мин

    for tr in TASK_TRIGGERS:
        text = re.sub(tr, "", text, flags=re.IGNORECASE).strip()

    # Убираем "по сделке", "для сделки" и т.д. перед поиском номера
    text = re.sub(r"\b(по|для|к|в|на)\s+сделк\w*\s*", " ", text, flags=re.IGNORECASE).strip()

    # Ищем номер сделки (64К, 73М и т.д.)
    deal_info = parse_deal_number(text)
    if deal_info:
        text = re.sub(r"\b" + re.escape(deal_info["full"]) + r"\b", "", text, flags=re.IGNORECASE).strip()

    # Ищем время: "в 15:30", "в 10"
    time_match = re.search(r"в\s+(\d{1,2})(?:[:\-](\d{2})|\s([0-5]\d)(?=\s|\$))?", text)
    if time_match:
        explicit_time = True
        text = text[:time_match.start()] + text[time_match.end():]

    # ─── Конкретные даты: "1 июня", "01.06", "01.06.2026" ───────────────────────
    MONTHS_RU = {
        "январ": 1, "феврал": 2, "март": 3, "апрел": 4,
        "май": 5, "мая": 5, "июн": 6, "июл": 7, "август": 8,
        "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
    }
    # "1 июня", "15 июля", "первого июня"
    date_word_match = re.search(
        r"(\d{1,2})\s+(январ\w*|феврал\w*|март\w*|апрел\w*|ма[йя]\w*|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)",
        text, re.IGNORECASE
    )
    # "01.06", "01.06.2026", "1.6.26"
    date_num_match = re.search(
        r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?",
        text
    ) if not date_word_match else None

    if date_word_match:
        day = int(date_word_match.group(1))
        month_str = date_word_match.group(2).lower()[:6]
        month = next((v for k, v in MONTHS_RU.items() if month_str.startswith(k[:4])), None)
        if month:
            year = now.year
            try:
                candidate = now.replace(year=year, month=month, day=day, hour=10, minute=0, second=0, microsecond=0)
                if candidate < now:
                    candidate = candidate.replace(year=year + 1)
                due = candidate
            except ValueError:
                pass
        text = text[:date_word_match.start()] + text[date_word_match.end():]
    elif date_num_match:
        try:
            day = int(date_num_match.group(1))
            month = int(date_num_match.group(2))
            year_raw = date_num_match.group(3)
            year = now.year
            if year_raw:
                year = int(year_raw)
                if year < 100:
                    year += 2000
            if 1 <= day <= 31 and 1 <= month <= 12:
                candidate = now.replace(year=year, month=month, day=day, hour=10, minute=0, second=0, microsecond=0)
                if candidate < now:
                    candidate = candidate.replace(year=year + 1)
                due = candidate
                text = text[:date_num_match.start()] + text[date_num_match.end():]
        except (ValueError, AttributeError):
            pass

    # ─── Ищем день ────────────────────────────────────────────────────────────
    if "послезавтра" in text.lower():
        due = (now + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
        text = re.sub(r"послезавтра", "", text, flags=re.IGNORECASE)
    elif "завтра" in text.lower():
        due = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        text = re.sub(r"завтра", "", text, flags=re.IGNORECASE)
    elif "сегодня" in text.lower():
        due = now.replace(second=0, microsecond=0)
        text = re.sub(r"сегодня", "", text, flags=re.IGNORECASE)

    # Через N минут / часов / дней (+ словесные формы: минуту, час, день)
    WORD_NUMS = {
        "одн": 1, "одну": 1, "один": 1,
        "дв": 2, "две": 2, "двух": 2, "двум": 2,
        "три": 3, "трёх": 3, "трех": 3,
        "четыр": 4, "четыр": 4,
        "пять": 5, "пяти": 5, "пятью": 5,
        "шест": 6, "семь": 7, "семи": 7,
        "восем": 8, "девят": 9,
        "десять": 10, "десяти": 10,
        "пятнадц": 15, "двадц": 20, "тридц": 30,
        "полчаса": 30, "полчас": 30,
    }

    # Проверяем дробные часы: полчаса, полтора часа, два с половиной и т.д.
    half_patterns = [
        (r"через\s+пол\s*часа?", 30),                          # через полчаса / пол часа
        (r"через\s+полтора\s*часа?", 90),                      # через полтора часа
        (r"через\s+(\d+)\s+с\s+половиной\s+час\w*",  None), # через 2 с половиной часа
        (r"через\s+(\d+)[.,]5\s*час\w*", None),              # через 2.5 часа
    ]
    half_found = False
    for pattern, minutes in half_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            if minutes:
                due = now + timedelta(minutes=minutes)
            else:
                # Извлекаем число часов
                hrs = int(m.group(1))
                due = now + timedelta(minutes=int(hrs * 60 + 30))
            explicit_time = True
            text = text[:m.start()] + text[m.end():]
            half_found = True
            break

    # Сначала проверяем "через минуту/час/день" (без числа)
    single_match = re.search(r"через\s+(минуту|минутку|час|день|неделю)", text, re.IGNORECASE)
    if single_match:
        unit = single_match.group(1).lower()
        if unit in ("минуту", "минутку"):
            due = now + timedelta(minutes=1)
            explicit_time = True
        elif unit == "час":
            due = now + timedelta(hours=1)
            explicit_time = True
        elif unit == "день":
            due = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        elif unit == "неделю":
            due = now + timedelta(weeks=1)
        text = text[:single_match.start()] + text[single_match.end():]

    time_delta_match = None if single_match else re.search(
        r"через\s+(\d+|одну?|один|дв[уе]|три|четыр\w*|пять|десять|пятнадц\w*|двадц\w*|полчас\w*)\s*(минут\w*|мин|час\w*|ч|дн\w*|день|дней|недел\w*)",
        text, re.IGNORECASE
    )
    if time_delta_match:
        raw_n = time_delta_match.group(1).lower()
        try:
            n = int(raw_n)
        except ValueError:
            n = next((v for k, v in WORD_NUMS.items() if raw_n.startswith(k)), 1)
        unit = time_delta_match.group(2).lower()
        if unit.startswith("мин"):
            due = now + timedelta(minutes=n)
            explicit_time = True
        elif unit.startswith("час") or unit == "ч":
            due = now + timedelta(hours=n)
            explicit_time = True
        elif unit.startswith("недел"):
            due = now + timedelta(weeks=n)
        else:
            due = (now + timedelta(days=n)).replace(hour=10, minute=0, second=0, microsecond=0)
        text = text[:time_delta_match.start()] + text[time_delta_match.end():]

    if time_match:
        mins_raw = time_match.group(2) or time_match.group(3)
        due = due.replace(
            hour=int(time_match.group(1)),
            minute=int(mins_raw) if mins_raw else 0,
            second=0, microsecond=0
        )

    text = re.sub(r"^(по|для|к)\s+", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ,.")
    return text or "Задача из Telegram", due, deal_info, explicit_time


async def _remind_later(chat_id: int, task_text: str, deal_name: str, delay: float):
    """Отправляет напоминание в Telegram через delay секунд."""
    await asyncio.sleep(delay)
    try:
        from bot_instance import bot
        deal_str = f"\n🔗 {deal_name}" if deal_name else ""
        await bot.send_message(
            chat_id,
            f"⏰ <b>Напоминание!</b>\n\n📝 {task_text}{deal_str}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Remind error: {e}")


async def handle_task_create(message: Message, raw_text: str):
    """Создаёт задачу в AmoCRM. Если есть номер сделки — привязывает."""
    task_text, due_dt, deal_info, explicit_time = parse_task_datetime(raw_text)
    try:
        from services.amocrm import get_amo_user_id, search_leads_by_number
        from services.scheduler import schedule_reminder
        from bot_instance import bot
        responsible_id = get_amo_user_id(message.from_user.id)
        entity_id = None
        deal_name = ""

        if deal_info:
            leads = await search_leads_by_number(deal_info["search_query"])
            if leads:
                entity_id = leads[0]["id"]
                deal_name = leads[0]["name"]
            else:
                await message.answer(
                    f"⚠️ Сделка <b>{deal_info['full']}</b> не найдена — задача без привязки.",
                    parse_mode="HTML"
                )

        task = await create_task(
            text=task_text,
            entity_id=entity_id,
            due_dt=due_dt,
            responsible_user_id=responsible_id,
        )
        if task.get("id"):
            due_str = due_dt.strftime("%d.%m.%Y в %H:%M")
            deal_str = f"\n🔗 Сделка: <b>{deal_name}</b>" if deal_name else ""
            remind_note = "⏰ Напомню за 30 минут до срока" if not explicit_time else f"⏰ Напомню в {due_dt.strftime('%H:%M')}"
            await message.answer(
                f"✅ <b>Задача создана</b>\n\n"
                f"📝 {task_text}\n"
                f"🕐 Срок: {due_str}"
                f"{deal_str}\n"
                f"<i>{remind_note}</i>",
                parse_mode="HTML"
            )
            delay_total = (due_dt - datetime.now()).total_seconds()
            if delay_total > 0:
                schedule_reminder(
                    bot=bot,
                    chat_id=message.chat.id,
                    task_id=task["id"],
                    task_text=task_text,
                    deal_name=deal_name,
                    due_dt=due_dt,
                    explicit_time=explicit_time,
                )
        else:
            await message.answer("❌ Не удалось создать задачу.")
    except Exception as e:
        logger.error(f"Task create error: {e}")
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")


@router.message(Command("overdue"))
async def cmd_overdue(message: Message):
    await message.answer("⏳ Загружаю просроченные задачи...")
    try:
        from services.amocrm import get_amo_user_id
        amo_user_id = get_amo_user_id(message.from_user.id)
        tasks = await get_overdue_tasks(responsible_user_id=amo_user_id)
        if not tasks:
            await message.answer("✅ Просроченных задач нет!")
            return

        text = f"⚠️ <b>Просроченные задачи: {len(tasks)}</b>\n\n"
        for t in tasks[:10]:
            lead_title = t.get('lead_name') or "Без названия"
            lead_id = t.get('entity_id', '')
            pipeline = t.get('pipeline', '')
            status = t.get('status', '')
            pipeline_str = f"{pipeline} → {status}" if pipeline and status else ""
            text += (
                f"• <b>{lead_title}</b> (ID: {lead_id})\n"
            )
            if pipeline_str:
                text += f"  📊 {pipeline_str}\n"
            text += (
                f"  📅 Срок: {t['due']}\n"
                f"  📝 {t['text'][:80]}\n\n"
            )
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")


# ─── Сделки без движения ──────────────────────────────────────────────────────

@router.message(Command("stale"))
async def cmd_stale(message: Message):
    await message.answer("⏳ Загружаю сделки без движения...")
    try:
        from services.amocrm import get_amo_user_id
        amo_user_id = get_amo_user_id(message.from_user.id)
        leads = await get_stale_leads(days=7, responsible_user_id=amo_user_id)
        if not leads:
            await message.answer("✅ Все сделки активны!")
            return

        text = f"😴 <b>Сделки без движения 7+ дней: {len(leads)}</b>\n\n"
        for lead in leads[:10]:
            text += (
                f"• <b>{lead['name']}</b> (ID: {lead['id']})\n"
                f"  📊 {lead['pipeline']} → {lead['status']}\n"
                f"  👤 {lead['responsible']} | ⏱ {lead['days_ago']} дней\n\n"
            )
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")


# ─── Примечания к сделке ────────────────────────────────────────────────────

async def handle_note_add(message: Message, raw_text: str):
    """Добавляет примечание к сделке. Пример: «добавь примечание по 88КЭ: согласовали цену»"""
    from services.amo_leads import parse_deal_number
    # Убираем триггер
    text = raw_text
    for tr in NOTE_TRIGGERS:
        import re as _re
        text = _re.sub(tr, "", text, flags=_re.IGNORECASE).strip()

    # Ищем номер сделки
    deal_info = parse_deal_number(raw_text)
    if deal_info:
        text = text.replace(deal_info["full"], "").strip(" :,-")

    # Текст после двоеточия
    if ":" in text:
        text = text.split(":", 1)[1].strip()

    if not text:
        await message.answer("Укажи текст примечания. Пример: «добавь примечание по 88КЭ: согласовали цену 15000$»")
        return

    if not deal_info:
        await message.answer("Укажи номер сделки. Пример: «добавь примечание по 88КЭ: текст»")
        return

    await message.answer(f"📝 Ищу сделку {deal_info['full']}...")
    try:
        from services.amocrm import search_leads_by_number
        leads = await search_leads_by_number(deal_info["search_query"])
        if not leads:
            await message.answer(f"❌ Сделка <b>{deal_info['full']}</b> не найдена.", parse_mode="HTML")
            return

        lead = leads[0]
        note = await add_note(entity_id=lead["id"], text=text)
        if note.get("id"):
            await message.answer(
                f"✅ <b>Примечание добавлено</b>\n\n"
                f"🔗 Сделка: <b>{lead['name']}</b>\n"
                f"📝 {text}",
                parse_mode="HTML"
            )
        else:
            await message.answer("❌ Не удалось добавить примечание.")
    except Exception as e:
        logger.error(f"Note add error: {e}")
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")


# ─── Создание сделки ────────────────────────────────────────────────────────

async def handle_lead_create(message: Message, raw_text: str):
    """Создаёт сделку в AmoCRM из текста (заявка, письмо, голос)."""
    import os as _os
    from services.amo_create import parse_lead_from_text, create_lead_from_parsed
    from services.amocrm import get_amo_user_id
    _amo_domain = _os.getenv("AMO_DOMAIN", "westasia.amocrm.ru")

    await message.answer("⏳ Анализирую заявку...")
    try:
        parsed = await parse_lead_from_text(raw_text)
        if not parsed:
            await message.answer("❌ Не удалось распознать данные заявки.")
            return

        lines = ["📋 <b>Распознал следующие данные:</b>\n"]
        if parsed.get("deal_name"):
            lines.append(f"📦 Название: <b>{parsed['deal_name']}</b>")
        if parsed.get("name"):
            lines.append(f"👤 Контакт: {parsed['name']}")
        if parsed.get("phone"):
            lines.append(f"📞 Телефон: {parsed['phone']}")
        if parsed.get("email"):
            lines.append(f"📧 Email: {parsed['email']}")
        if parsed.get("company"):
            lines.append(f"🏢 Компания: {parsed['company']}")
        if parsed.get("cargo_desc"):
            lines.append(f"📝 Груз: {parsed['cargo_desc'][:100]}")
        if parsed.get("weight_kg"):
            lines.append(f"⚖️ Вес: {parsed['weight_kg']} кг")
        if parsed.get("volume_m3"):
            lines.append(f"📐 Объём: {parsed['volume_m3']} м³")
        if parsed.get("origin"):
            lines.append(f"🛫 Откуда: {parsed['origin']}")
        if parsed.get("destination"):
            lines.append(f"🛬 Куда: {parsed['destination']}")
        if parsed.get("transport_type"):
            lines.append(f"🚚 Тип: {parsed['transport_type']}")
        if parsed.get("notes"):
            lines.append(f"💬 Доп. инфо: {parsed['notes'][:100]}")
        lines.append("\n<i>Создаю сделку в AmoCRM...</i>")
        await message.answer("\n".join(lines), parse_mode="HTML")

        responsible_id = get_amo_user_id(message.from_user.id)
        result = await create_lead_from_parsed(parsed, responsible_user_id=responsible_id, raw_text=raw_text)

        if result.get("id"):
            await message.answer(
                f"✅ <b>Сделка создана!</b>\n\n"
                f"📋 {result['name']}\n"
                f"📊 {result.get('pipeline_label', 'Контракт Клиента → Новая заявка')}\n"
                f"🔗 <a href='https://{_amo_domain}/leads/detail/{result['id']}'>Открыть в AmoCRM</a>",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        else:
            await message.answer("❌ Не удалось создать сделку в AmoCRM.")
    except Exception as e:
        logger.error(f"Lead create error: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")


async def callback_task_action(callback: CallbackQuery):
    from services.scheduler import handle_task_callback
    from bot_instance import bot
    await handle_task_callback(callback, bot)



# ─── Главная точка входа (вызывается из text.py) ─────────────────────────────

async def handle_amo_request(message: Message, user_text: str):
    """Обрабатывает запросы к AmoCRM из text.py."""
    text_lower = user_text.lower()

    # Номер сделки (64К, 73М, 82ЖД, 91А, 107Авто)
    deal = parse_deal_number(user_text)
    if deal and not _has_task_intent(user_text) and not any(tr in text_lower for tr in CONTACT_TRIGGERS) and not any(tr in text_lower for tr in NOTE_TRIGGERS):
        await handle_deal_number_search(message, deal)
        return

    # Поиск сделок
    if any(tr in text_lower for tr in LEAD_TRIGGERS):
        # Убираем триггер из запроса
        query = user_text
        for tr in LEAD_TRIGGERS:
            query = re.sub(tr, '', query, flags=re.IGNORECASE).strip()
        # Убираем предлоги в начале
        query = re.sub(r'^(с|со|по|у нас|нас|что|у)\s+', '', query, flags=re.IGNORECASE).strip()
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
    elif _has_task_intent(user_text):
        await handle_task_create(message, user_text)

    # Мои задачи
    elif any(tr in text_lower for tr in MYTASKS_TRIGGERS):
        await handle_mytasks(message)

    # Поиск контакта
    elif any(tr in text_lower for tr in CONTACT_SEARCH_TRIGGERS):
        await handle_contact_search_full(message, user_text)

    # Создание сделки
    elif any(tr in text_lower for tr in CREATE_TRIGGERS):
        await handle_lead_create(message, user_text)

    # Примечание к сделке
    elif any(tr in text_lower for tr in NOTE_TRIGGERS):
        await handle_note_add(message, user_text)

    else:
        await message.answer("Не понял запрос к CRM. Попробуй: «найди сделку», «реквизиты клиента», «напомни завтра в 10», «добавь примечание по 88КЭ: текст»")
