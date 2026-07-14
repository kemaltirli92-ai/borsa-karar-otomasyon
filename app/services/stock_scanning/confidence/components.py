"""BLOK 15 - 12 bilesen degerlendirici (components.py).

Her fonksiyon TEK bir bileseni degerlendirir ve ComponentInput dondurur
(SPEC BLOK 15 bolum 4). Tum girdiler ENJEKTEdir — gercek ag/cagri YOK:

1.  price_availability       — gecerli son fiyat var mi (BLOK 8 storage)
2.  price_source_validation  — ana/yedek kaynak kapanisi tolerans icinde mi
                               (BLOK 8 validator sonucu)
3.  volume_availability      — gecerli hacim var mi (BLOK 10; eksik hacim
                               MISSING, gercek sifir OK DEGIL)
4.  history_sufficiency      — veri yeterlilik etiketi (BLOK 9 sufficiency:
                               SUFFICIENT_DATA/LIMITED_DATA/NEW_LISTING/...)
5.  kap_check                — KAP kontrol tamam mi (BLOK 11: kritik bildirim
                               body durumu)
6.  news_check               — haber kontrol tamam mi (BLOK 12: eslestirme/
                               dedupe tamamlandi mi)
7.  corporate_check          — kurumsal islem kontrol tamam mi (BLOK 13)
8.  restriction_check        — tedbir kontrol tamam mi + aktif TRADING_HALT
                               bayragi (BLOK 13)
9.  symbol_verification      — stock_id dogrulanmis mi (BLOK 6: VERIFIED;
                               SYMBOL_VERIFICATION_PENDING ise UNVERIFIED)
10. data_freshness           — son veri taze mi (enjekte saat; stale_days_limit;
                               eski ise STALE)
11. anomaly_count            — anomali sayisi (0: OK, 1-2: INFO, 3+: FAILED)
12. critical_fields          — kritik eksik alan var mi (varsa FAILED + alan
                               adlari)

Kontrol durumu sozlugu (kap/news/corporate/restriction girdileri):
- None              -> MISSING  (kontrol calistirilmadi)
- True / "COMPLETED" / "OK"      -> kontrol tamam
- "PENDING" / "IN_PROGRESS" / "INCOMPLETE" / False -> UNVERIFIED
- "ERROR" / "FAILED"             -> FAILED
- bilinmeyen string              -> UNVERIFIED (guvenli varsayilan)

stdlib only; gercek ag YOK; deterministik; saat enjekte.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence

from .models import (
    FAILED,
    INSUFFICIENT_FOR_TECHNICAL,
    LIMITED_DATA,
    MISSING,
    NEW_LISTING,
    NEW_LISTING_NOTE,
    NOT_APPLICABLE,
    OK,
    PRICE_DATA_MISSING,
    REVIEW_REQUIRED,
    STALE,
    SUFFICIENT_DATA,
    UNVERIFIED,
    ComponentInput,
)

# Kontrol tamam durumlari
_COMPLETED = ("COMPLETED", "OK", "DONE")
_PENDING = ("PENDING", "IN_PROGRESS", "INCOMPLETE", "PARTIAL")
_ERRORED = ("ERROR", "FAILED")

# Fiyat kaynak dogrulama durumlari (BLOK 8 validator ciktisi)
_VALIDATION_OK = ("VALIDATED", "OK", "MATCH", "WITHIN_TOLERANCE")
_VALIDATION_PENDING = ("PENDING", "NOT_RUN", "INCOMPLETE", "SKIPPED")
_VALIDATION_BAD = ("DIVERGED", "MISMATCH", "OUT_OF_TOLERANCE", "FAILED", "ERROR")


def _coerce_number(value) -> Optional[float]:
    """Sayiya cevrilebilen degeri float yapar; aksi None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _coerce_date(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _check_status(status) -> Optional[str]:
    """Kontrol durumu girdisini kanonik hale getirir.

    Donus: "COMPLETED" | "PENDING" | "ERROR" | "UNKNOWN" | None
    (None: kontrol hic calistirilmadi)
    """
    if status is None:
        return None
    if isinstance(status, bool):
        return "COMPLETED" if status else "PENDING"
    s = str(status).strip().upper()
    if not s:
        return None
    if s in _COMPLETED:
        return "COMPLETED"
    if s in _PENDING:
        return "PENDING"
    if s in _ERRORED:
        return "ERROR"
    return "UNKNOWN"


def _evaluate_check(status, label: str) -> ComponentInput:
    """kap/news/corporate kontrol durumu icin ortak esleme."""
    canon = _check_status(status)
    if canon is None:
        return ComponentInput(MISSING, "%s kontrolu calistirilmadi" % label)
    if canon == "COMPLETED":
        return ComponentInput(OK, "%s kontrolu tamam" % label)
    if canon == "PENDING":
        return ComponentInput(UNVERIFIED, "%s kontrolu tamamlanmadi (bekliyor)" % label)
    if canon == "ERROR":
        return ComponentInput(FAILED, "%s kontrolu hata ile sonuclandi" % label)
    return ComponentInput(
        UNVERIFIED, "%s kontrol durumu bilinmiyor: %r" % (label, status)
    )


# ---------------------------------------------------------------------------
# 1. price_availability (BLOK 8 storage — enjekte son fiyat)
# ---------------------------------------------------------------------------
def evaluate_price_availability(last_price) -> ComponentInput:
    """Gecerli (pozitif, sayisal) son fiyat var mi."""
    if last_price is None:
        return ComponentInput(MISSING, "son fiyat yok")
    price = _coerce_number(last_price)
    if price is None:
        return ComponentInput(FAILED, "son fiyat sayisal degil: %r" % (last_price,))
    if price <= 0:
        return ComponentInput(FAILED, "son fiyat pozitif degil: %r" % (price,))
    return ComponentInput(OK, "son fiyat gecerli: %r" % (price,))


# ---------------------------------------------------------------------------
# 2. price_source_validation (BLOK 8 validator sonucu)
# ---------------------------------------------------------------------------
def evaluate_price_source_validation(validation_status) -> ComponentInput:
    """Ana/yedek kaynak kapanisi tolerans icinde mi."""
    if validation_status is None:
        return ComponentInput(MISSING, "kaynak dogrulamasi calistirilmadi")
    s = str(validation_status).strip().upper()
    if s in _VALIDATION_OK:
        return ComponentInput(OK, "kaynak kapanislari tolerans icinde")
    if s in _VALIDATION_PENDING:
        return ComponentInput(UNVERIFIED, "kaynak dogrulamasi henuz tamamlanmadi")
    if s in _VALIDATION_BAD:
        return ComponentInput(
            FAILED, "kaynak kapanislari tolerans disi: %r" % (validation_status,)
        )
    return ComponentInput(
        UNVERIFIED, "kaynak dogrulama durumu bilinmiyor: %r" % (validation_status,)
    )


# ---------------------------------------------------------------------------
# 3. volume_availability (BLOK 10 — eksik hacim MISSING, gercek sifir OK degil)
# ---------------------------------------------------------------------------
def evaluate_volume_availability(volume) -> ComponentInput:
    """Gecerli hacim var mi.

    - None          -> MISSING (eksik hacim)
    - negatif       -> FAILED  (gecersiz)
    - tam sifir     -> UNVERIFIED (gercek sifir OK DEGIL; dogrulanmadi)
    - pozitif       -> OK
    """
    if volume is None:
        return ComponentInput(MISSING, "hacim verisi yok")
    vol = _coerce_number(volume)
    if vol is None:
        return ComponentInput(FAILED, "hacim sayisal degil: %r" % (volume,))
    if vol < 0:
        return ComponentInput(FAILED, "hacim negatif: %r" % (vol,))
    if vol == 0:
        return ComponentInput(
            UNVERIFIED, "hacim tam sifir — gercek sifir olabilir, dogrulanmadi"
        )
    return ComponentInput(OK, "hacim gecerli: %r" % (vol,))


# ---------------------------------------------------------------------------
# 4. history_sufficiency (BLOK 9 sufficiency etiketi — enjekte)
# ---------------------------------------------------------------------------
def evaluate_history_sufficiency(sufficiency_label) -> ComponentInput:
    """Veri yeterlilik etiketini bilesen durumuna cevirir.

    - SUFFICIENT_DATA           -> OK
    - LIMITED_DATA              -> UNVERIFIED (sinirli gecmis)
    - NEW_LISTING               -> UNVERIFIED (NOT_APPLICABLE DEGIL; LIMITED
                                   sayilir, eksik gecmis "sifir veri" olmaz)
    - INSUFFICIENT_FOR_TECHNICAL -> FAILED
    - PRICE_DATA_MISSING        -> MISSING
    - REVIEW_REQUIRED           -> UNVERIFIED (cozulmemis inceleme)
    - None / bilinmeyen         -> MISSING / UNVERIFIED
    """
    if sufficiency_label is None:
        return ComponentInput(MISSING, "yeterlilik etiketi yok")
    s = str(sufficiency_label).strip().upper()
    if s == SUFFICIENT_DATA:
        return ComponentInput(OK, "yeterli gecmis (SUFFICIENT_DATA)")
    if s == LIMITED_DATA:
        return ComponentInput(UNVERIFIED, "sinirli gecmis (LIMITED_DATA)")
    if s == NEW_LISTING:
        return ComponentInput(UNVERIFIED, NEW_LISTING_NOTE + " (NEW_LISTING)")
    if s == INSUFFICIENT_FOR_TECHNICAL:
        return ComponentInput(
            FAILED, "teknik icin yetersiz gecmis (INSUFFICIENT_FOR_TECHNICAL)"
        )
    if s == PRICE_DATA_MISSING:
        return ComponentInput(MISSING, "fiyat serisi yok (PRICE_DATA_MISSING)")
    if s == REVIEW_REQUIRED:
        return ComponentInput(
            UNVERIFIED, "cozulmemis inceleme var (REVIEW_REQUIRED)"
        )
    return ComponentInput(
        UNVERIFIED, "bilinmeyen yeterlilik etiketi: %r" % (sufficiency_label,)
    )


# ---------------------------------------------------------------------------
# 5. kap_check (BLOK 11 — kritik bildirim body durumu)
# ---------------------------------------------------------------------------
def evaluate_kap_check(kap_status, required: bool = True) -> ComponentInput:
    """KAP kontrol tamam mi.

    required=False -> NOT_APPLICABLE (bilesen agirligi kalanlara dagitilir).
    """
    if not required:
        return ComponentInput(NOT_APPLICABLE, "KAP kontrolu uygulanamaz")
    return _evaluate_check(kap_status, "KAP")


# ---------------------------------------------------------------------------
# 6. news_check (BLOK 12 — eslestirme/dedupe tamamlandi mi)
# ---------------------------------------------------------------------------
def evaluate_news_check(news_status) -> ComponentInput:
    """Haber kontrol tamam mi (eslestirme + dedupe)."""
    return _evaluate_check(news_status, "haber")


# ---------------------------------------------------------------------------
# 7. corporate_check (BLOK 13 — kurumsal islem kontrolu)
# ---------------------------------------------------------------------------
def evaluate_corporate_check(corporate_status) -> ComponentInput:
    """Kurumsal islem kontrol tamam mi."""
    return _evaluate_check(corporate_status, "kurumsal islem")


# ---------------------------------------------------------------------------
# 8. restriction_check (BLOK 13 — tedbir kontrolu + TRADING_HALT bayragi)
# ---------------------------------------------------------------------------
def evaluate_restriction_check(
    restriction_status, trading_halt_active: bool = False
) -> ComponentInput:
    """Tedbir kontrol tamam mi + aktif TRADING_HALT bayragi.

    Kontrol tamam VE aktif TRADING_HALT var -> FAILED
    ("restriction_check FAILED ise scoring_ready=False" — SPEC bolum 9;
    technical_ready etkilenmez, readiness sarti 9 kontrolun TAMAMLANMASINA
    bakar).
    """
    canon = _check_status(restriction_status)
    if canon is None:
        return ComponentInput(MISSING, "tedbir kontrolu calistirilmadi")
    if canon == "PENDING":
        return ComponentInput(UNVERIFIED, "tedbir kontrolu tamamlanmadi (bekliyor)")
    if canon == "ERROR":
        return ComponentInput(FAILED, "tedbir kontrolu hata ile sonuclandi")
    if canon == "UNKNOWN":
        return ComponentInput(
            UNVERIFIED, "tedbir kontrol durumu bilinmiyor: %r" % (restriction_status,)
        )
    # Kontrol tamam
    if trading_halt_active:
        return ComponentInput(
            FAILED, "aktif TRADING_HALT tespit edildi (kontrol tamam)"
        )
    return ComponentInput(OK, "tedbir kontrolu tamam, aktif TRADING_HALT yok")


# ---------------------------------------------------------------------------
# 9. symbol_verification (BLOK 6 — VERIFIED / SYMBOL_VERIFICATION_PENDING)
# ---------------------------------------------------------------------------
def evaluate_symbol_verification(verification_status) -> ComponentInput:
    """stock_id dogrulanmis mi.

    VERIFIED -> OK; SYMBOL_VERIFICATION_PENDING -> UNVERIFIED;
    diger/None -> FAILED/MISSING.
    """
    if verification_status is None:
        return ComponentInput(MISSING, "dogrulama durumu yok")
    s = str(verification_status).strip().upper()
    if s == "VERIFIED":
        return ComponentInput(OK, "stock_id dogrulanmis (VERIFIED)")
    if s == "SYMBOL_VERIFICATION_PENDING":
        return ComponentInput(
            UNVERIFIED, "dogrulama bekliyor (SYMBOL_VERIFICATION_PENDING)"
        )
    return ComponentInput(FAILED, "dogrulanmamis stock_id: %r" % (verification_status,))


# ---------------------------------------------------------------------------
# 10. data_freshness (enjekte saat; stale_days_limit; eski ise STALE)
# ---------------------------------------------------------------------------
def evaluate_data_freshness(
    last_data_date, clock=None, stale_days_limit: int = 5
) -> ComponentInput:
    """Son veri taze mi.

    age = (bugun - son veri tarihi).gun; age > stale_days_limit -> STALE.
    Gelecek tarih (age < 0) taze sayilir. Saat enjekte (clock) — yoksa
    date.today kullanilir.
    """
    if last_data_date is None:
        return ComponentInput(MISSING, "son veri tarihi yok")
    last = _coerce_date(last_data_date)
    if last is None:
        return ComponentInput(
            FAILED, "son veri tarihi cozulemedi: %r" % (last_data_date,)
        )
    today = _coerce_date(clock()) if clock is not None else date.today()
    if today is None:
        return ComponentInput(UNVERIFIED, "saat enjekte edilmedi/cozulemedi")
    age = (today - last).days
    if age > stale_days_limit:
        return ComponentInput(
            STALE,
            "son veri %d gun once (sinir: %d) — ESKI VERI" % (age, stale_days_limit),
        )
    return ComponentInput(OK, "veri taze (yas: %d gun, sinir: %d)" % (age, stale_days_limit))


# ---------------------------------------------------------------------------
# 11. anomaly_count (0: OK, 1-2: INFO, 3+: FAILED)
# ---------------------------------------------------------------------------
def evaluate_anomaly_count(count) -> ComponentInput:
    """Anomali sayisi degerlendirmesi.

    0 -> OK; 1-2 -> OK (INFO notu ile, guven dusurmez); 3+ -> FAILED.
    """
    if count is None:
        return ComponentInput(MISSING, "anomali sayisi yok")
    if isinstance(count, bool) or not isinstance(count, (int, float)):
        return ComponentInput(FAILED, "anomali sayisi sayisal degil: %r" % (count,))
    n = int(count)
    if n < 0:
        return ComponentInput(FAILED, "anomali sayisi negatif: %d" % n)
    if n == 0:
        return ComponentInput(OK, "anomali yok")
    if n <= 2:
        return ComponentInput(OK, "INFO: %d anomali kayitli (esik alti)" % n)
    return ComponentInput(FAILED, "%d anomali tespit edildi (esik: 3)" % n)


# ---------------------------------------------------------------------------
# 12. critical_fields (kritik eksik alan var mi)
# ---------------------------------------------------------------------------
def evaluate_critical_fields(missing_fields: Optional[Sequence]) -> ComponentInput:
    """Kritik eksik alan listesi.

    None  -> MISSING (kontrol calistirilmadi)
    []    -> OK
    [...] -> FAILED + alan adlari detail icinde
    """
    if missing_fields is None:
        return ComponentInput(MISSING, "kritik alan kontrolu calistirilmadi")
    fields = [str(f) for f in missing_fields if str(f).strip()]
    if not fields:
        return ComponentInput(OK, "kritik eksik alan yok")
    return ComponentInput(FAILED, "kritik eksik alanlar: %s" % ", ".join(fields))


# ---------------------------------------------------------------------------
# Toplu degerlendirme (enjekte tarama girdileri -> 12 bilesen)
# ---------------------------------------------------------------------------
@dataclass
class ComponentScanInputs:
    """Bir hisse icin enjekte tarama girdileri (BLOK 6/8/9/10/11/12/13).

    Tum alanlar opsiyonel; None 'kontrol calistirilmadi' demektir.
    """

    last_price: Optional[float] = None
    source_validation: Optional[str] = None
    volume: Optional[float] = None
    sufficiency_label: Optional[str] = None
    kap_status: Optional[str] = None
    kap_required: bool = True
    news_status: Optional[str] = None
    corporate_status: Optional[str] = None
    restriction_status: Optional[str] = None
    trading_halt_active: bool = False
    verification_status: Optional[str] = None
    last_data_date: Optional[str] = None
    anomaly_count: Optional[int] = None
    critical_missing: List[str] = field(default_factory=list)


def evaluate_components(
    inputs: ComponentScanInputs, clock=None, stale_days_limit: int = 5
) -> Dict[str, ComponentInput]:
    """12 bileseni topluca degerlendirir (bilesen adi -> ComponentInput).

    Saat enjekte (clock): data_freshness icin. Deterministik.
    """
    return {
        "price_availability": evaluate_price_availability(inputs.last_price),
        "price_source_validation": evaluate_price_source_validation(
            inputs.source_validation
        ),
        "volume_availability": evaluate_volume_availability(inputs.volume),
        "history_sufficiency": evaluate_history_sufficiency(inputs.sufficiency_label),
        "kap_check": evaluate_kap_check(inputs.kap_status, required=inputs.kap_required),
        "news_check": evaluate_news_check(inputs.news_status),
        "corporate_check": evaluate_corporate_check(inputs.corporate_status),
        "restriction_check": evaluate_restriction_check(
            inputs.restriction_status,
            trading_halt_active=inputs.trading_halt_active,
        ),
        "symbol_verification": evaluate_symbol_verification(inputs.verification_status),
        "data_freshness": evaluate_data_freshness(
            inputs.last_data_date, clock=clock, stale_days_limit=stale_days_limit
        ),
        "anomaly_count": evaluate_anomaly_count(inputs.anomaly_count),
        "critical_fields": evaluate_critical_fields(inputs.critical_missing),
    }
