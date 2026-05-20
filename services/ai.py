"""
services/ai.py — интеграция с DeepSeek API.
"""
import os
import logging
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

SYSTEM_PROMPT = (
    "Ты — эксперт по ВЭД и логистике. Помогаешь менеджерам компании West Asia. "
    "Отвечай кратко, по делу, с примерами. Используй таблицы где уместно."
)

async def ask_deepseek(user_text: str, include_history: bool = False) -> str:
    """
    Запрос к DeepSeek API.
    
    Args:
        user_text: текст запроса пользователя
        include_history: включать ли историю диалога
    
    Returns:
        Ответ от AI
    """
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY не задан")
        return "❌ Ошибка: API ключ не настроен."
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.append({"role": "user", "content": user_text})
    
    try:
        resp = await client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.3,
            max_tokens=1500,
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek ошибка: {e}")
        return f"❌ Ошибка AI: {e}"
