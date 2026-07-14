"""BLOK 16 - Yonetici kimlik dogrulama (AdminAuth).

- Header `X-Admin-Token` ZORUNLU (buyuk/kucuk harf duyarsiz aranir).
- Eksik/bos token -> 401 ADMIN_TOKEN_MISSING.
- Yanlis token -> 403 ADMIN_TOKEN_INVALID.
- Token DEGERI hata yaniitinda ASLA yer almaz; mesajlar sabittir.
- Beklenen token enjekte token_provider'dan okunur (ornegin env); kod
  icinde sabit token YOK. Karsilastirma secrets.compare_digest ile yapilir.
- Musteri uclarinda auth uygulanmaz (yayinlanabilirlik filtresi uygulanir).

stdlib only; deterministik; gercek ag YOK.
"""
from __future__ import annotations

import secrets
from typing import Any, Callable, Dict, Optional, Union

from app.api.masking import (
    CODE_ADMIN_TOKEN_INVALID,
    CODE_ADMIN_TOKEN_MISSING,
    ApiError,
)

ADMIN_TOKEN_HEADER = "X-Admin-Token"
_HEADER_LOWER = ADMIN_TOKEN_HEADER.lower()


def _find_header(headers: Optional[Dict[str, Any]], name_lower: str) -> Optional[str]:
    """Header degerini buyuk/kucuk harf duyarsiz bul."""
    if not headers:
        return None
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == name_lower:
            if value is None:
                return None
            return str(value)
    return None


class AdminAuth:
    """X-Admin-Token dogrulayici.

    token_provider enjekte: callable() -> str, .get_admin_token() metodlu
    nesne ya da {"admin_token": ...} dict. Hicbiri token bulamazsa tum
    istekler 403 ile reddedilir (acik kapi yok).
    """

    def __init__(self, token_provider: Any) -> None:
        self.token_provider = token_provider

    def expected_token(self) -> Optional[str]:
        """Beklenen token'i saglayicidan oku (yoksa None)."""
        provider = self.token_provider
        value: Any = None
        if callable(provider):
            value = provider()
        elif hasattr(provider, "get_admin_token"):
            value = provider.get_admin_token()
        elif isinstance(provider, dict):
            value = provider.get("admin_token")
        elif isinstance(provider, str):
            value = provider or None
        if value is None:
            return None
        value = str(value)
        return value if value else None

    def extract_token(self, headers: Optional[Dict[str, Any]]) -> Optional[str]:
        """Istek basligindan token'i cikar; bos string eksik sayilir."""
        token = _find_header(headers, _HEADER_LOWER)
        if token is None:
            return None
        token = token.strip()
        return token if token else None

    def authenticate(self, headers: Optional[Dict[str, Any]]) -> None:
        """Token'i dogrula; ihlalde ApiError firlat (token degeri sizmaz)."""
        provided = self.extract_token(headers)
        if provided is None:
            raise ApiError(
                CODE_ADMIN_TOKEN_MISSING,
                "Yonetici erisimi icin kimlik dogrulama gerekli.",
                status=401,
            )
        expected = self.expected_token()
        if expected is None or not secrets.compare_digest(provided, expected):
            raise ApiError(
                CODE_ADMIN_TOKEN_INVALID,
                "Kimlik dogrulama basarisiz.",
                status=403,
            )
