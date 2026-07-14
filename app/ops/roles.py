"""BLOK 21 - Guvenlik, Log, Izleme ve Yedekleme: backend rol kontrolu.

Kurallar ozeti:
- stdlib only (json, secrets); gercek ag/subprocess YOK.
- masking.py DEGISTIRILMEZ: CODE_ROLE_FORBIDDEN bu modulde tanimlidir;
  ApiError app.api.masking'den aynen kullanilir.
- X-Admin-Token -> rol eslesmesi secrets.compare_digest ile yapilir;
  token DEGERI hicbir hata mesajinda yer almaz (mesajlar sabittir).
- Backend zorunlulugu: buton gizlemek yetmez; her yonetici cagrisi bu
  kontrolden gecer.
- Puan/bildirim kilidi suruyor: rol kontrolu puan/bildirim uretmez.
"""
from __future__ import annotations

import json
import secrets
from typing import Any, Dict, Optional

from app.api.auth import ADMIN_TOKEN_HEADER
from app.api.masking import (
    CODE_ADMIN_TOKEN_INVALID,
    CODE_ADMIN_TOKEN_MISSING,
    ApiError,
)

ROLE_ADMIN = "ADMIN"
ROLE_READONLY = "READONLY"

# Hiyerarsi: ADMIN, READONLY'yi kapsar.
ROLE_ORDER = {ROLE_READONLY: 1, ROLE_ADMIN: 2}

# YENI hata kodu — masking.py'ye DOKUNULMAZ, burada tanimlanir.
CODE_ROLE_FORBIDDEN = "ROLE_FORBIDDEN"

_HEADER_LOWER = ADMIN_TOKEN_HEADER.lower()


def _find_header(headers: Optional[Dict[str, Any]]) -> Optional[str]:
    """X-Admin-Token degerini buyuk/kucuk harf duyarsiz bul; bos = eksik."""
    if not headers:
        return None
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == _HEADER_LOWER:
            if value is None:
                return None
            value = str(value).strip()
            return value if value else None
    return None


class RoleAuth:
    """X-Admin-Token -> rol eslesmesi.

    token_roles_provider: callable() -> dict[str, str] /
    .get_token_roles() metodlu nesne / dict. Eslesme secrets.compare_digest
    ile yapilir; token degeri ASLA hata mesajina yazilmaz.
    """

    def __init__(self, token_roles_provider: Any, clock=None):
        self._provider = token_roles_provider
        self._clock = clock  # gelecekteki denetim kayitlari icin enjekte noktasi

    def token_roles(self) -> Dict[str, str]:
        """Saglayicidan {token: rol} sozlugunu coz; bulunamazsa {} (acik kapi yok)."""
        provider = self._provider
        value: Any = None
        if callable(provider):
            value = provider()
        elif hasattr(provider, "get_token_roles"):
            value = provider.get_token_roles()
        elif isinstance(provider, dict):
            value = provider
        if not isinstance(value, dict):
            return {}
        return {str(k): str(v) for k, v in value.items()}

    def role_for(self, headers: Optional[Dict[str, Any]]) -> str:
        """Token'in rolunu dondur; ihlalde ApiError firlat (token sizmaz)."""
        provided = _find_header(headers)
        if provided is None:
            raise ApiError(
                CODE_ADMIN_TOKEN_MISSING,
                "Yonetici erisimi icin kimlik dogrulama gerekli.",
                status=401,
            )
        for expected, role in self.token_roles().items():
            if expected and secrets.compare_digest(provided, expected):
                return role
        raise ApiError(
            CODE_ADMIN_TOKEN_INVALID,
            "Kimlik dogrulama basarisiz.",
            status=403,
        )

    def require(self, headers: Optional[Dict[str, Any]], required_role: str) -> str:
        """Rol yeterliligi zorla; yetersizse 403 ROLE_FORBIDDEN (token sizmaz)."""
        role = self.role_for(headers)
        have = ROLE_ORDER.get(role, 0)
        need = ROLE_ORDER.get(required_role, 99)
        if have < need:
            raise ApiError(
                CODE_ROLE_FORBIDDEN,
                "Bu islem %s yetkisi gerektirir." % required_role,
                status=403,
            )
        return role


def load_token_roles_from_env(environ: Dict[str, str]) -> Dict[str, str]:
    """Cevre degiskenlerinden {token: rol} sozlugu yukle.

    - ADMIN_ROLES_JSON gecerli JSON dict ise aynen kullanilir.
    - Bozuk/dict-olmayan JSON -> {} (guvenli taraf: hicbir token rol alamaz).
    - ADMIN_TOKEN doluysa ADMIN sayilir (JSON'da yoksa eklenir).
    """
    roles: Dict[str, str] = {}
    raw = environ.get("ADMIN_ROLES_JSON")
    if raw:
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        if not isinstance(parsed, dict):
            return {}
        for key, value in parsed.items():
            key_s, value_s = str(key), str(value)
            if key_s:
                roles[key_s] = value_s
    admin_token = environ.get("ADMIN_TOKEN")
    if admin_token:
        roles.setdefault(str(admin_token), ROLE_ADMIN)
    return roles
