"""BLOK 16 - API rapor surum zarfi (ApiEnvelope).

Her musteri/yonetici cevabi zorunlu zarf alanlariyla doner:
- scan_run_id      : cevabin ait oldugu tarama run kimligi
- report_version   : int, artan (ReportVersion sayaci; deterministik, enjekte)
- last_updated_at  : ISO 8601 zaman damgasi
- data_cutoff_at   : ISO 8601 veri kesim zamani (09:40 kesim kaydi run'dan gelir)
- status           : OK | PARTIAL | FAILED | STALE

Karisma engeli: data'nin run_id'si zarf run_id'sinden farkliysa
RunMismatchError (RUN_MISMATCH) firlatilir.

stdlib only; gercek ag YOK; saat/sayac enjekte.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Union

STATUS_VALUES = ("OK", "PARTIAL", "FAILED", "STALE")
STATUS_OK = "OK"
STATUS_PARTIAL = "PARTIAL"
STATUS_FAILED = "FAILED"
STATUS_STALE = "STALE"

# pagination icin zorunlu alanlar (SPEC bolum 8).
PAGINATION_FIELDS = ("page", "page_size", "total", "total_pages")


class RunMismatchError(Exception):
    """data run_id'si zarf run_id'siyle uyuşmuyor (RUN_MISMATCH)."""

    code = "RUN_MISMATCH"

    def __init__(self, envelope_run_id: str, data_run_id: str) -> None:
        self.envelope_run_id = envelope_run_id
        self.data_run_id = data_run_id
        super().__init__(
            f"RUN_MISMATCH: zarf run_id={envelope_run_id} != data run_id={data_run_id}"
        )


class InvalidEnvelopeError(ValueError):
    """Zarf uretimi icin zorunlu alan eksik/gecersiz."""


class ReportVersion:
    """Artan rapor surum sayaci (deterministik; testlerde enjekte edilebilir).

    Her next() cagrisi bir oncekinden buyuk int dondurur. Gercek saate
    bagimli degildir; VPS'te kalici depodan beslenmek uzere enjeksiyon
    noktasi olarak tasarlanmistir.
    """

    def __init__(self, start: int = 0) -> None:
        if not isinstance(start, int) or start < 0:
            raise ValueError("report_version baslangici negatif olamaz")
        self._current = start

    def next(self) -> int:
        """Sonraki surum numarasi (her zaman artan)."""
        self._current += 1
        return self._current

    @property
    def current(self) -> int:
        return self._current


# Modul seviyesinde varsayilan sayac: version_provider enjekte edilmezse
# cevaplar yine de artan surum alir.
_DEFAULT_VERSION = ReportVersion()

# run_record'tan okunacak aday alan adlari (dict veya obje olabilir).
_RUN_ID_FIELDS = ("run_id", "scan_run_id")
_UPDATED_FIELDS = ("last_updated_at", "updated_at", "completed_at")
_CUTOFF_FIELDS = ("data_cutoff_at", "cutoff_at")


def _field(record: Any, names: Sequence[str]) -> Any:
    """run_record dict ya da obje olabilir; ilk bulunan alani dondur."""
    if isinstance(record, dict):
        for name in names:
            value = record.get(name)
            if value is not None:
                return value
        return None
    for name in names:
        value = getattr(record, name, None)
        if value is not None:
            return value
    return None


def _iso(value: Any) -> str:
    """datetime/date degerini ISO 8601'e cevir; str ise oldugu gibi birak."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise InvalidEnvelopeError(f"ISO'ya cevrilemez deger: {type(value).__name__}")


def _resolve_version(version_provider: Optional[Any]) -> int:
    """Surum numarasini uret: ReportVersion, callable ya da int enjekte."""
    provider = version_provider if version_provider is not None else _DEFAULT_VERSION
    if isinstance(provider, ReportVersion):
        return provider.next()
    if hasattr(provider, "next"):
        return int(provider.next())
    if callable(provider):
        return int(provider())
    return int(provider)


