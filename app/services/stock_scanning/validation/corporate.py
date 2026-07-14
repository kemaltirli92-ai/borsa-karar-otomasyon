"""BLOK 9 - Kurumsal islem duzeltmesi (corporate.py).

SPEC BLOK 9 bolum 7.

Bilesenler:
- CorporateAction dataclass: stock_id, action_type, announcement_date,
  effective_date, ratio, kap_notice_no, source.
- CorporateActionAdjuster:
    * register(action): olay kaydi; ayni kap_notice_no tekrari REDDEDILIR
      (DuplicateKapNoticeError / DUPLICATE_KAP_NOTICE). BLOK 7
      stock_corporate_actions formatina uyumlu dict doner.
    * adjust_series(stock_id, raw_bars, actions=None) -> AdjustedSeries:
      ham fiyatlar KORUNUR (raw_bars degismez); duzeltilmis fiyatlar AYRI
      AdjustedBar(trade_date, raw_close, adj_close, adj_factor, action_refs)
      olarak uretilir. Duzeltme effective_date ONCESI tum barlara kumulatif
      uygulanir. Her calistirma YENI data_version ("adj-vN") uretir; eski
      surumler listede kalir ve eski degerlerle okunur.
    * explain_outlier(bar, prev_close, actions): outlier kurumsal islemle
      aciklaniyor mu?
    * backfill_history(...): yeni halka arz icin sentetik/sifir gecmis
      URETILMEZ — her cagri NoSyntheticHistoryError (NO_SYNTHETIC_HISTORY)
      firlatir.
- FrozenSnapshotStore: gecmis rapor snapshot'lari icin enjekte frozen
  store; bir kez yazilan anahtar DEGISTIRILEMEZ (SnapshotFrozenError) ve
  get her zaman derin kopya dondurur (sessiz degisiklik yok).

Faktor konvansiyonu (duzeltme effective_date oncesi barlara uygulanir):
- split / reverse_split: ratio "a:b" = a yeni pay / b eski pay ->
  faktor = b/a ("2:1" -> 0.5; "1:2" -> 2.0). Sayisal ratio dogrudan faktordur.
- bonus / capital_increase / rights: ratio "a:b" = b paya a bedelsiz/yeni ->
  faktor = b/(a+b) ("1:1" -> 0.5). Sayisal ratio dogrudan faktordur.
- dividend: ratio hisse basina nakit tutar; faktor =
  (ref_close - tutar) / ref_close (ref_close = effective_date oncesi son
  ham kapanis).
- other: "a:b" -> b/a; sayisal -> dogrudan faktor.

Gercek ag YOK; stdlib only; saat enjekte.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# Olay / hata kodlari
DUPLICATE_KAP_NOTICE = "DUPLICATE_KAP_NOTICE"
INVALID_CORPORATE_ACTION = "INVALID_CORPORATE_ACTION"
NO_SYNTHETIC_HISTORY = "NO_SYNTHETIC_HISTORY"
SNAPSHOT_FROZEN = "SNAPSHOT_FROZEN"

ACTION_TYPES = (
    "dividend",
    "bonus",
    "split",
    "capital_increase",
    "rights",
    "reverse_split",
    "other",
)

DEFAULT_OUTLIER_THRESHOLD_PCT = 20.0
DEFAULT_EXPLAIN_TOLERANCE_PCT = 2.0


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_date(value) -> Optional[str]:
    """date/datetime/str -> ISO tarih stringi; gecersizse None."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10]).isoformat()
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------- #
# Hata siniflari (makine okunur kodlu)
# --------------------------------------------------------------------------- #
class CorporateActionError(Exception):
    """Kurumsal islem hatalarinin taban sinifi."""

    code = "CORPORATE_ACTION_ERROR"

    def __init__(self, message: str, **details):
        super().__init__(message)
        self.message = message
        self.details = details


class DuplicateKapNoticeError(CorporateActionError):
    code = DUPLICATE_KAP_NOTICE


