"""
Тесты core.serial.normalize_serial — канон серийника: decimal-строка.

Дубли accounts возникают, если один и тот же сертификат приходит в разных
представлениях (OpenVPN — decimal, cryptography — int, старые данные — hex),
а нормализация даёт разные строки.
"""

from core.serial import normalize_serial


class TestNormalizeSerial:

    def test_int(self):
        assert normalize_serial(74565) == "74565"

    def test_decimal_string_as_is(self):
        assert normalize_serial("74565") == "74565"

    def test_hex_with_letters(self):
        assert normalize_serial("1a2b") == str(0x1A2B)

    def test_hex_with_prefix(self):
        assert normalize_serial("0x012345") == "74565"

    def test_hex_with_colons(self):
        assert normalize_serial("AA:BB:CC") == str(0xAABBCC)

    def test_hex_with_colons_digits_only(self):
        """
        Регрессия: hex из одних цифр с двоеточиями (01:23:45) раньше после
        удаления разделителей проходил isdigit() и сохранялся как decimal
        "012345" — дубль account для того же сертификата.
        """
        assert normalize_serial("01:23:45") == str(0x012345)
        assert normalize_serial("01:23:45") == normalize_serial(0x012345)

    def test_unknown_and_empty(self):
        assert normalize_serial(None) == "unknown"
        assert normalize_serial("") == "unknown"
        assert normalize_serial("UNKNOWN") == "unknown"

    def test_legacy_untouched(self):
        assert normalize_serial("legacy_42") == "legacy_42"