def _data_run_ids(data: Any) -> Iterable[str]:
    """data icindeki run_id adaylari (dict ya da dict listesi)."""
    if isinstance(data, dict):
        rid = data.get("scan_run_id") or data.get("run_id")
        if rid is not None:
            yield str(rid)
    elif isinstance(data, (list, tuple)):
        for item in data:
            if isinstance(item, dict):
                rid = item.get("scan_run_id") or item.get("run_id")
                if rid is not None:
                    yield str(rid)


def assert_run_match(envelope_run_id: str, data: Any) -> None:
    """data run_id'leri zarf run_id'siyle uyuşmazsa RunMismatchError."""
    for rid in _data_run_ids(data):
        if rid != envelope_run_id:
            raise RunMismatchError(envelope_run_id, rid)


def _base_envelope(
    run_record: Any,
    status: str,
    version_provider: Optional[Any],
) -> Dict[str, Any]:
    """Zorunlu zarf alanlarini run_record'tan kur."""
    run_id = _field(run_record, _RUN_ID_FIELDS)
    if run_id is None:
        raise InvalidEnvelopeError("run_record.run_id zorunlu")
    updated = _field(run_record, _UPDATED_FIELDS)
    if updated is None:
        raise InvalidEnvelopeError("run_record.last_updated_at zorunlu")
    cutoff = _field(run_record, _CUTOFF_FIELDS)
    if cutoff is None:
        raise InvalidEnvelopeError("run_record.data_cutoff_at zorunlu")
    if status not in STATUS_VALUES:
        raise InvalidEnvelopeError(
            f"gecersiz status: {status!r} (beklenen: {', '.join(STATUS_VALUES)})"
        )
    return {
        "scan_run_id": str(run_id),
        "report_version": _resolve_version(version_provider),
        "last_updated_at": _iso(updated),
        "data_cutoff_at": _iso(cutoff),
        "status": status,
    }


def build_envelope(
    run_record: Any,
    data: Any,
    status: str = STATUS_OK,
    version_provider: Optional[Any] = None,
) -> Dict[str, Any]:
    """Tekil veri cevabi icin zarf.

    data run_id tasiyorsa zarf run_id'siyle uyuşmak zorunda;
    uyuşmazlikta RunMismatchError (RUN_MISMATCH).
    """
    envelope = _base_envelope(run_record, status, version_provider)
    assert_run_match(envelope["scan_run_id"], data)
    envelope["data"] = data
    return envelope


def list_envelope(
    run_record: Any,
    items: Sequence[Any],
    page_meta: Dict[str, Any],
    status: str = STATUS_OK,
    version_provider: Optional[Any] = None,
) -> Dict[str, Any]:
    """Liste cevabi icin zarf: items + pagination.

    Sayfadaki tum kalemler TEK run_id'ye ait olmali; farkli run'lu kalem
    varsa RunMismatchError. page_meta 4 zorunlu alani icermeli.
    """
    envelope = _base_envelope(run_record, status, version_provider)
    item_list = list(items)
    assert_run_match(envelope["scan_run_id"], item_list)
    meta = dict(page_meta)
    missing = [name for name in PAGINATION_FIELDS if name not in meta]
    if missing:
        raise InvalidEnvelopeError(
            "pagination alanlari eksik: " + ", ".join(missing)
        )
    envelope["items"] = item_list
    envelope["pagination"] = meta
    return envelope


class ApiEnvelope:
    """Enjekte sayac/saat ile zarf ureten yardimci sinif.

    Modul fonksiyonlariyla ayni kurallari uygular; servis katmanina
    tek bir version_provider baglamak icin kullanilir.
    """

    def __init__(
        self,
        version_provider: Optional[Union[ReportVersion, Callable[[], int]]] = None,
    ) -> None:
        self.version_provider = version_provider or ReportVersion()

    def build(
        self, run_record: Any, data: Any, status: str = STATUS_OK
    ) -> Dict[str, Any]:
        return build_envelope(run_record, data, status, self.version_provider)

    def list(
        self,
        run_record: Any,
        items: Sequence[Any],
        page_meta: Dict[str, Any],
        status: str = STATUS_OK,
    ) -> Dict[str, Any]:
        return list_envelope(run_record, items, page_meta, status, self.version_provider)
