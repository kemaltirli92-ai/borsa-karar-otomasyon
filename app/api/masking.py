"""BLOK 16 - Musteri hata maskesi + yayinlanabilirlik filtresi.

- publishable(data): admin-only alanlari (internal_notes, raw_error, debug,
  pending_review, admin_* onekli) musteri cevabindan cikarir (recursive kopya).
- mask_exception(exc, scope): bilinmeyen hata musteriye 500 INTERNAL_ERROR +
  error_id olarak doner; stack trace, dosya yolu, SQL, kaynak URL ve ham
  exception mesaji ASLA musteriye gitmez. Admin scope'ta detail donulur ama
  secret/token degerleri *** ile maskelenir.
- ApiError: bilinen hata kodlari (SYMBOL_NOT_FOUND, INVALID_PARAMETER, ...)
  icin kontrollu, musteriye guvenli mesaj tasiyan istisna.

stdlib only; deterministik (error_id sayaci enjekte edilebilir).
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

# Musteriye asla gosterilmeyen alan adlari (SPEC bolum 5).
ADMIN_ONLY_FIELDS = ("internal_notes", "raw_error", "debug", "pending_review")
ADMIN_FIELD_PREFIX = "admin_"

SCOPE_CUSTOMER = "customer"
SCOPE_ADMIN = "admin"

# Bilinen hata kodlari.
CODE_INTERNAL = "INTERNAL_ERROR"
CODE_SYMBOL_NOT_FOUND = "SYMBOL_NOT_FOUND"
CODE_INVALID_PARAMETER = "INVALID_PARAMETER"
CODE_NOT_FOUND = "NOT_FOUND"
CODE_METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
CODE_RUN_NOT_FOUND = "RUN_NOT_FOUND"
CODE_RUN_MISMATCH = "RUN_MISMATCH"
CODE_ADMIN_TOKEN_MISSING = "ADMIN_TOKEN_MISSING"
CODE_ADMIN_TOKEN_INVALID = "ADMIN_TOKEN_INVALID"


class ApiError(Exception):
    """Bilinen, kontrollu hata: musteriye guvenli kod + mesaj tasir.

    Ham exception mesaji/stack ASLA musteriye donmez; yalnizca code,
    kontrollu message ve istege bagli alan adi (field) doner.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        field: Optional[str] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status = status
        self.field = field
        super().__init__(f"{code}: {message}")


# --- kontrollu hata yardimcilari -------------------------------------------

def symbol_not_found(symbol: str) -> ApiError:
    return ApiError(
        CODE_SYMBOL_NOT_FOUND,
        "Istenen sembol bulunamadi veya aktif evrende degil.",
        status=404,
        field="symbol",
    )


def run_not_found(run_id: str) -> ApiError:
    return ApiError(
        CODE_RUN_NOT_FOUND,
        "Istenen tarama kaydi bulunamadi.",
        status=404,
        field="run_id",
    )


def invalid_parameter(field: str, detail: str = "") -> ApiError:
    message = f"Gecersiz parametre: {field}"
    if detail:
        message += f" ({detail})"
    return ApiError(CODE_INVALID_PARAMETER, message, status=400, field=field)


def not_found() -> ApiError:
    return ApiError(CODE_NOT_FOUND, "Kaynak bulunamadi.", status=404)


def method_not_allowed() -> ApiError:
    return ApiError(
        CODE_METHOD_NOT_ALLOWED,
        "Bu yol icin izin verilmeyen method.",
        status=405,
    )


# --- yayinlanabilirlik filtresi ---------------------------------------------