class InvalidCorporateActionError(CorporateActionError):
    code = INVALID_CORPORATE_ACTION


class NoSyntheticHistoryError(CorporateActionError):
    code = NO_SYNTHETIC_HISTORY


class SnapshotFrozenError(CorporateActionError):
    code = SNAPSHOT_FROZEN


# --------------------------------------------------------------------------- #
# Veri modeli
# --------------------------------------------------------------------------- #
@dataclass
class CorporateAction:
    """Kurumsal islem kaydi (BLOK 7 stock_corporate_actions ile uyumlu)."""

    stock_id: str
    action_type: str
    announcement_date: str
    effective_date: str
    ratio: Any
    kap_notice_no: str
    source: str = "KAP"

    def __post_init__(self) -> None:
        if self.action_type not in ACTION_TYPES:
            raise InvalidCorporateActionError(
                "gecersiz action_type: %r (gecerli: %s)"
                % (self.action_type, ", ".join(ACTION_TYPES)),
                action_type=self.action_type,
            )
        for name in ("announcement_date", "effective_date"):
            iso = _iso_date(getattr(self, name))
            if iso is None:
                raise InvalidCorporateActionError(
                    "gecersiz %s: %r" % (name, getattr(self, name))
                )
            setattr(self, name, iso)
        if not self.kap_notice_no or not str(self.kap_notice_no).strip():
            raise InvalidCorporateActionError("kap_notice_no bos olamaz")
        if not self.stock_id or not str(self.stock_id).strip():
            raise InvalidCorporateActionError("stock_id bos olamaz")

    def to_dict(self) -> dict:
        """BLOK 7 stock_corporate_actions satirina uyumlu sozluk."""
        return {
            "stock_id": self.stock_id,
            "action_type": self.action_type,
            "announcement_date": self.announcement_date,
            "effective_date": self.effective_date,
            "ratio": self.ratio,
            "kap_notice_no": self.kap_notice_no,
            "source": self.source,
        }


@dataclass
class AdjustedBar:
    """Duzeltilmis bar: ham kapanis KORUNUR, duzeltilmis AYRI alandadir."""

    trade_date: str
    raw_close: float
    adj_close: float
    adj_factor: float
    action_refs: List[str] = field(default_factory=list)


@dataclass
class AdjustedSeries:
    """Bir duzeltme calismasinin ciktisi (data_version ile surumlenir)."""

    stock_id: str
    data_version: str
    bars: List[AdjustedBar] = field(default_factory=list)
    action_refs: List[str] = field(default_factory=list)
    created_at: str = ""


@dataclass
class OutlierExplanation:
    """explain_outlier sonucu."""

    explained: bool
    reason: str
    diff_pct: float
    expected_close: Optional[float] = None
    actual_close: Optional[float] = None
    action_ref: Optional[str] = None


# --------------------------------------------------------------------------- #
# Faktor hesabi
# --------------------------------------------------------------------------- #
def parse_ratio(ratio) -> float:
    """"a:b" stringini a/b'ye, sayiyi floata cevirir."""
    if isinstance(ratio, bool):
        raise InvalidCorporateActionError("ratio bool olamaz")
    if isinstance(ratio, (int, float)):
        return float(ratio)
    if isinstance(ratio, str):
        text = ratio.strip()
        if ":" in text:
            left, _, right = text.partition(":")
            try:
                a, b = float(left), float(right)
            except ValueError:
                raise InvalidCorporateActionError("gecersiz ratio: %r" % (ratio,))
            if b == 0:
                raise InvalidCorporateActionError("ratio paydasi 0 olamaz: %r" % (ratio,))
            return a / b
        try:
            return float(text)
        except ValueError:
            raise InvalidCorporateActionError("gecersiz ratio: %r" % (ratio,))
    raise InvalidCorporateActionError("gecersiz ratio tipi: %r" % (type(ratio).__name__,))


