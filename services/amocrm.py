"""
services/amocrm.py — интеграция с AmoCRM API.

Функции:
- Поиск сделок по названию/контакту
- Поиск контактов/компаний
- Создание задач
- Добавление примечаний к сделкам
- Получение воронок и этапов
"""
import json
import asyncio
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional
from config import logger

import os
AMO_DOMAIN = os.getenv("AMO_DOMAIN", "")
AMO_ACCESS_TOKEN = os.getenv("AMO_ACCESS_TOKEN", "")
AMO_CLIENT_ID = os.getenv("AMO_CLIENT_ID", "")
AMO_CLIENT_SECRET = os.getenv("AMO_CLIENT_SECRET", "")

BASE_URL = f"https://{AMO_DOMAIN}/api/v4"

# Кеш воронок: {pipeline_id: {name, statuses: {status_id: name}}}
_pipelines_cache: dict = {}
_pipelines_cache_ts: float = 0


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {AMO_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _request(method: str, path: str, data: dict = None, params: dict = None) -> dict:
    """Синхронный HTTP запрос к AmoCRM API."""
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=_headers(), method=method)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e else ""
        logger.error(f"AmoCRM HTTP {e.code}: {path} — {body[:200]}")
        return {"error": e.code, "detail": body[:200]}
    except Exception as e:
        logger.error(f"AmoCRM error: {e}")
        return {"error": str(e)}


async def _async_request(method: str, path: str, data: dict = None, params: dict = None) -> dict:
    return await asyncio.to_thread(_request, method, path, data, params)


# ─── Воронки и этапы ──────────────────────────────────────────────────────────

async def get_pipelines() -> dict:
    """Возвращает словарь {pipeline_id: {name, statuses}}. Кеш 10 мин."""
    global _pipelines_cache, _pipelines_cache_ts
    import time
    if _pipelines_cache and time.monotonic() - _pipelines_cache_ts < 600:
        return _pipelines_cache

    resp = await _async_request("GET", "/leads/pipelines")
    result = {}
    for pipeline in resp.get("_embedded", {}).get("pipelines", []):
        statuses = {}
        for s in pipeline.get("_embedded", {}).get("statuses", []):
            statuses[s["id"]] = s["name"]
        result[pipeline["id"]] = {
            "name": pipeline["name"],
            "statuses": statuses
        }
    _pipelines_cache = result
    _pipelines_cache_ts = time.monotonic()
    return result


async def get_status_name(pipeline_id: int, status_id: int) -> str:
    """Возвращает название этапа по ID."""
    pipelines = await get_pipelines()
    pipeline = pipelines.get(pipeline_id, {})
    return pipeline.get("statuses", {}).get(status_id, f"Этап {status_id}")


async def get_pipeline_name(pipeline_id: int) -> str:
    pipelines = await get_pipelines()
    return pipelines.get(pipeline_id, {}).get("name", f"Воронка {pipeline_id}")


# ─── Пользователи ─────────────────────────────────────────────────────────────

_users_cache: dict = {}

async def get_users() -> dict:
    """Возвращает {user_id: name}."""
    global _users_cache
    if _users_cache:
        return _users_cache
    resp = await _async_request("GET", "/users")
    result = {}
    for u in resp.get("_embedded", {}).get("users", []):
        result[u["id"]] = u["name"]
    _users_cache = result
    return result


async def get_user_name(user_id: int) -> str:
    users = await get_users()
    return users.get(user_id, f"Пользователь {user_id}")


# ─── Поиск сделок ─────────────────────────────────────────────────────────────

async def search_leads(query: str, limit: int = 5) -> list:
    """Ищет сделки по названию или контакту."""
    resp = await _async_request("GET", "/leads", params={
        "query": query,
        "limit": limit,
        "with": "contacts",
    })
    leads = resp.get("_embedded", {}).get("leads", [])
    pipelines = await get_pipelines()
    users = await get_users()

    result = []
    for lead in leads:
        pipeline_id = lead.get("pipeline_id", 0)
        status_id = lead.get("status_id", 0)
        pipeline = pipelines.get(pipeline_id, {})
        pipeline_name = pipeline.get("name", "—")
        status_name = pipeline.get("statuses", {}).get(status_id, "—")
        responsible = users.get(lead.get("responsible_user_id", 0), "—")

        # Контакты
        contacts = []
        for c in lead.get("_embedded", {}).get("contacts", []):
            contacts.append(c.get("name", ""))

        result.append({
            "id": lead["id"],
            "name": lead.get("name", "Без названия"),
            "price": lead.get("price", 0),
            "pipeline": pipeline_name,
            "status": status_name,
            "responsible": responsible,
            "contacts": contacts,
            "created_at": lead.get("created_at", 0),
            "updated_at": lead.get("updated_at", 0),
        })
    return result


def format_lead(lead: dict) -> str:
    """Форматирует сделку для отображения в Telegram."""
    contacts_str = ", ".join(lead["contacts"]) if lead["contacts"] else "—"
    price_str = f"{lead['price']:,} ₽".replace(",", " ") if lead["price"] else "—"

    updated = ""
    if lead.get("updated_at"):
        dt = datetime.fromtimestamp(lead["updated_at"])
        updated = dt.strftime("%d.%m.%Y")

    return (
        f"📋 <b>{lead['name']}</b>\n"
        f"🆔 ID: <code>{lead['id']}</code>\n"
        f"📊 Этап: {lead['pipeline']} → <b>{lead['status']}</b>\n"
        f"👤 Ответственный: {lead['responsible']}\n"
        f"💰 Бюджет: {price_str}\n"
        f"👥 Контакты: {contacts_str}\n"
        f"🕐 Обновлена: {updated}"
    )


