"""
services/ai.py — DeepSeek API wrapper.
"""
import openai
from typing import List, Dict
from config import DEEPSEEK_API_KEY, logger


async def ask_deepseek(messages: List[Dict]) -> str:
    """Отправляет список сообщений в DeepSeek API, возвращает текст ответа."""
    if not DEEPSEEK_API_KEY:
        return "⚠️ DEEPSEEK_API_KEY не задан в .env"
    client = openai.AsyncOpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com/v1",
    )
    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.2,
            max_tokens=1500,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"DeepSeek API error: {e}")
        return f"⚠️ Ошибка при обращении к AI: {e}"


def build_messages(user_id: int, user_text: str, extra_context: str = "", include_history: bool = True) -> List[Dict]:
    """Строит список сообщений для DeepSeek API.
    
    Args:
        user_id: ID пользователя для получения истории
        user_text: Текст текущего запроса
        extra_context: Дополнительный системный контекст
        include_history: Включать ли историю диалога
    """
    from config import SYSTEM_PROMPT, MAX_HISTORY
    from database import get_dialog_history
    
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    if extra_context:
        msgs.append({"role": "system", "content": extra_context})
    if include_history:
        history = get_dialog_history(user_id, limit=MAX_HISTORY)
        for h in history:
            msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": user_text})
    return msgs