def _is_admin_field(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    return key in ADMIN_ONLY_FIELDS or key.startswith(ADMIN_FIELD_PREFIX)


def publishable(data: Any) -> Any:
    """Admin-only alanlari cikarilmis derin kopya dondur (orijinal dokunulmaz).

    Ic ice dict/list yapilarinda da filtre uygulanir; musteri API'sinde
    internal_notes, raw_error, debug, pending_review ve admin_* alanlari
    asla gorunmez.
    """
    if isinstance(data, dict):
        cleaned: Dict[Any, Any] = {}
        for key, value in data.items():
            if _is_admin_field(key):
                continue
            cleaned[key] = publishable(value)
        return cleaned
    if isinstance(data, (list, tuple)):
        return [publishable(item) for item in data]
    return data


def find_admin_fields(data: Any, path: str = "") -> List[str]:
    """Test/denetim icin: verideki admin-only alan yollarini listele."""
    found: List[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            current = f"{path}.{key}" if path else str(key)
            if _is_admin_field(key):
                found.append(current)
            else:
                found.extend(find_admin_fields(value, current))
    elif isinstance(data, (list, tuple)):
        for index, item in enumerate(data):
            found.extend(find_admin_fields(item, f"{path}[{index}]"))
    return found


# --- error_id uretimi --------------------------------------------------------

class ErrorIdGenerator:
    """Deterministik artan hata kimligi sayaci (testlerde enjekte)."""

    def __init__(self, prefix: str = "ERR", start: int = 0) -> None:
        self.prefix = prefix
        self._counter = start

    def next(self) -> str:
        self._counter += 1
        return f"{self.prefix}-{self._counter:06d}"

    @property
    def current(self) -> str:
        return f"{self.prefix}-{self._counter:06d}"


_DEFAULT_IDS = ErrorIdGenerator()

# Secret benzeri degerleri maskeleyen desen (admin scope detail icin).
_SECRET_PATTERN = re.compile(
    r"(?i)\b(token|password|passwd|secret|api[_-]?key|authorization|x-admin-token)"
    r"(\s*[=:]\s*|\s+)(\S+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+\S+")


def mask_secrets(text: str) -> str:
    """Metindeki secret/token benzeri degerleri *** ile maskeler."""
    masked = _SECRET_PATTERN.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)
    masked = _BEARER_PATTERN.sub("Bearer ***", masked)
    return masked


def _resolve_error_id(error_ids: Optional[Any]) -> str:
    provider = error_ids if error_ids is not None else _DEFAULT_IDS
    if hasattr(provider, "next"):
        return str(provider.next())
    if callable(provider):
        return str(provider())
    return str(provider)


def _write_log(
    error_log: Optional[Callable[[Dict[str, Any]], None]],
    entry: Dict[str, Any],
) -> None:
    if error_log is None:
        return
    try:
        error_log(entry)
    except Exception:
        pass  # log yazimi hatasi cevabi engellemez


def mask_exception(
    exc: BaseException,
    scope: str = SCOPE_CUSTOMER,
    error_ids: Optional[Any] = None,
    error_log: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[int, Dict[str, Any]]:
    """Istisnayi (status, json_body) ciftine cevirir.

    - ApiError: kontrollu kod + mesaj (her iki scope icin guvenli).
    - Bilinmeyen hata + customer: 500 {"error": "INTERNAL_ERROR", "error_id"} —
      stack/yol/SQL/URL/ham mesaj YOK.
    - Bilinmeyen hata + admin: 500 + maskelenmis detail (secret *** ).
    - RunMismatchError dahili tutarsizliktir: musteriye 500 INTERNAL_ERROR,
      admine maskelenmis detail.
    """
    if isinstance(exc, ApiError):
        body: Dict[str, Any] = {"error": exc.code, "message": exc.message}
        if exc.field is not None:
            body["field"] = exc.field
        return exc.status, body

    error_id = _resolve_error_id(error_ids)
    _write_log(
        error_log,
        {
            "error_id": error_id,
            "scope": scope,
            "exception_type": type(exc).__name__,
            "exception_repr": repr(exc),
        },
    )

    if scope == SCOPE_ADMIN:
        return 500, {
            "error": CODE_INTERNAL,
            "error_id": error_id,
            "exception": type(exc).__name__,
            "detail": mask_secrets(str(exc)),
        }
    return 500, {"error": CODE_INTERNAL, "error_id": error_id}
