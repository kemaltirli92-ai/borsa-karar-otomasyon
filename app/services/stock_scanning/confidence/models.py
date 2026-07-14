"""BLOK 15 - Veri Guveni ve Hazirlik Durumu: veri modelleri (models.py).

Bu modul her hisse icin 0-100 Tarama Veri Guveni (data_confidence) ve
hazirlik durumlarini tasir. BU DEGER HISSE DEGERLENDIRMESI DEGILDIR,
yukselme ihtimali DEGILDIR, alim tavsiyesi DEGILDIR — verinin tamlik ve
dogrulama seviyesidir (kapsam kilidi).

Icerik (SPEC BLOK 15 bolum 3 + 5):
- Bilesen durumlari: OK | MISSING | STALE | UNVERIFIED | FAILED |
  NOT_APPLICABLE
- ComponentInput: bilesen degerlendirici ciktisi (status + detail)
- ReadyFlags: technical_ready / scoring_ready / favorite_eligible
- ConfidenceResult: nihai cikti paketi (data_confidence 0-100 int,
  hazirlik bayraklari, missing_fields, component_scores, warnings,
  disclaimer)
- ConfidenceConfig: 12 bilesen agirligi (varsayilan toplam = 100),
  set_weights (bilinmeyen bilesen reddi + toplam dogrulamasi/normalizasyon)
  + config_version audit izi
- Hata siniflari (makine okunur kodlu)

KAPSAM KILIDI: Bu modulde hisse degerlendirmesine iliskin yasakli
alan/fonksiyon YOKTUR (SPEC bolum 3'teki yasakli adlar tanimlanmamistir;
testlerle kanitlanir).

stdlib only; gercek ag YOK; deterministik; saat enjekte.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .display import DISCLAIMER_TEXT

# ---------------------------------------------------------------------------
# Bilesen durumlari (SPEC bolum 3)
# ---------------------------------------------------------------------------
OK = "OK"
MISSING = "MISSING"
STALE = "STALE"
UNVERIFIED = "UNVERIFIED"
FAILED = "FAILED"
NOT_APPLICABLE = "NOT_APPLICABLE"

ALL_STATUSES = (OK, MISSING, STALE, UNVERIFIED, FAILED, NOT_APPLICABLE)

# ---------------------------------------------------------------------------
# Yeterlilik etiketleri (BLOK 9 sufficiency — enjekte string olarak gelir;
# bu modul BLOK 9'a bagimli DEGILDIR, ayni etiket sozlugunu tasir)
# ---------------------------------------------------------------------------
SUFFICIENT_DATA = "SUFFICIENT_DATA"
LIMITED_DATA = "LIMITED_DATA"
NEW_LISTING = "NEW_LISTING"
INSUFFICIENT_FOR_TECHNICAL = "INSUFFICIENT_FOR_TECHNICAL"
PRICE_DATA_MISSING = "PRICE_DATA_MISSING"
REVIEW_REQUIRED = "REVIEW_REQUIRED"

# Yeni halka arz notu (SPEC bolum 9)
NEW_LISTING_NOTE = "Yeni halka arz — sinirli gecmis"

# ---------------------------------------------------------------------------
# 12 bilesen adi + varsayilan agirliklar (SPEC bolum 5, toplam = 100)
# ---------------------------------------------------------------------------
COMPONENT_NAMES = (
    "price_availability",
    "price_source_validation",
    "volume_availability",
    "history_sufficiency",
    "kap_check",
    "news_check",
    "corporate_check",
    "restriction_check",
    "symbol_verification",
    "data_freshness",
    "anomaly_count",
    "critical_fields",
)

DEFAULT_WEIGHTS: Dict[str, float] = {
    "price_availability": 15,
    "price_source_validation": 10,
    "volume_availability": 10,
    "history_sufficiency": 8,
    "kap_check": 8,
    "news_check": 6,
    "corporate_check": 7,
    "restriction_check": 7,
    "symbol_verification": 8,
    "data_freshness": 8,
    "anomaly_count": 8,
    "critical_fields": 5,
}


# ---------------------------------------------------------------------------
# Hata siniflari (her hatanin makine okunur kodu vardir)
# ---------------------------------------------------------------------------
class ConfidenceError(Exception):
    """BLOK 15 temel hata sinifi."""

    code = "CONFIDENCE_ERROR"

    def __init__(self, message: str, **details):
        super().__init__(message)
        self.message = message
        self.details = details


class UnknownComponentError(ConfidenceError):
    """set_weights: tanimli olmayan bilesen adi."""

    code = "UNKNOWN_COMPONENT"


class IncompleteWeightsError(ConfidenceError):
    """set_weights: 12 bilesenin tamami verilmedi."""

    code = "INCOMPLETE_WEIGHTS"


class InvalidWeightSumError(ConfidenceError):
    """set_weights: toplam 100 degil (normalize=False)."""

    code = "INVALID_WEIGHT_SUM"


class NegativeWeightError(ConfidenceError):
    """set_weights: negatif agirlik."""

    code = "NEGATIVE_WEIGHT"


# ---------------------------------------------------------------------------
# Veri modelleri
# ---------------------------------------------------------------------------
@dataclass
class ComponentInput:
    """Bir bilesen degerlendiricisinin ciktisi.

    status: OK | MISSING | STALE | UNVERIFIED | FAILED | NOT_APPLICABLE
    detail: serbest aciklama (bilesene ozgu gerekce)
    """

    status: str
    detail: str = ""

    def __post_init__(self):
        self.status = str(self.status).strip().upper()
        if self.status not in ALL_STATUSES:
            raise ValueError(
                "Gecersiz bilesen durumu: %r (gecerli: %s)"
                % (self.status, ", ".join(ALL_STATUSES))
            )


@dataclass(frozen=True)
class ReadyFlags:
    """Uc hazirlik bayragi (degismez)."""

    technical_ready: bool
    scoring_ready: bool
    favorite_eligible: bool


@dataclass
class ConfidenceResult:
    """BLOK 15 nihai cikti paketi (SPEC bolum 3).

    data_confidence: 0-100 int — verinin tamlik/dogrulama seviyesi.
    disclaimer: ana sayfa aciklama metni (sabit kural — display.py).
    """

    stock_id: str
    data_confidence: int
    technical_ready: bool
    scoring_ready: bool
    favorite_eligible: bool
    missing_fields: List[str] = field(default_factory=list)
    component_scores: Dict[str, dict] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    disclaimer: str = field(default_factory=lambda: DISCLAIMER_TEXT)

    @property
    def ready_flags(self) -> ReadyFlags:
        """Uc hazirlik bayragini degismez paket olarak dondurur."""
        return ReadyFlags(
            technical_ready=self.technical_ready,
            scoring_ready=self.scoring_ready,
            favorite_eligible=self.favorite_eligible,
        )


@dataclass
class ConfidenceConfig:
    """Bilesen agirliklari + esikler + audit izi (SPEC bolum 5).

    weights: 12 bilesenin agirliklari (varsayilan toplam = 100).
    critical_cap: kritik eksik varken confidence ust siniri (vars. 60).
    stale_days_limit: data_freshness icin tazelik siniri (gun, vars. 5).
    config_version: her basarili set_weights ile 1 artar (audit izi).
    audit_log: agirlik degisikligi notlari (deterministik; saat tasimaz).
    """

    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    critical_cap: int = 60
    stale_days_limit: int = 5
    config_version: int = 1
    audit_log: List[dict] = field(default_factory=list)

    # -- dogrulama ----------------------------------------------------------
    def validate_weights(self, weights: Dict[str, float]) -> bool:
        """Bayrak tabanli dogrulama: toplam!=100 (veya baska ihlal) -> False.

        Hata firlatmaz; set_weights'in 'hata' karsiligidir (SPEC bolum 5:
        'toplam!=100 ise hata ya da bayrak; ikisi desteklenir').
        """
        try:
            self._check_weights(weights)
        except ConfidenceError:
            return False
        return float(sum(weights.values())) == 100.0

    def _check_weights(self, weights: Dict[str, float]) -> None:
        """Ortak kural kontrolleri (toplam haric)."""
        if not isinstance(weights, dict) or not weights:
            raise IncompleteWeightsError(
                "weights bos olamaz; 12 bilesenin tamami gerekli"
            )
        unknown = sorted(set(weights) - set(COMPONENT_NAMES))
        if unknown:
            raise UnknownComponentError(
                "Bilinmeyen bilesen adi(lari): %s" % ", ".join(unknown),
                unknown=unknown,
            )
        missing = sorted(set(COMPONENT_NAMES) - set(weights))
        if missing:
            raise IncompleteWeightsError(
                "Eksik bilesen agirlik(lar)i: %s" % ", ".join(missing),
                missing=missing,
            )
        for name, value in weights.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise NegativeWeightError(
                    "Agirlik sayisal olmali: %s=%r" % (name, value)
                )
            if float(value) < 0:
                raise NegativeWeightError(
                    "Negatif agirlik kabul edilmez: %s=%r" % (name, value),
                    component=name,
                    weight=value,
                )

    # -- yonetici paneli ----------------------------------------------------
    def set_weights(self, weights: Dict[str, float], normalize: bool = False) -> None:
        """Agirliklari gunceller (tam degisim; 12 bilesenin tamami gerekli).

        - Bilinmeyen bilesen adi reddedilir (UnknownComponentError).
        - normalize=False: toplam tam 100 olmali, aksi InvalidWeightSumError.
        - normalize=True: toplam 100'e orantili normalize edilir.
        - Basarili degisiklikte config_version artar ve audit notu birakilir.
        """
        self._check_weights(weights)
        total = float(sum(weights.values()))
        if total <= 0:
            raise InvalidWeightSumError(
                "Agirlik toplami pozitif olmali (toplam=%r)" % total
            )
        if normalize:
            factor = 100.0 / total
            new_weights = {name: float(value) * factor for name, value in weights.items()}
        else:
            if total != 100.0:
                raise InvalidWeightSumError(
                    "Agirlik toplami 100 olmali (toplam=%r); normalize=True ile "
                    "orantili dagitim yapilabilir" % total,
                    total=total,
                )
            new_weights = {name: float(value) for name, value in weights.items()}

        self.weights = new_weights
        self.config_version += 1
        self.audit_log.append(
            {
                "version": self.config_version,
                "action": "set_weights",
                "normalized": bool(normalize),
                "previous_total": total,
                "note": "Agirliklar guncellendi (toplam=100, normalize=%s)"
                % ("evet" if normalize else "hayir"),
            }
        )

    @property
    def total_weight(self) -> float:
        return float(sum(self.weights.values()))
