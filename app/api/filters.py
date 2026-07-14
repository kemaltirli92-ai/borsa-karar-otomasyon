"""BLOK 16 - Liste parametreleri: parse + dogrulama + sayfalama/siralama motoru.

12 parametre (SPEC bolum 8):
  page (>=1, vars.1), page_size (1-200, vars.50), search (kelime sinirli),
  sector, scan_status (ScanState degerleri), minimum_confidence (0-100),
  has_kap / has_news / has_action / has_restriction (true/false),
  sort_by (symbol|confidence|scan_status|sector|last_updated),
  sort_direction (asc|desc).

Gecersiz parametre -> ApiError 400 INVALID_PARAMETER + alan adi
(ham exception mesaji MUSTERIYE GITMEZ).

Run tutarliligi: apply_filters listeyi TEK run_id'ye hizalar — farkli
run'lu kayit gelirse en son run'a hizalanir; strict=True ise
RunMismatchError (RUN_MISMATCH) firlatilir.

stdlib only; deterministik; gercek ag YOK.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.api.envelope import RunMismatchError
from app.api.masking import ApiError, invalid_parameter

PARAMETER_NAMES = (
    "page",
    "page_size",
    "search",
    "sector",
    "scan_status",
    "minimum_confidence",
    "has_kap",
    "has_news",
    "has_action",
    "has_restriction",
    "sort_by",
    "sort_direction",
)

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
SEARCH_MAX_WORDS = 5
SEARCH_MAX_LENGTH = 64

SORT_FIELDS = ("symbol", "confidence", "scan_status", "sector", "last_updated")
SORT_DIRECTIONS = ("asc", "desc")
DEFAULT_SORT_BY = "symbol"
DEFAULT_SORT_DIRECTION = "asc"

# ScanState degerleri (BLOK 14; enjeksiyonla degistirilebilir).
DEFAULT_SCAN_STATES = (
    "WAITING",
    "COLLECTING_PRICE",
    "COLLECTING_KAP",
    "COLLECTING_NEWS",
    "COLLECTING_ACTIONS",
    "COLLECTING_RESTRICTIONS",
    "VALIDATING",
    "READY",
    "PARTIAL_DATA",
    "FAILED",
    "INACTIVE",
)

_TRUE_VALUES = ("true",)
_FALSE_VALUES = ("false",)


@dataclass(frozen=True)
class FilterParams:
    """Dogrulanmis 12 liste parametresi."""

    page: int = DEFAULT_PAGE
    page_size: int = DEFAULT_PAGE_SIZE
    search: Optional[str] = None
    sector: Optional[str] = None
    scan_status: Optional[str] = None
    minimum_confidence: Optional[float] = None
    has_kap: Optional[bool] = None
    has_news: Optional[bool] = None
    has_action: Optional[bool] = None
    has_restriction: Optional[bool] = None
    sort_by: str = DEFAULT_SORT_BY
    sort_direction: str = DEFAULT_SORT_DIRECTION


def _raw(query: Dict[str, Any], name: str) -> Optional[str]:
    value = query.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text if text != "" else None


def _parse_int(query: Dict[str, Any], name: str, default: int) -> int:
    text = _raw(query, name)
    if text is None:
        return default
    try:
        return int(text)
    except (TypeError, ValueError):
        raise invalid_parameter(name, "tamsayi olmali")


def _parse_float(query: Dict[str, Any], name: str) -> Optional[float]:
    text = _raw(query, name)
    if text is None:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        raise invalid_parameter(name, "sayisal olmali")


def _parse_bool(query: Dict[str, Any], name: str) -> Optional[bool]:
    text = _raw(query, name)
    if text is None:
        return None
    lowered = text.lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    raise invalid_parameter(name, "true/false olmali")


def parse_params(
    query: Optional[Dict[str, Any]],
    valid_scan_states: Optional[Sequence[str]] = None,
) -> FilterParams:
    """Query dict'ini dogrulanmis FilterParams'a cevirir.

    Gecersiz deger -> ApiError(400, INVALID_PARAMETER, field=<param>).
    """
    query = dict(query or {})
    states = tuple(valid_scan_states) if valid_scan_states else DEFAULT_SCAN_STATES

    page = _parse_int(query, "page", DEFAULT_PAGE)
    if page < 1:
        raise invalid_parameter("page", "1 veya daha buyuk olmali")

    page_size = _parse_int(query, "page_size", DEFAULT_PAGE_SIZE)
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise invalid_parameter("page_size", f"1-{MAX_PAGE_SIZE} arasi olmali")

    search = _raw(query, "search")
    if search is not None:
        if len(search) > SEARCH_MAX_LENGTH:
            raise invalid_parameter("search", f"en fazla {SEARCH_MAX_LENGTH} karakter")
        if len(search.split()) > SEARCH_MAX_WORDS:
            raise invalid_parameter("search", f"en fazla {SEARCH_MAX_WORDS} kelime")

    sector = _raw(query, "sector")

    scan_status = _raw(query, "scan_status")
    if scan_status is not None and scan_status.upper() not in states:
        raise invalid_parameter(
            "scan_status", "gecerli durum: " + ", ".join(states)
        )
    if scan_status is not None:
        scan_status = scan_status.upper()

    minimum_confidence = _parse_float(query, "minimum_confidence")
    if minimum_confidence is not None and not (0.0 <= minimum_confidence <= 100.0):
        raise invalid_parameter("minimum_confidence", "0-100 arasi olmali")

    sort_by = _raw(query, "sort_by") or DEFAULT_SORT_BY
    if sort_by not in SORT_FIELDS:
        raise invalid_parameter("sort_by", "gecerli alan: " + ", ".join(SORT_FIELDS))

    sort_direction = (_raw(query, "sort_direction") or DEFAULT_SORT_DIRECTION).lower()
    if sort_direction not in SORT_DIRECTIONS:
        raise invalid_parameter("sort_direction", "asc/desc olmali")

    return FilterParams(
        page=page,
        page_size=page_size,
        search=search,
        sector=sector,
        scan_status=scan_status,
        minimum_confidence=minimum_confidence,
        has_kap=_parse_bool(query, "has_kap"),
        has_news=_parse_bool(query, "has_news"),
        has_action=_parse_bool(query, "has_action"),
        has_restriction=_parse_bool(query, "has_restriction"),
        sort_by=sort_by,
        sort_direction=sort_direction,
    )


# --- run tutarliligi ---------------------------------------------------------

_RUN_FIELDS = ("scan_run_id", "run_id")


def item_run_id(item: Any) -> Optional[str]:
    if not isinstance(item, dict):
        return None
    for name in _RUN_FIELDS:
        value = item.get(name)
        if value is not None:
            return str(value)
    return None


def align_run(items: List[Any], strict: bool = False) -> List[Any]:
    """Listeyi TEK run_id'ye hizala.

    - Tum kalemler ayni run'daysa degismez.
    - Farkli run'lu kalemler varsa: strict -> RunMismatchError; aksi halde
      en son (en buyuk) run_id'ye ait kalemler korunur.
    """
    run_ids = [item_run_id(item) for item in items]
    known = {rid for rid in run_ids if rid is not None}
    if len(known) <= 1:
        return list(items)
    latest = max(known)
    if strict:
        for rid in known:
            if rid != latest:
                raise RunMismatchError(latest, rid)
    return [
        item
        for item, rid in zip(items, run_ids)
        if rid is None or rid == latest
    ]


# --- filtreleme --------------------------------------------------------------

_FLAG_SOURCES = {
    "has_kap": ("kap_count", "kap"),
    "has_news": ("news_count", "news"),
    "has_action": ("action_count", "corporate_actions", "actions"),
    "has_restriction": ("restriction_count", "restrictions"),
}


def _flag_value(item: Dict[str, Any], flag: str) -> bool:
    if flag in item and item[flag] is not None:
        return bool(item[flag])
    for source in _FLAG_SOURCES.get(flag, ()):
        value = item.get(source)
        if value is not None:
            return bool(value)
    return False


def _matches(item: Dict[str, Any], params: FilterParams) -> bool:
    if not isinstance(item, dict):
        return False
    if params.search is not None:
        needle = params.search.lower()
        haystacks = [
            str(item.get("symbol") or ""),
            str(item.get("name") or ""),
            str(item.get("title") or ""),
            str(item.get("unvan") or ""),
        ]
        if not any(needle in text.lower() for text in haystacks):
            return False
    if params.sector is not None:
        sector = item.get("sector")
        if sector is None or str(sector).lower() != params.sector.lower():
            return False
    if params.scan_status is not None:
        status = item.get("scan_status")
        if status is None or str(status).upper() != params.scan_status:
            return False
    if params.minimum_confidence is not None:
        confidence = item.get("confidence")
        if confidence is None:
            return False
        try:
            if float(confidence) < params.minimum_confidence:
                return False
        except (TypeError, ValueError):
            return False
    for flag in ("has_kap", "has_news", "has_action", "has_restriction"):
        wanted = getattr(params, flag)
        if wanted is not None and _flag_value(item, flag) is not wanted:
            return False
    return True


# --- siralama ----------------------------------------------------------------

def _sort_key(item: Dict[str, Any], sort_by: str) -> Tuple[int, Any, str]:
    """None degerler her zaman sona; ikincil anahtar symbol (kararlilik)."""
    value = item.get(sort_by)
    symbol = str(item.get("symbol") or "")
    if value is None:
        return (1, "", symbol)
    if sort_by == "confidence":
        try:
            return (0, float(value), symbol)
        except (TypeError, ValueError):
            return (1, "", symbol)
    return (0, str(value).lower(), symbol)


# --- sayfalama + ana giris ----------------------------------------------------

def paginate(
    items: Sequence[Any], page: int, page_size: int
) -> Tuple[List[Any], Dict[str, int]]:
    """Sayfa dilimi + pagination meta {page,page_size,total,total_pages}."""
    total = len(items)
    total_pages = math.ceil(total / page_size) if total else 0
    start = (page - 1) * page_size
    page_items = list(items[start : start + page_size])
    pagination = {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }
    return page_items, pagination


def apply_filters(
    items: Iterable[Any],
    params: Optional[FilterParams] = None,
    strict: bool = False,
) -> Tuple[List[Any], Dict[str, int]]:
    """Hizala -> filtrele -> sirala -> sayfala.

    Donus: (page_items, pagination). Liste tek run_id'ye hizalidir
    (strict=True ise karisik run RunMismatchError firlatir).
    """
    params = params or FilterParams()
    aligned = align_run(list(items), strict=strict)
    filtered = [item for item in aligned if _matches(item, params)]
    reverse = params.sort_direction == "desc"
    # None/gecersiz degerler yon bagimisiz HER ZAMAN sonda kalir.
    with_value = [
        item for item in filtered if _sort_key(item, params.sort_by)[0] == 0
    ]
    without_value = [
        item for item in filtered if _sort_key(item, params.sort_by)[0] == 1
    ]
    with_value.sort(
        key=lambda item: _sort_key(item, params.sort_by), reverse=reverse
    )
    without_value.sort(key=lambda item: str(item.get("symbol") or ""))
    return paginate(with_value + without_value, params.page, params.page_size)
