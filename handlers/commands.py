"""
handlers/commands.py — базовые команды /start, /help, /status.
/clear УБРАН по требованию брифа.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "<b>West Asia AI Helper</b> — помощник для менеджеров по ВЭД и логистике.

"
        "Просто напиши вопрос — помогу с расчётами, сроками, маршрутами.

"
        "Если ответ неправильный — ответь на моё сообщение словом «несогласен»."
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "<b>Справка:</b>
"
        "• Отправь текст с кодом ТН ВЭД — получишь расчёт.
"
        "• Отправь .xlsx файл — извлеку данные.
"
        "• Отправь голосовое сообщение — распознаю и обработаю.
"
        "• Ответь «несогласен» на сообщение бота — запишешь замечание.
"
        "• /help — эта справка."
    )


@router.message(Command("status"))
async def cmd_status(message: Message):
    from services.currency import get_cbr_rates
    rates = await get_cbr_rates()
    cny = rates.get("CNY", "н/д")
    usd = rates.get("USD", "н/д")
    eur = rates.get("EUR", "н/д")
    date = rates.get("DATE", "сегодня")
    await message.answer(
        f"💱 <b>Курс ЦБ РФ на {date}:</b>
"
        f"1 USD = {usd} ₽
"
        f"1 CNY = {cny} ₽
"
        f"1 EUR = {eur} ₽"
    )
