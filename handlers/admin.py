"""
handlers/admin.py — административные команды.
TODO: перенести из старого handlers.py
"""
from aiogram import types
from aiogram.types import Message
from aiogram.filters import Command
from bot_instance import dp
from config import ADMIN_ID, VERSION, logger
from services.security import unblock_user

async def register_admin(dp):
    """Регистрация админских команд."""
    pass  # TODO: перенести /brief, /topics, /learn, /done, /updatecodes, /unblock

@dp.message(Command("unblock"))
async def cmd_unblock(message: Message):
    """Разблокировать пользователя: /unblock 123456789"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    
    args = message.text.replace("/unblock", "").strip()
    if not args.isdigit():
        await message.answer("Использование: /unblock <user_id>")
        return
    
    uid = int(args)
    if unblock_user(uid):
        await message.answer(f"✅ Пользователь <code>{uid}</code> разблокирован.")
    else:
        await message.answer(f"ℹ️ Пользователь <code>{uid}</code> не был заблокирован.")
