"""BLOK 21 - Guvenlik, Log, Izleme ve Yedekleme: gizli anahtar saglayici + redaksiyon.

Kurallar ozeti:
- stdlib only (os, re); gercek ag/subprocess YOK.
- Deterministik: cevre degiskenleri enjekte edilebilir (environ parametresi).
- Kaynak koda hicbir gercek gizli deger yazilmaz; testlerde sahte degerler.
- Iki katmanli redaksiyon: (a) SecretProvider.known_values() ile bilinen
  degerlerin metin icinde gectigi yerler "***", (b) SENSITIVE_KEY_RE ile
  eslesen mapping anahtarlarinin degerleri her zaman "***".
- Orijinal mapping ASLA degistirilmez (kopya dondurulur).
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

REDACTED = "***"

# Degeri her zaman maskelenecek anahtar adi deseni (buyuk/kucuk harf duyarsiz).
SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|sifre)", re.I
)


class SecretMissingError(Exception):
    """Zorunlu gizli anahtar eksik/bos; .name niteligi eksik anahtar adini tasir."""

    def __init__(self, name: str):
        self.name = name
        super().__init__("Gizli anahtar eksik: %s" % name)


class SecretProvider:
    """Cevre degiskenlerinden gizli anahtar okuyucu.

    environ enjekte edilebilir (testte dict); default os.environ.
    Bos string degerler "eksik" sayilir.
    """

    def __init__(self, environ: Optional[Dict[str, str]] = None):
        self._environ: Dict[str, str] = dict(os.environ if environ is None else environ)

    def get(
        self,
        name: str,
        required: bool = True,
        default: Optional[str] = None,
    ) -> Optional[str]:
        """Anahtari oku; bos string eksik sayilir.

        required=True ve deger eksikse SecretMissingError firlatir;
        required=False ise eksikte default doner.
        """
        value = self._environ.get(name)
        if value is not None:
            value = str(value)
            if value == "":
                value = None
        if value is None:
            if required:
                raise SecretMissingError(name)
            return default
        return value

    def require_all(self, names: List[str]) -> Dict[str, str]:
        """Tum anahtarlari zorunlu oku; ilk eksikte SecretMissingError."""
        result: Dict[str, str] = {}
        for name in names:
            result[name] = self.get(name, required=True)  # type: ignore[assignment]
        return result

    def known_values(self) -> List[str]:
        """Bos olmayan TUM degerlerin kopyasi (redaksiyon icin)."""
        return [str(v) for v in self._environ.values() if v is not None and str(v) != ""]


def redact_text(
    text: str,
    secret_values: List[str],
    min_len: int = 4,
) -> str:
    """Metinde bilinen gizli degerlerin gectigi her yere "***" koyar.

    Deger uzunlugu < min_len ise redaksiyon uygulanmaz (kisa/genel degerler
    metni bozmasin). Gizli deger donuste ASLA yer almaz.
    """
    if not isinstance(text, str):
        return text
    redacted = text
    for value in secret_values or []:
        if not isinstance(value, str) or len(value) < min_len:
            continue
        redacted = redacted.replace(value, REDACTED)
    return redacted


def redact_mapping(
    data: dict,
    secret_values: List[str],
    min_len: int = 4,
) -> dict:
    """Mapping'i derin kopyalayip redakte eder; orijinal DEGISTIRILMEZ.

    - Anahtari SENSITIVE_KEY_RE ile eslesen her deger -> "***" (deger ne
      olursa olsun; ic ice yapilarda da).
    - Diger string degerler redact_text'ten gecer (min_len esigi ile).
    - Ic ice dict/list desteklenir.
    """
    return _redact_value(data, secret_values, min_len=min_len)


def _redact_value(
    value,
    secret_values: List[str],
    min_len: int = 4,
    key_sensitive: bool = False,
):
    if key_sensitive:
        # Anahtar adi hassas ise deger ne olursa olsun maskelenir.
        return REDACTED
    if isinstance(value, dict):
        cleaned: Dict[object, object] = {}
        for key, sub in value.items():
            sensitive = isinstance(key, str) and bool(SENSITIVE_KEY_RE.search(key))
            cleaned[key] = _redact_value(
                sub, secret_values, min_len=min_len, key_sensitive=sensitive
            )
        return cleaned
    if isinstance(value, (list, tuple)):
        return [
            _redact_value(item, secret_values, min_len=min_len, key_sensitive=False)
            for item in value
        ]
    if isinstance(value, str):
        return redact_text(value, secret_values, min_len=min_len)
    return value