def adjustment_factor(action: CorporateAction, ref_close: Optional[float] = None) -> float:
    """Bir aksiyonun fiyat duzeltme faktoru.

    dividend icin ref_close zorunludur (effective_date oncesi son kapanis).
    """
    if action.action_type == "dividend":
        amount = parse_ratio(action.ratio)
        if ref_close is None or ref_close <= 0:
            raise InvalidCorporateActionError(
                "temettu faktoru icin pozitif ref_close gerekli",
                kap_notice_no=action.kap_notice_no,
            )
        if amount >= ref_close:
            raise InvalidCorporateActionError(
                "temettu tutari kapanisi asiyor: %s >= %s" % (amount, ref_close),
                kap_notice_no=action.kap_notice_no,
            )
        return (ref_close - amount) / ref_close
    ratio = action.ratio
    if isinstance(ratio, str) and ":" in ratio.strip():
        left, _, right = ratio.strip().partition(":")
        a, b = float(left), float(right)
        if a <= 0 or b <= 0:
            raise InvalidCorporateActionError("ratio bilesenleri pozitif olmali: %r" % (ratio,))
        if action.action_type in ("bonus", "capital_increase", "rights"):
            return b / (a + b)
        # split / reverse_split / other: a yeni pay / b eski pay
        return b / a
    factor = parse_ratio(ratio)
    if factor <= 0:
        raise InvalidCorporateActionError("faktor pozitif olmali: %r" % (ratio,))
    return factor


# --------------------------------------------------------------------------- #
# Frozen snapshot store (eski rapor korumasi)
# --------------------------------------------------------------------------- #
class FrozenSnapshotStore:
    """Gecmis rapor snapshot'lari icin degistirilemez depo (enjekte).

    Bir anahtar yalnizca BIR KEZ yazilabilir; ikinci yazim
    SnapshotFrozenError firlatir. get her zaman derin kopya dondurur:
    cagiranin yapacagi degisiklik saklanan snapshot'i ETKILEMEZ.
    """

    def __init__(self):
        self._data: Dict[str, Any] = {}

    def freeze(self, key: str, value: Any) -> None:
        key = str(key)
        if key in self._data:
            raise SnapshotFrozenError(
                "snapshot zaten dondurulmus, degistirilemez: %r" % key, key=key
            )
        self._data[key] = copy.deepcopy(value)

    def get(self, key: str) -> Any:
        key = str(key)
        if key not in self._data:
            raise KeyError("snapshot bulunamadi: %r" % key)
        return copy.deepcopy(self._data[key])

    def keys(self) -> List[str]:
        return list(self._data.keys())


