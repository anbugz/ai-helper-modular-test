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
        "<b>West Asia AI Helper</b> — внутренний ассистент для менеджеров по ВЭД.\n\n"
        "<b>Что умею:</b>\n\n"
        "📦 <b>Расчёт таможенных платежей</b>\n"
        "Пример: <code>6109100000 инвойс 15000ю фрахт 900дол вес 500кг</code>\n\n"
        "🔍 <b>Подбор кода ТН ВЭД</b>\n"
        "Пример: <code>подбери код для хлопковых футболок</code>\n\n"
        "📋 <b>Генерация договоров</b>\n"
        "Напиши <code>нужен договор</code> или <code>/contract</code> — выберу тип и заполню по карточке компании\n\n"
        "🚚 <b>Агенты и экспедиторы</b>\n"
        "Пример: <code>покажи агентов авиа</code>, <code>наши партнёры по морю</code>\n\n"
        "💱 <b>Конвертация валют</b>\n"
        "Пример: <code>переведи 10000 юаней в рубли</code>\n\n"
        "👤 <b>Декларанты</b>\n"
        "Пример: <code>кто наш декларант</code>\n\n"
        "🎤 <b>Голосовые сообщения</b> — распознаю и обработаю\n\n"
        "Если ответ неправильный — ответь на моё сообщение словом «несогласен».",
        parse_mode="HTML"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "<b>Справка:</b>\n\n"
        "<b>Расчёт ТП:</b> код + инвойс + фрахт + вес\n"
        "<code>6109100000 инвойс 15000ю фрахт 900дол вес 500кг</code>\n\n"
        "<b>Договора:</b> напиши «нужен договор» или /contract\n"
        "Поддерживаются: Аралия Трек и АЗИЯ ИМПОРТ × Поставка и ТЭО\n\n"
        "<b>Агенты:</b> агенты авиа / авто / жд / море\n\n"
        "<b>Валюты:</b> переведи 5000 долларов в рубли\n\n"
        "<b>Команды:</b>\n"
        "/contract — создать договор\n"
        "/start — главное меню\n"
        "/help — эта справка\n\n"
        "Ответь «несогласен» на сообщение бота — запишешь замечание.",
        parse_mode="HTML"
    )
