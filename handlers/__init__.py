"""
handlers/ — обработчики Telegram сообщений.

text, voice, documents регистрируются через side-effect импорта (@dp.message).
"""
from .commands import register_commands
from .admin import register_admin
# text, voice, documents импортируются в main.py для регистрации хэндлеров

__all__ = [
    "register_commands",
    "register_admin",
]
