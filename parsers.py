"""
parsers.py — парсинг файлов .xlsx, .docx, .txt и кодов ТН ВЭД.
Базовая реализация без внешних зависимостей (openpyxl не требуется).
"""
import re
import io
from typing import List, Optional
from config import logger


def parse_xlsx(file_obj) -> List[List[str]]:
    """Парсит .xlsx файл через zip + xml (без openpyxl).
    
    Args:
        file_obj: BytesIO или путь к файлу
    
    Returns:
        Список строк, каждая строка — список ячеек
    """
    import zipfile
    import xml.etree.ElementTree as ET
    
    if hasattr(file_obj, 'read'):
        file_bytes = file_obj.read()
    else:
        with open(file_obj, 'rb') as f:
            file_bytes = f.read()
    
    try:
        z = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile:
        logger.error("Файл не является валидным .xlsx (BadZipFile)")
        return []
    
    # Получаем shared strings
    shared_strings = []
    try:
        ss_xml = z.read("xl/sharedStrings.xml")
        root = ET.fromstring(ss_xml)
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        for si in root.findall(f"{{{ns}}}si"):
            t_elem = si.find(f"{{{ns}}}t")
            if t_elem is not None and t_elem.text:
                shared_strings.append(t_elem.text)
            else:
                # Обработка rich text
                r_elems = si.findall(f"{{{ns}}}r")
                text_parts = []
                for r in r_elems:
                    t = r.find(f"{{{ns}}}t")
                    if t is not None and t.text:
                        text_parts.append(t.text)
                shared_strings.append("".join(text_parts))
    except KeyError:
        pass  # Нет shared strings
    
    # Парсим ВСЕ листы (sheet1.xml, sheet2.xml, ...)
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    
    def _parse_sheet(sheet_name):
        """Парсит один лист и возвращает список строк."""
        try:
            sheet_xml = z.read(f"xl/worksheets/{sheet_name}")
        except KeyError:
            return []
        root = ET.fromstring(sheet_xml)
        sheet_rows = []
        for row_elem in root.findall(f".//{{{ns}}}row"):
            row_data = []
            for cell in row_elem.findall(f"{{{ns}}}c"):
                cell_type = cell.get("t", "")
                v_elem = cell.find(f"{{{ns}}}v")
                if v_elem is not None and v_elem.text:
                    if cell_type == "s":
                        try:
                            idx = int(v_elem.text)
                            row_data.append(shared_strings[idx] if idx < len(shared_strings) else "")
                        except (ValueError, IndexError):
                            row_data.append(v_elem.text)
                    else:
                        row_data.append(v_elem.text)
                else:
                    row_data.append("")
            if any(cell.strip() for cell in row_data):
                sheet_rows.append(row_data)
        return sheet_rows
    
    # Находим все sheet*.xml файлы
    all_rows = []
    sheet_files = sorted([n for n in z.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")])
    logger.info(f"XLSX sheets found: {sheet_files}")
    
    for sheet_file in sheet_files:
        sheet_name = sheet_file.split("/")[-1]
        sheet_rows = _parse_sheet(sheet_name)
        logger.info(f"  {sheet_name}: {len(sheet_rows)} rows")
        all_rows.extend(sheet_rows)
    
    z.close()
    return all_rows


def parse_txt(file_obj) -> str:
    """Парсит .txt файл."""
    if hasattr(file_obj, 'read'):
        content = file_obj.read()
        if isinstance(content, bytes):
            return content.decode('utf-8', errors='replace')
        return content
    with open(file_obj, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()


def parse_docx(file_obj) -> str:
    """Парсит .docx файл (извлекает текст)."""
    import zipfile
    import xml.etree.ElementTree as ET
    
    if hasattr(file_obj, 'read'):
        file_bytes = file_obj.read()
    else:
        with open(file_obj, 'rb') as f:
            file_bytes = f.read()
    
    try:
        z = zipfile.ZipFile(io.BytesIO(file_bytes))
        xml_content = z.read("word/document.xml")
        z.close()
    except (zipfile.BadZipFile, KeyError):
        return ""
    
    root = ET.fromstring(xml_content)
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    
    paragraphs = []
    for p in root.findall(f".//{{{ns}}}p"):
        texts = []
        for t in p.findall(f".//{{{ns}}}t"):
            if t.text:
                texts.append(t.text)
        if texts:
            paragraphs.append("".join(texts))
    
    return "\n".join(paragraphs)


def _extract_codes_from_rows(rows: List[List[str]]) -> List[str]:
    """Извлекает 10-значные коды радиоэлектроники из строк .xlsx.
    
    Returns:
        Список уникальных кодов
    """
    codes = set()
    for row in rows:
        for cell in row:
            if isinstance(cell, str):
                # Ищем 10-значные коды
                found = re.findall(r'\d{10}', cell.replace(" ", ""))
                codes.update(found)
    return sorted(list(codes))
