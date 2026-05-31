"""
services/ai.py — DeepSeek API wrapper (на чистом httpx, без openai SDK).

Прямой вызов через httpx с ЯВНЫМИ таймаутами — лечит зависание на чтении
тела ответа (read timeout), которое возникало в openai SDK при использовании
переиспользуемых keep-alive соединений.
"""
import httpx
from typing import List, Dict
from config import DEEPSEEK_API_KEY, logger

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# Явные таймауты: connect=10с, read=60с (генерация длинного ответа),
# write=10с, pool=5с. read=60 гарантирует, что зависший сокет не повесит бота навсегда.
_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=5.0)


async def ask_deepseek(messages: List[Dict]) -> str:
    """Отправляет список сообщений в DeepSeek API, возвращает текст ответа."""
    if not DEEPSEEK_API_KEY:
        return "⚠️ DEEPSEEK_API_KEY не задан в .env"

    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 3000,
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        # Новый клиент на запрос, БЕЗ keep-alive (max_keepalive_connections=0),
        # чтобы не переиспользовать мёртвые соединения.
        limits = httpx.Limits(max_keepalive_connections=0, max_connections=10)
        async with httpx.AsyncClient(timeout=_TIMEOUT, limits=limits) as client:
            resp = await client.post(DEEPSEEK_URL, json=payload, headers=headers)

        if resp.status_code != 200:
            logger.error(f"DeepSeek HTTP {resp.status_code}: {resp.text[:300]}")
            return f"⚠️ Ошибка DeepSeek (HTTP {resp.status_code})"

        data = resp.json()
        choice = data["choices"][0]
        answer = choice["message"].get("content") or ""
        finish = choice.get("finish_reason", "")
        usage = data.get("usage", {})
        logger.info(
            f"[DeepSeek] finish_reason={finish}, tokens: "
            f"prompt={usage.get('prompt_tokens')}, "
            f"completion={usage.get('completion_tokens')}, "
            f"total={usage.get('total_tokens')}"
        )
        if finish == "length":
            answer += "\n\n⚠️ <i>Ответ был обрезан — слишком длинный. Уточните вопрос.</i>"
        return answer

    except httpx.ReadTimeout:
        logger.error("DeepSeek read timeout (60s) — сервер не вернул тело ответа")
        return "⚠️ AI отвечает слишком медленно. Попробуйте ещё раз или упростите запрос."
    except httpx.ConnectTimeout:
        logger.error("DeepSeek connect timeout")
        return "⚠️ Не удалось подключиться к AI. Попробуйте позже."
    except Exception as e:
        logger.error(f"DeepSeek API error: {e}")
        return f"⚠️ Ошибка при обращении к AI: {e}"


def build_messages(
    user_id: int,
    user_text: str,
    extra_context: str = "",
    include_history: bool = True,
    history_limit: int = None,
) -> List[Dict]:
    """Строит список сообщений для DeepSeek API.

    Args:
        user_id: ID пользователя для получения истории
        user_text: Текст текущего запроса
        extra_context: Дополнительный системный контекст
        include_history: Включать ли историю диалога
        history_limit: Сколько последних сообщений истории брать (по умолчанию MAX_HISTORY)
    """
    from config import SYSTEM_PROMPT, MAX_HISTORY
    from database import get_dialog_history
    from datetime import datetime as _dt
    _now = _dt.now()
    _months = {1:"января",2:"февраля",3:"марта",4:"апреля",5:"мая",6:"июня",
               7:"июля",8:"августа",9:"сентября",10:"октября",11:"ноября",12:"декабря"}
    _date_str = f"{_now.day} {_months[_now.month]} {_now.year} года"
    _system_with_date = SYSTEM_PROMPT + f" Сегодня {_date_str}."

    msgs = [{"role": "system", "content": _system_with_date}]

    if include_history:
        # Инструкция про контекст диалога — LLM сама решает, продолжение это или новый запрос
        msgs.append({
            "role": "system",
            "content": (
                "Это диалог в мессенджере с менеджером по ВЭД. Учитывай контекст беседы:\n"
                "— Если текущее сообщение УТОЧНЯЕТ предыдущий вопрос (отвечает на твои уточняющие "
                "вопросы, добавляет характеристики обсуждаемого товара) — продолжай ту же тему, "
                "не начинай подбор заново. Например: ранее спросили про футболки, сейчас пишут "
                "«100% хлопок» — это всё равно футболки, а не хлопковая ткань.\n"
                "— Если текущее сообщение — ЯВНО НОВЫЙ запрос (другой товар, другая задача, "
                "новый расчёт) — обрабатывай его самостоятельно, не смешивая со старой темой.\n"
                "— Сам определи по смыслу, какой это случай."
            ),
        })

    if extra_context:
        msgs.append({"role": "system", "content": extra_context})

    if include_history:
        limit = history_limit if history_limit is not None else MAX_HISTORY
        history = get_dialog_history(user_id, limit=limit)
        # Последнее сообщение в истории — это текущий запрос (уже сохранён в БД до вызова),
        # исключаем его, чтобы не дублировать с финальным user-сообщением ниже.
        if history and history[-1]["role"] == "user" and history[-1]["content"] == user_text:
            history = history[:-1]
        for h in history:
            msgs.append({"role": h["role"], "content": h["content"]})

    msgs.append({"role": "user", "content": user_text})
    return msgs
