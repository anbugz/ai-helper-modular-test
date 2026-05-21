"""
handlers/commands.py — базовые команды /start, /help.
/clear УБРАН по требованию брифа.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "<b>West Asia AI Helper</b> — помощник для менеджеров по ВЭД и логистике.\n\n"
        "Просто напиши вопрос — помогу с расчётами, сроками, маршрутами.\n\n"
        "Если ответ неправильный — ответь на моё сообщение словом «несогласен»."
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "<b>Справка:</b>\n"
        "• Отправь текст с кодом ТН ВЭД — получишь расчёт.\n"
        "• Отправь .xlsx файл — извлеку данные.\n"
        "• Отправь голосовое сообщение — распознаю и обработаю.\n"
        "• Ответь «несогласен» на сообщение бота — запишешь замечание.\n"
        "• /help — эта справка."
    )
