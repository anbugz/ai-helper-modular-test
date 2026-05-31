"""
services/ocr.py — Универсальное извлечение текста из файлов и изображений.

Поддерживает:
- PDF       → pdfplumber (текстовый) или PyPDF2 (fallback)
- DOCX      → python-docx
- XLSX/XLS  → openpyxl
- TXT       → напрямую
- JPG/PNG/WEBP/TIFF → DeepSeek Vision (base64)
- Сканы PDF → DeepSeek Vision (конвертация страниц в изображения)
"""

import os
import io
import base64
import asyncio
import logging
import tempfile

import httpx
from config import DEEPSEEK_API_KEY, logger

# ─── DeepSeek Vision ──────────────────────────────────────────────────────────

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
_TIMEOUT = httpx.Timeout(connect=10.0, read=90.0, write=10.0, pool=5.0)

VISION_PROMPT = """Извлеки весь текст с изображения дословно, сохраняя структуру.
Если это таблица — сохрани колонки через | (пайп).
Если текст на английском — оставь на английском.
Если текст на русском — оставь на русском.
Верни только текст, без комментариев."""


async def image_to_text(image_bytes: bytes, mime: str = "image/jpeg") -> str:
    """Отправляет изображение в DeepSeek Vision и возвращает извлечённый текст."""
    if not DEEPSEEK_API_KEY:
        return ""

    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "model": "deepseek-chat",
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"}
                },
                {
                    "type": "text",
                    "text": VISION_PROMPT
                }
            ]
        }],
        "temperature": 0,
        "max_tokens": 4000,
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        limits = httpx.Limits(max_keepalive_connections=0, max_connections=10)
        async with httpx.AsyncClient(timeout=_TIMEOUT, limits=limits) as client:
            resp = await client.post(DEEPSEEK_URL, json=payload, headers=headers)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"].get("content", "")
        else:
            logger.error(f"[OCR] DeepSeek Vision HTTP {resp.status_code}: {resp.text[:200]}")
            return ""
    except Exception as e:
        logger.error(f"[OCR] DeepSeek Vision error: {e}")
        return ""


# ─── Синхронные утилиты извлечения текста ────────────────────────────────────

def _extract_pdf_text(path: str) -> str:
    """Извлекает текст из PDF (только текстовые PDF, не сканы)."""
    text = ""
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
    except Exception:
        try:
            import PyPDF2
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() or ""
        except Exception as e:
            logger.error(f"[OCR] PDF text extract error: {e}")
    return text.strip()


def _extract_docx_text(path: str) -> str:
    """Извлекает текст из DOCX."""
    try:
        from docx import Document
        doc = Document(path)
        lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    lines.append(" | ".join(cells))
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[OCR] DOCX extract error: {e}")
        return ""


def _extract_xlsx_text(path: str) -> str:
    """Извлекает текст из XLSX/XLS."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        lines = []
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None and str(c).strip()]
                if cells:
                    lines.append(" | ".join(cells))
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[OCR] XLSX extract error: {e}")
        return ""


def _pdf_to_images(path: str) -> list[bytes]:
    """Конвертирует страницы PDF в изображения (для сканов)."""
    images = []
    try:
        import fitz  # pymupdf
        doc = fitz.open(path)
        for page in doc:
            pix = page.get_pixmap(dpi=150)
            images.append(pix.tobytes("jpeg"))
        doc.close()
    except ImportError:
        logger.warning("[OCR] pymupdf не установлен — сканы PDF не поддерживаются")
    except Exception as e:
        logger.error(f"[OCR] PDF to images error: {e}")
    return images


def _is_scanned_pdf(path: str) -> bool:
    """Проверяет является ли PDF сканом (нет извлекаемого текста)."""
    text = _extract_pdf_text(path)
    return len(text.strip()) < 50


# ─── Главная функция ──────────────────────────────────────────────────────────

async def extract_text(path: str) -> str:
    """
    Универсальное извлечение текста из файла.

    Порядок обработки:
    - .txt               → читаем напрямую
    - .docx              → python-docx
    - .xlsx/.xls         → openpyxl
    - .pdf (текстовый)   → pdfplumber
    - .pdf (скан)        → конвертируем в изображения → DeepSeek Vision
    - .jpg/.png/.webp    → DeepSeek Vision

    Возвращает извлечённый текст или пустую строку.
    """
    ext = os.path.splitext(path)[1].lower()

    # Текстовые форматы
    if ext == ".txt":
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            logger.error(f"[OCR] TXT read error: {e}")
            return ""

    if ext == ".docx":
        return await asyncio.to_thread(_extract_docx_text, path)

    if ext in (".xlsx", ".xls"):
        return await asyncio.to_thread(_extract_xlsx_text, path)

    # PDF
    if ext == ".pdf":
        text = await asyncio.to_thread(_extract_pdf_text, path)
        if len(text.strip()) >= 50:
            return text
        # Скан — пробуем Vision
        logger.info("[OCR] PDF кажется сканом — пробуем DeepSeek Vision")
        images = await asyncio.to_thread(_pdf_to_images, path)
        if not images:
            return text  # возвращаем что есть даже если мало
        # Берём первые 3 страницы чтобы не перегружать API
        texts = []
        for img_bytes in images[:3]:
            t = await image_to_text(img_bytes, "image/jpeg")
            if t:
                texts.append(t)
        return "\n\n".join(texts)

    # Изображения
    mime_map = {
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png":  "image/png",
        ".webp": "image/webp",
        ".tiff": "image/tiff",
        ".tif":  "image/tiff",
    }
    if ext in mime_map:
        with open(path, "rb") as f:
            image_bytes = f.read()
        return await image_to_text(image_bytes, mime_map[ext])

    logger.warning(f"[OCR] Неизвестный формат: {ext}")
    return ""


async def extract_text_bytes(file_bytes: bytes, ext: str) -> str:
    """Извлекает текст из байтов файла (без сохранения на диск для простых форматов)."""
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        return await extract_text(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
