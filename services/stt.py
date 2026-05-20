"""
services/stt.py — Speech-to-Text через Deepgram API.
"""
import os
import logging
import httpx

logger = logging.getLogger(__name__)

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")

async def speech_to_text(audio_path: str) -> str:
    """
    Распознавание речи через Deepgram API (~2-3 сек).
    
    Args:
        audio_path: путь к аудио-файлу (.ogg, .mp3, .wav)
    
    Returns:
        Распознанный текст или пустая строка при ошибке
    """
    if not DEEPGRAM_API_KEY:
        logger.error("DEEPGRAM_API_KEY не задан")
        return ""
    
    try:
        with open(audio_path, "rb") as f:
            response = httpx.post(
                "https://api.deepgram.com/v1/listen",
                headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
                params={
                    "language": "ru",
                    "punctuate": "true",
                    "model": "nova-2",
                },
                content=f.read(),
                timeout=15.0,
            )
        
        if response.status_code == 200:
            result = response.json()
            transcript = result["results"]["channels"][0]["alternatives"][0]["transcript"]
            return transcript.strip()
        else:
            logger.error(f"Deepgram HTTP {response.status_code}: {response.text[:200]}")
            return ""
    except Exception as e:
        logger.error(f"Deepgram ошибка: {e}")
        return ""
