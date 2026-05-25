"""
services/stt.py — Deepgram API (speech-to-text).
Использует httpx.AsyncClient для неблокирующего I/O.
"""
import httpx
from typing import Optional
from config import DEEPGRAM_API_KEY, logger


async def speech_to_text(audio_path: str) -> Optional[str]:
    """
    Распознавание речи через Deepgram API (async).

    Args:
        audio_path: путь к аудио-файлу (.ogg, .mp3, .wav)

    Returns:
        Распознанный текст или None при ошибке
    """
    if not DEEPGRAM_API_KEY:
        logger.error("DEEPGRAM_API_KEY не задан в .env")
        return None
    try:
        with open(audio_path, "rb") as f:
            audio_data = f.read()

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.deepgram.com/v1/listen",
                headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
                params={
                    "language": "ru",
                    "punctuate": "true",
                    "model": "nova-2",
                },
                content=audio_data,
            )

        if response.status_code == 200:
            result = response.json()
            transcript = (
                result["results"]["channels"][0]["alternatives"][0]["transcript"]
            )
            text = transcript.strip()
            return text if text else None
        else:
            logger.error(f"Deepgram HTTP {response.status_code}: {response.text[:200]}")
            return None

    except Exception as e:
        logger.error(f"Deepgram ошибка: {e}")
        return None
