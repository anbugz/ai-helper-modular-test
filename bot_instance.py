"""
bot_instance.py — инициализация aiogram Bot + Dispatcher.
"""
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN, logger

if not BOT_TOKEN:
    logger.critical("BOT_TOKEN не задан! Проверь .env")
    raise RuntimeError("BOT_TOKEN is required")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