# --------------------------------------------------------------------------- #
# Duzeltici
# --------------------------------------------------------------------------- #
class CorporateActionAdjuster:
    """Kurumsal islem duzeltici (surumlenmis, ham koruyan)."""

    def __init__(self, clock: Optional[Callable] = None):
        self._clock = clock or _utcnow
        # kap_notice_no -> CorporateAction (tekrar kayit reddi icin)
        self._by_notice: Dict[str, CorporateAction] = {}
        # stock_id -> [CorporateAction] (kayit sirasi)
        self._by_stock: Dict[str, List[CorporateAction]] = {}
        # stock_id -> {data_version: AdjustedSeries} (eski surumler korunur)
        self._versions: Dict[str, Dict[str, AdjustedSeries]] = {}
        # stock_id -> son surum numarasi
        self._version_seq: Dict[str, int] = {}

    def _now(self) -> str:
        now = self._clock()
        if isinstance(now, str):
            return now
        if isinstance(now, datetime):
            return now.strftime("%Y-%m-%dT%H:%M:%SZ")
        if isinstance(now, date):
            return now.isoformat()
        raise TypeError("clock date/datetime/str dondurmeli: %r" % (now,))

    # ------------------------------------------------------------------ #
    # Kayit
    # ------------------------------------------------------------------ #
    def register(self, action: CorporateAction) -> dict:
        """Kurumsal islem kaydeder; ayni kap_notice_no tekrari REDDEDILIR.

        Donus: BLOK 7 stock_corporate_actions formatina uyumlu dict
        (registered_at damgasi ekli).
        """
        if not isinstance(action, CorporateAction):
            raise InvalidCorporateActionError(
                "action CorporateAction olmali: %r" % (type(action).__name__,)
            )
        notice = str(action.kap_notice_no)
        if notice in self._by_notice:
            raise DuplicateKapNoticeError(
                "kap_notice_no zaten kayitli: %r" % notice, kap_notice_no=notice
            )
        self._by_notice[notice] = action
        self._by_stock.setdefault(action.stock_id, []).append(action)
        row = action.to_dict()
        row["registered_at"] = self._now()
        return row

    def actions_for(self, stock_id: str) -> List[CorporateAction]:
        return list(self._by_stock.get(stock_id, []))

    # ------------------------------------------------------------------ #
    # Surumleme
    # ------------------------------------------------------------------ #
    def _next_version(self, stock_id: str) -> str:
        n = self._version_seq.get(stock_id, 0) + 1
        self._version_seq[stock_id] = n
        return "adj-v%d" % n

    def list_versions(self, stock_id: str) -> List[str]:
        """Uretilmis tum data_version'lar (uretim sirasi)."""
        versions = self._versions.get(stock_id, {})
        return sorted(versions, key=lambda v: int(v.split("-v")[1]))

    def get_series(self, stock_id: str, data_version: Optional[str] = None) -> AdjustedSeries:
        """Belirli surumu (veya en yeniyi) dondurur; her zaman derin kopya.

        Eski surum okundugunda ESKI degerler doner — yeni duzeltmeler
        gecmis surumleri sessizce degistirmez.
        """
        versions = self._versions.get(stock_id, {})
        if not versions:
            raise KeyError("duzeltilmis seri yok: %r" % stock_id)
        if data_version is None:
            data_version = self.list_versions(stock_id)[-1]
        if data_version not in versions:
            raise KeyError("data_version bulunamadi: %r" % data_version)
        return copy.deepcopy(versions[data_version])

    # ------------------------------------------------------------------ #
    # Duzeltme
    # ------------------------------------------------------------------ #
    def _reference_close(self, raw_bars, effective_date: str) -> Optional[float]:
        """effective_date oncesi son ham kapanis (temettu faktoru icin)."""
        ref = None
        for bar in raw_bars:
            td = str(getattr(bar, "trade_date", ""))
            if td < effective_date:
                close = getattr(bar, "close", None)
                if close is not None:
                    ref = float(close)
        return ref

    def adjust_series(
        self,
        stock_id: str,
        raw_bars: Sequence,
        actions: Optional[Sequence[CorporateAction]] = None,
    ) -> AdjustedSeries:
        """Ham seriye kurumsal islem duzeltmesi uygular.

        - raw_bars HICBIR ZAMAN degistirilmez (ham fiyatlar korunur).
        - Duzeltilmis degerler ayri AdjustedBar listesinde uretilir.
        - Her cagri YENI data_version ("adj-vN") uretir; eski surumler
          listede kalir.
        - Duzeltme effective_date ONCESI barlara kumulatif uygulanir.
        """
        action_list = list(actions) if actions is not None else self.actions_for(stock_id)
        # Her aksiyonun faktorunu bir kez hesapla (temettu ref_close'lu).
        prepared: List[Tuple[CorporateAction, float]] = []
        for action in action_list:
            if action.action_type == "dividend":
                ref = self._reference_close(raw_bars, action.effective_date)
                factor = adjustment_factor(action, ref)
            else:
                factor = adjustment_factor(action)
            prepared.append((action, factor))

        adjusted_bars: List[AdjustedBar] = []
        for bar in raw_bars:
            td = str(getattr(bar, "trade_date", ""))
            raw_close = float(getattr(bar, "close"))
            factor = 1.0
            refs: List[str] = []
            for action, afactor in prepared:
                if td < action.effective_date:
                    factor *= afactor
                    refs.append(str(action.kap_notice_no))
            adjusted_bars.append(
                AdjustedBar(
                    trade_date=td,
                    raw_close=raw_close,
                    adj_close=round(raw_close * factor, 6),
                    adj_factor=factor,
                    action_refs=refs,
                )
            )

        version = self._next_version(stock_id)
        series = AdjustedSeries(
            stock_id=stock_id,
            data_version=version,
            bars=adjusted_bars,
            action_refs=[str(a.kap_notice_no) for a in action_list],
            created_at=self._now(),
        )
        self._versions.setdefault(stock_id, {})[version] = copy.deepcopy(series)
        return series

    # ------------------------------------------------------------------ #
    # Outlier aciklamasi
    # ------------------------------------------------------------------ #
    def explain_outlier(
        self,
        bar,
        prev_close: Optional[float],
        actions: Sequence[CorporateAction],
        threshold_pct: float = DEFAULT_OUTLIER_THRESHOLD_PCT,
        tolerance_pct: float = DEFAULT_EXPLAIN_TOLERANCE_PCT,
    ) -> OutlierExplanation:
        """Fiyat farki bir kurumsal islemle aciklaniyor mu?

        Esik alti fark "outlier degil" (explained=True, NO_OUTLIER).
        effective_date == bar.trade_date olan aksiyon varsa beklenen
        kapanis hesaplanir (bolunme: prev*faktor; temettu: prev-tutar);
        gercek kapanis tolerans icindeyse aciklanmis sayilir.
        """
        close = float(getattr(bar, "close"))
        trade_date = str(getattr(bar, "trade_date", ""))
        if prev_close is None or prev_close <= 0:
            return OutlierExplanation(
                explained=False,
                reason="NO_REFERENCE",
                diff_pct=0.0,
                actual_close=close,
            )
        diff = abs(close - float(prev_close)) / float(prev_close) * 100.0
        if diff <= threshold_pct:
            return OutlierExplanation(
                explained=True,
                reason="NO_OUTLIER",
                diff_pct=diff,
                expected_close=float(prev_close),
                actual_close=close,
            )
        for action in actions:
            if action.effective_date != trade_date:
                continue
            if action.action_type == "dividend":
                expected = float(prev_close) - parse_ratio(action.ratio)
            else:
                expected = float(prev_close) * adjustment_factor(action)
            if expected <= 0:
                continue
            dev = abs(close - expected) / expected * 100.0
            if dev <= tolerance_pct:
                return OutlierExplanation(
                    explained=True,
                    reason="CORPORATE_ACTION",
                    diff_pct=diff,
                    expected_close=expected,
                    actual_close=close,
                    action_ref=str(action.kap_notice_no),
                )
            return OutlierExplanation(
                explained=False,
                reason="CORPORATE_ACTION_MISMATCH",
                diff_pct=diff,
                expected_close=expected,
                actual_close=close,
                action_ref=str(action.kap_notice_no),
            )
        return OutlierExplanation(
            explained=False,
            reason="UNEXPLAINED_OUTLIER",
            diff_pct=diff,
            actual_close=close,
        )

    # ------------------------------------------------------------------ #
    # Yeni halka arz: sentetik gecmis URETILMEZ
    # ------------------------------------------------------------------ #
    def backfill_history(self, *args, **kwargs):
        """Eksik gecmis uretme cagrisi — DAİMA hata.

        Yeni halka arzlar icin sentetik/sifir bar olusturulmaz; eksik
        gecmis oldugu gibi birakilir (NO_SYNTHETIC_HISTORY).
        """
        raise NoSyntheticHistoryError(
            "sentetik gecmis uretilmez: yeni halka arzlar icin eksik "
            "gecmis oldugu gibi korunur",
            args=list(args),
            kwargs=dict(kwargs),
        )
