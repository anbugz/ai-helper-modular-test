#!/usr/bin/env python3
"""
main.py — точка входа для WA AI Helper.
Модульная архитектура: handlers/, services/, utils/
"""
import sys
import os
import asyncio

# bothost: гарантируем что текущая папка в PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import logger, VERSION
from database import init_db
from bot_instance import dp, bot
from tnved_engine import restore_tnved_from_db

# Регистрация обработчиков из модульной структуры
from handlers.commands import register_commands
from handlers.admin import register_admin
# text, voice, documents регистрируются через импорт side-effect
import handlers.text   # noqa: F401
import handlers.voice  # noqa: F401
import handlers.documents  # noqa: F401


def register_all_handlers():
    """Регистрация всех обработчиков."""
    register_commands(dp)
    register_admin(dp)
    # text, voice, documents регистрируются при импорте через @dp.message


async def main() -> None:
    logger.info(f"Bot starting. Version: {VERSION}")
    init_db()
    logger.info("Database initialized.")
    restore_tnved_from_db()
    logger.info("TNVED cache restored from DB (if exists).")
    register_all_handlers()
    logger.info("All handlers registered.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
