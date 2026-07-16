"""
Нормализация серийных номеров сертификатов.

OpenVPN отдаёт `tls_serial_0` как decimal-строку (в 2.4+) или hex-строку (в старых
версиях, например с двоеточиями), а `cryptography.x509.serial_number` всегда даёт
`int`. Чтобы все источники приводились к одному виду, нормализуем к
**decimal-строке** — это совместимо с историческими данными, которые сохранялись
как `str(int)`.
"""

import re
from typing import Optional, Union

_HEX_CHARS = re.compile(r"[A-Fa-f]")


def normalize_serial(value: Optional[Union[int, str]]) -> str:
    """
    Возвращает каноническое представление серийного номера: десятичная строка.

    - int → str(int).
    - str с цифрами и буквами a-f / префиксом 0x / двоеточиями (hex) → int → str.
    - str только цифры → как есть (уже decimal).
    - 'unknown' / пустые / None → 'unknown'.
    - 'legacy_*' → возвращается без изменений.
    """
    if value is None:
        return "unknown"
    if isinstance(value, int):
        if value < 0:
            value = -value
        return str(value)

    text = str(value).strip()
    if not text or text.lower() == "unknown":
        return "unknown"
    if text.startswith("legacy_"):
        return text

    # Удаляем разделители-двоеточия (hex с разделителями: AA:BB:CC).
    if ":" in text:
        text = text.replace(":", "")

    if text.lower().startswith("0x"):
        try:
            return str(int(text, 16))
        except ValueError:
            return text.upper()

    # Только цифры — уже decimal, возвращаем как есть.
    if text.isdigit():
        return text

    # Содержит hex-литеры — парсим как hex.
    if _HEX_CHARS.search(text):
        try:
            return str(int(text, 16))
        except ValueError:
            return text.upper()

    # Прочие случаи возвращаем как есть.
    return text
