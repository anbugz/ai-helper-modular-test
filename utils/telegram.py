"""
utils/telegram.py — работа с Telegram API: отправка сообщений, rate limit.
Перенос из utils.py.
"""
import asyncio
from datetime import datetime
from typing import Dict
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from config import RATE_LIMIT_SECONDS, logger


# ------------------------------------------------------------------
# RATE LIMIT
# ------------------------------------------------------------------

_last_request_time: Dict[int, datetime] = {}


def check_rate_limit(user_id: int) -> bool:
    """Проверяет rate limit для пользователя.
    
    Returns:
        True если запрос разрешён, False если нужно подождать.
    """
    now = datetime.utcnow()
    last = _last_request_time.get(user_id)
    if last and (now - last).total_seconds() < RATE_LIMIT_SECONDS:
        return False
    _last_request_time[user_id] = now
    return True


def clear_rate_limit(user_id: int) -> None:
    """Сбрасывает rate limit для пользователя (например, после голосового)."""
    _last_request_time.pop(user_id, None)


# ------------------------------------------------------------------
# SAFE SEND (безопасная отправка длинных сообщений)
# ------------------------------------------------------------------

async def safe_send(message: Message, text: str, chunk: int = 4000) -> None:
    """Безопасно отправляет текст, разбивая на части при необходимости.
    
    При ошибке парсинга HTML — отправляет как plain text.
    """
    try:
        if len(text) <= chunk:
            await message.answer(text, parse_mode=ParseMode.HTML)
            return
        parts = [text[i:i + chunk] for i in range(0, len(text), chunk)]
        for part in parts:
            await message.answer(part, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.3)
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "parse" in err or "tag" in err or "entity" in err:
            # Убираем HTML-теги и отправляем как plain text
            plain = text.replace("<b>", "").replace("</b>", "")
            plain = plain.replace("<i>", "").replace("</i>", "")
            plain = plain.replace("<code>", "").replace("</code>", "")
            plain = plain.replace("<pre>", "").replace("</pre>", "")
            plain = plain.replace("<a href=", "[").replace("</a>", "]")
            if len(plain) <= chunk:
                await message.answer(plain, parse_mode=None)
                return
            for part in [plain[i:i + chunk] for i in range(0, len(plain), chunk)]:
                await message.answer(part, parse_mode=None)
                await asyncio.sleep(0.3)
        else:
            raise


def parse_date_range(text: str) -> tuple:
    """Парсит диапазон дат из текста.
    
    Returns:
        (date_from, date_to) в формате "YYYY-MM-DD" или (None, None)
    """
    now = datetime.utcnow()
    text_lower = text.lower()
    if "сегодня" in text_lower:
        today = now.strftime("%Y-%m-%d")
        return today, today
    if "вчера" in text_lower:
        yest = (now - __import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")
        return yest, yest
    if "неделю" in text_lower or "за неделю" in text_lower:
        start = (now - __import__('datetime').timedelta(days=7)).strftime("%Y-%m-%d")
        return start, now.strftime("%Y-%m-%d")
    dates = re.findall(r"(\d{2})[.](\d{2})[.](\d{4})", text)
    if len(dates) >= 2:
        d1 = f"{dates[0][2]}-{dates[0][1]}-{dates[0][0]}"
        d2 = f"{dates[1][2]}-{dates[1][1]}-{dates[1][0]}"
        return d1, d2
    return None, None
