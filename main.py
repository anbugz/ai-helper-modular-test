"""
main.py — точка входа для модульного бота WA AI Helper.
Регистрирует все хэндлеры и запускает polling.
"""
import asyncio
import sys
import os

# Добавляем директорию проекта в путь (для импортов)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot_instance import bot, dp
from config import logger, VERSION
from database import init_db
from services.tnved import restore_tnved_from_db


async def main():
    logger.info(f"=== West Asia AI Helper v{VERSION} (modular) ===")
    
    # Инициализация БД
    init_db()
    
    # Восстановление кэша ТН ВЭД из БД
    restore_tnved_from_db()
    
    # Регистрация хэндлеров
    from handlers import commands, admin, documents, voice, text, contracts, amo

    dp.include_router(commands.router)
    dp.include_router(admin.router)
    dp.include_router(contracts.router)   # ← договоры (до text!)
    dp.include_router(amo.router)         # ← AmoCRM команды
    dp.include_router(documents.router)
    dp.include_router(voice.router)
    dp.include_router(text.router)
    
    logger.info("Хэндлеры зарегистрированы. Запуск polling...")
    
    # Запуск бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
