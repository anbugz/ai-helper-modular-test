"""
bot_instance.py — инициализация aiogram Bot + Dispatcher.
"""
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from config import BOT_TOKEN, logger

if not BOT_TOKEN:
    logger.critical("BOT_TOKEN не задан! Проверь .env")
    raise RuntimeError("BOT_TOKEN is required")

# Увеличиваем timeout для стабильности на VDS
session = AiohttpSession(timeout=120)
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()