# ─── Поиск контактов/компаний ────────────────────────────────────────────────

async def search_contacts(query: str, limit: int = 3) -> list:
    """Ищет контакты и компании по названию/ИНН."""
    resp = await _async_request("GET", "/contacts", params={
        "query": query,
        "limit": limit,
        "with": "leads,customers",
    })
    contacts = resp.get("_embedded", {}).get("contacts", [])
    result = []
    for c in contacts:
        # Кастомные поля
        fields = {}
        for f in c.get("custom_fields_values", []) or []:
            fname = f.get("field_name", "")
            fval = f.get("values", [{}])[0].get("value", "")
            if fname and fval:
                fields[fname] = fval

        result.append({
            "id": c["id"],
            "name": c.get("name", "—"),
            "fields": fields,
            "leads_count": len(c.get("_embedded", {}).get("leads", [])),
        })
    return result


async def search_companies(query: str, limit: int = 3) -> list:
    """Ищет компании."""
    resp = await _async_request("GET", "/companies", params={
        "query": query,
        "limit": limit,
    })
    companies = resp.get("_embedded", {}).get("companies", [])
    result = []
    for c in companies:
        fields = {}
        for f in c.get("custom_fields_values", []) or []:
            fname = f.get("field_name", "")
            fval = f.get("values", [{}])[0].get("value", "")
            if fname and fval:
                fields[fname] = fval

        result.append({
            "id": c["id"],
            "name": c.get("name", "—"),
            "fields": fields,
        })
    return result


# ─── Создание задач ───────────────────────────────────────────────────────────

async def create_task(
    text: str,
    entity_id: int = None,
    entity_type: str = "leads",
    due_dt: datetime = None,
    responsible_user_id: int = None,
) -> dict:
    """Создаёт задачу в AmoCRM."""
    if due_dt is None:
        due_dt = datetime.now() + timedelta(days=1)

    task_type_id = 1  # Позвонить (стандартный тип)
    payload = {
        "text": text,
        "complete_till": int(due_dt.timestamp()),
        "task_type_id": task_type_id,
    }
    if entity_id:
        payload["entity_id"] = entity_id
        payload["entity_type"] = entity_type
    if responsible_user_id:
        payload["responsible_user_id"] = responsible_user_id

    resp = await _async_request("POST", "/tasks", data=[payload])
    tasks = resp.get("_embedded", {}).get("tasks", [])
    return tasks[0] if tasks else {}


# ─── Добавление примечания ────────────────────────────────────────────────────

async def add_note(entity_id: int, text: str, entity_type: str = "leads") -> dict:
    """Добавляет примечание к сделке/контакту."""
    payload = [{
        "entity_id": entity_id,
        "note_type": "common",
        "params": {"text": text}
    }]
    resp = await _async_request("POST", f"/{entity_type}/notes", data=payload)
    notes = resp.get("_embedded", {}).get("notes", [])
    return notes[0] if notes else {}


# ─── Просроченные задачи ─────────────────────────────────────────────────────

async def get_overdue_tasks(responsible_user_id: int = None) -> list:
    """Возвращает просроченные задачи."""
    params = {
        "filter[is_completed]": 0,
        "filter[complete_till][to]": int(datetime.now().timestamp()),
        "limit": 20,
        "with": "lead",
    }
    if responsible_user_id:
        params["filter[responsible_user_id][]"] = responsible_user_id

    resp = await _async_request("GET", "/tasks", params=params)
    tasks = resp.get("_embedded", {}).get("tasks", [])
    users = await get_users()
    result = []
    for t in tasks:
        due = datetime.fromtimestamp(t.get("complete_till", 0))
        result.append({
            "id": t["id"],
            "text": t.get("text", "—"),
            "due": due.strftime("%d.%m.%Y %H:%M"),
            "responsible": users.get(t.get("responsible_user_id", 0), "—"),
            "entity_id": t.get("entity_id"),
            "entity_type": t.get("entity_type"),
        })
    return result


async def get_stale_leads(days: int = 7, responsible_user_id: int = None) -> list:
    """Возвращает сделки которые не двигались N дней."""
    threshold = int((datetime.now() - timedelta(days=days)).timestamp())
    params = {
        "filter[updated_at][to]": threshold,
        "filter[statuses][0][pipeline_id]": 0,  # все воронки
        "limit": 20,
    }
    if responsible_user_id:
        params["filter[responsible_user_id][]"] = responsible_user_id

    resp = await _async_request("GET", "/leads", params=params)
    leads = resp.get("_embedded", {}).get("leads", [])
    pipelines = await get_pipelines()
    users = await get_users()
    result = []
    for lead in leads:
        pipeline_id = lead.get("pipeline_id", 0)
        status_id = lead.get("status_id", 0)
        pipeline = pipelines.get(pipeline_id, {})
        updated = datetime.fromtimestamp(lead.get("updated_at", 0))
        days_ago = (datetime.now() - updated).days
        result.append({
            "id": lead["id"],
            "name": lead.get("name", "—"),
            "pipeline": pipeline.get("name", "—"),
            "status": pipeline.get("statuses", {}).get(status_id, "—"),
            "responsible": users.get(lead.get("responsible_user_id", 0), "—"),
            "days_ago": days_ago,
        })
    return result
