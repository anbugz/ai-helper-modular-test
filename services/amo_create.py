"""
services/amo_create.py — создание сделок и контактов в AmoCRM.

Воронка по умолчанию: Контракт Клиента (id=10909302)
Этап по умолчанию: Новая заявка (id=85806450)
"""
import re
import json
import asyncio
from datetime import datetime
from config import logger
from services.amocrm import _async_request, get_amo_user_id

# Воронка и этап по умолчанию для новых сделок
DEFAULT_PIPELINE_ID = 10909302   # Контракт Клиента
DEFAULT_STATUS_ID   = 85806450   # Новая заявка

# ID кастомных полей контакта
CONTACT_FIELD_PHONE = 578354
CONTACT_FIELD_EMAIL = 578356

# ID кастомных полей сделки (из amo_leads.py)
LEAD_FIELD_CARGO_DESC  = 1084193
LEAD_FIELD_WEIGHT      = 1084187
LEAD_FIELD_VOLUME      = 1084197
LEAD_FIELD_ORIGIN      = 1084199
LEAD_FIELD_DESTINATION = 1084201

# Маппинг типа транспорта → enum value в AmoCRM
TRANSPORT_KEYWORDS = {
    "авиа": "Авиа",
    "авиа-": "Авиа",
    "море": "Море",
    "морем": "Море",
    "морской": "Море",
    "авто": "Авто",
    "автомобил": "Авто",
    "жд": "ЖД",
    "ж/д": "ЖД",
    "железнодор": "ЖД",
    "карго": "Карго (сборный)",
    "сборн": "Карго (сборный)",
}

SYSTEM_PROMPT_PARSE = """Ты парсер заявок для логистической компании West Asia.
Из текста извлеки поля в JSON. Отвечай ТОЛЬКО валидным JSON без комментариев и markdown.

Поля:
- name: имя контакта (строка или null)
- phone: телефон в формате +7XXXXXXXXXX (строка или null)
- email: email (строка или null)
- company: название компании (строка или null)
- cargo_desc: описание груза (строка или null)
- weight_kg: вес в кг (число или null)
- volume_m3: объём в м3 (число или null)
- origin: пункт отправления / откуда (строка или null)
- destination: пункт назначения / куда (строка или null)
- transport_type: тип транспорта — одно из: Авиа, Море, Авто, ЖД, Карго (сборный), null
- deal_name: короткое название сделки (строка, обязательно — придумай из описания груза)
- notes: любая важная информация которую не вошла в другие поля (строка или null)

Примеры deal_name: "Квадроциклы 2шт", "Транспаки из Фошаня", "Головоломки 3000шт"
"""

async def parse_lead_from_text(text: str) -> dict:
    """Парсит текст через DeepSeek и возвращает словарь с полями заявки."""
    import os
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com/v1",
    )
    try:
        resp = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_PARSE},
                {"role": "user", "content": text},
            ],
            max_tokens=500,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```json|^```|```$", "", raw, flags=re.MULTILINE).strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"parse_lead_from_text error: {e}")
        return {}


async def find_or_create_contact(name: str = None, phone: str = None, email: str = None) -> int | None:
    """Ищет контакт по телефону/email, если не найден — создаёт. Возвращает contact_id."""
    # Сначала ищем существующий
    if phone:
        resp = await _async_request("GET", "/contacts", params={"query": phone, "limit": 1})
        contacts = resp.get("_embedded", {}).get("contacts", [])
        if contacts:
            logger.info(f"Найден существующий контакт: {contacts[0]['id']}")
            return contacts[0]["id"]
    if email:
        resp = await _async_request("GET", "/contacts", params={"query": email, "limit": 1})
        contacts = resp.get("_embedded", {}).get("contacts", [])
        if contacts:
            return contacts[0]["id"]

    # Создаём новый
    contact = {"name": name or "Новый контакт", "custom_fields_values": []}
    if phone:
        contact["custom_fields_values"].append({
            "field_id": CONTACT_FIELD_PHONE,
            "values": [{"value": phone, "enum_code": "WORK"}],
        })
    if email:
        contact["custom_fields_values"].append({
            "field_id": CONTACT_FIELD_EMAIL,
            "values": [{"value": email, "enum_code": "WORK"}],
        })

    resp = await _async_request("POST", "/contacts", data=[contact])
    contacts = resp.get("_embedded", {}).get("contacts", [])
    if contacts:
        logger.info(f"Создан контакт: {contacts[0]['id']}")
        return contacts[0]["id"]
    return None


async def create_lead_from_parsed(parsed: dict, responsible_user_id: int = None) -> dict:
    """Создаёт сделку в AmoCRM из распарсенных данных."""
    today = datetime.now().strftime("%d.%m.%Y")
    deal_name = parsed.get("deal_name") or "Новая заявка"
    lead_name = f"{deal_name} {today}"

    # Кастомные поля сделки
    custom_fields = []
    if parsed.get("cargo_desc"):
        custom_fields.append({"field_id": LEAD_FIELD_CARGO_DESC, "values": [{"value": parsed["cargo_desc"]}]})
    if parsed.get("weight_kg"):
        custom_fields.append({"field_id": LEAD_FIELD_WEIGHT, "values": [{"value": str(parsed["weight_kg"])}]})
    if parsed.get("volume_m3"):
        custom_fields.append({"field_id": LEAD_FIELD_VOLUME, "values": [{"value": str(parsed["volume_m3"])}]})
    if parsed.get("origin"):
        custom_fields.append({"field_id": LEAD_FIELD_ORIGIN, "values": [{"value": parsed["origin"]}]})
    if parsed.get("destination"):
        custom_fields.append({"field_id": LEAD_FIELD_DESTINATION, "values": [{"value": parsed["destination"]}]})

    lead = {
        "name": lead_name,
        "pipeline_id": DEFAULT_PIPELINE_ID,
        "status_id": DEFAULT_STATUS_ID,
        "_embedded": {},
    }
    if responsible_user_id:
        lead["responsible_user_id"] = responsible_user_id
    if custom_fields:
        lead["custom_fields_values"] = custom_fields

    # Создаём контакт
    contact_id = await find_or_create_contact(
        name=parsed.get("name"),
        phone=parsed.get("phone"),
        email=parsed.get("email"),
    )
    if contact_id:
        lead["_embedded"]["contacts"] = [{"id": contact_id}]

    resp = await _async_request("POST", "/leads", data=[lead])
    leads = resp.get("_embedded", {}).get("leads", [])
    if not leads:
        return {}

    lead_id = leads[0]["id"]

    # Добавляем примечание с доп. информацией если есть
    notes_text = ""
    if parsed.get("notes"):
        notes_text += parsed["notes"]
    if parsed.get("company"):
        notes_text = f"Компания: {parsed['company']}\n" + notes_text

    if notes_text.strip():
        from services.amocrm import add_note
        await add_note(entity_id=lead_id, text=notes_text.strip())

    return {"id": lead_id, "name": lead_name, "contact_id": contact_id}
