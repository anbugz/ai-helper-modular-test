"""
handlers/commands.py — базовые команды бота (/start, /help, /clear)
"""
from aiogram import types
from aiogram.types import Message
from config import VERSION
from database import get_dialog_history
from bot_instance import bot
import logging

logger = logging.getLogger(__name__)

START_MSG = (
    "👋 <b>Привет! Я WA AI Helper</b> — ваш ассистент по ВЭД и логистике.\n\n"
    "📋 <b>Что я умею:</b>\n"
    "• Подбирать код ТН ВЭД по описанию товара\n"
    "• Считать таможенные платежи (пошлина, НДС, сбор)\n"
    "• Отвечать на вопросы по ВЭД и логистике\n"
    "• Распознавать голосовые сообщения\n"
    "• Работать с курсами ЦБ РФ (USD, EUR, CNY)\n\n"
    "💡 <b>Примеры запросов:</b>\n"
    '<code>5208 43 000 0 10000 USD</code> — расчёт по коду\n'
    '<code>хлопковая ткань</code> — подбор кода\n'
    '<code>FOB Shanghai инвойс 5000 EUR</code> — с фрахтом\n\n'
    f"📌 <b>Версия:</b> <code>{VERSION}</code>\n"
    "📖 /help — справка по командам"
)

HELP_MSG = (
    "<b>📖 Справка</b>\n\n"
    "<b>🔢 Расчёт таможенных платежей:</b>\n"
    '<code>5208 43 000 0 10000 USD</code> — код + сумма\n'
    '<code>6109 10 000 0 5000 EUR вес 100 кг</code> — с весом\n'
    '<code>9405 42 0033 108 USD фрахт 79 000 руб</code> — с фрахтом\n\n'
    "<b>🔍 Подбор кода ТН ВЭД:</b>\n"
    '<code>хлопковая ткань</code>\n'
    '<code>vatnye volokna</code> (транслит)\n\n'
    "<b>🎤 Голосовые сообщения</b> — отправь голосовое с запросом\n\n"
    "<b>🧹 /clear</b> — очистить чат (визуально)\n"
)

async def register_commands(dp):
    """Регистрация базовых команд."""
    
    @dp.message(commands=["start"])
    async def cmd_start(message: Message):
        await message.answer(START_MSG)
    
    @dp.message(commands=["help"])
    async def cmd_help(message: Message):
        await message.answer(HELP_MSG)
    
    @dp.message(commands=["clear"])
    async def cmd_clear(message: Message):
        await message.answer("═══════════ 🧹 ИСТОРИЯ ЧАТА ОЧИЩЕНА ═══════════")
