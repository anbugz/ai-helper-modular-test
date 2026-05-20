"""
handlers/ — обработчики Telegram сообщений.
"""
from .commands import register_commands
from .text import register_text
from .voice import register_voice
from .documents import register_documents
from .admin import register_admin

__all__ = [
    "register_commands",
    "register_text", 
    "register_voice",
    "register_documents",
    "register_admin",
]
