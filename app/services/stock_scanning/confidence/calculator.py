"""BLOK 15 - Guven hesaplayici (calculator.py).

ConfidenceCalculator: 12 bilesen ComponentInput'unu agirlikli toplama
cevirip nihai cikti paketini (ConfidenceResult) uretir.

Kurallar (SPEC BLOK 15 bolum 6):
- Bilesen katsayilari: OK=1.0, NOT_APPLICABLE=1.0 (agirlik dagitim disi —
  kalan agirliklar orantili yeniden dagitilir), UNVERIFIED=0.5, STALE=0.5,
  MISSING=0.0, FAILED=0.0.
- EKSIK ALAN SIFIR VERI GIBI KABUL EDILMEZ: MISSING bilesen 0 katsayi ile
  girer ama var gibi sayilmaz; missing_fields listesine yazilir ve
  confidence otomatik 100 OLAMAZ (en fazla 99).
- data_confidence = round(aktif agirlikli toplam / aktif agirlik toplami
  * 100) — 0-100 int.
- Kritik eksik (critical_fields FAILED) varsa: confidence ust siniri
  (config.critical_cap, vars. 60) + "KRITIK VERI EKSIK" uyarisi +
  favorite_eligible=False (kati) + scoring_ready=False (kati).
- STALE bilesen(ler) varsa: "ESKI VERI" uyarisi + favorite_eligible=False.
- Yeni halka arz (NEW_LISTING): favorite_eligible=False +
  "Yeni halka arz — sinirli gecmis" notu (readiness verdict'inden).

Hazirlik bayraklari readiness.py ReadinessVerdict'inden gelir; calculator
kati kurallari (kritik eksik / STALE / yeni halka arz) verdict tutarsiz
olsa bile yeniden uygular (savunma derinligi).

stdlib only; gercek ag YOK; deterministik; saat enjekte.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .display import DISCLAIMER_TEXT
from .models import (
    COMPONENT_NAMES,
    FAILED,
    MISSING,
    NOT_APPLICABLE,
    OK,
    STALE,
    UNVERIFIED,
    ComponentInput,
    ConfidenceConfig,
    ConfidenceResult,
)
from .readiness import ReadinessVerdict

# Bilesen katsayilari (SPEC bolum 6)
COEFFICIENTS = {
    OK: 1.0,
    NOT_APPLICABLE: 1.0,
    UNVERIFIED: 0.5,
    STALE: 0.5,
    MISSING: 0.0,
    FAILED: 0.0,
}

# Uyari metinleri (SPEC bolum 6 — sabit)
WARNING_CRITICAL_DATA = "KRITIK VERI EKSIK"
WARNING_STALE_DATA = "ESKI VERI"

CRITICAL_COMPONENT = "critical_fields"


class ConfidenceCalculator:
    """Agirlikli guven toplami + hazirlik paketi uretici."""

    def __init__(self, config: Optional[ConfidenceConfig] = None):
        self.config = config or ConfidenceConfig()

    # ------------------------------------------------------------------ #
    # Yardimcilar
    # ------------------------------------------------------------------ #
    def _component(self, components: Dict[str, ComponentInput], name: str) -> ComponentInput:
        """Bileseni getirir; pakette yoksa MISSING sayilir (girdi eksigi)."""
        comp = components.get(name)
        if comp is None:
            return ComponentInput(MISSING, "bilesen girdisi yok")
        return comp

    # ------------------------------------------------------------------ #
    # Ana hesap
    # ------------------------------------------------------------------ #
    def calculate(
        self,
        stock_id: str,
        components: Dict[str, ComponentInput],
        verdict: ReadinessVerdict,
    ) -> ConfidenceResult:
        """Bilesenler + hazirlik karari -> ConfidenceResult (0-100 int)."""
        weights = self.config.weights

        # NOT_APPLICABLE bilesenler dagitim disi: kalan agirliklar orantili
        # yeniden dagitilir (aktif agirlik toplami uzerinden).
        active = [
            name
            for name in COMPONENT_NAMES
            if self._component(components, name).status != NOT_APPLICABLE
        ]
        active_weight = sum(float(weights.get(name, 0.0)) for name in active)

        component_scores: Dict[str, dict] = {}
        weighted_sum = 0.0
        for name in COMPONENT_NAMES:
            comp = self._component(components, name)
            weight = float(weights.get(name, 0.0))
            coefficient = COEFFICIENTS[comp.status]
            is_active = comp.status != NOT_APPLICABLE
            contribution = 0.0
            if is_active and active_weight > 0:
                contribution = weight * coefficient / active_weight * 100.0
                weighted_sum += weight * coefficient
            component_scores[name] = {
                "status": comp.status,
                "coefficient": coefficient,
                "weight": weight,
                "active": is_active,
                "contribution": round(contribution, 4),
            }

        if active_weight > 0:
            raw = weighted_sum / active_weight * 100.0
        else:
            # Tum bilesenler NOT_APPLICABLE: eksik veri yok, ust sinir 100.
            raw = 100.0
        confidence = int(round(raw))

        # MISSING bilesenler: var gibi sayilmaz, listeye yazilir.
        missing_fields: List[str] = [
            name
            for name in COMPONENT_NAMES
            if self._component(components, name).status == MISSING
        ]
        stale_components: List[str] = [
            name
            for name in COMPONENT_NAMES
            if self._component(components, name).status == STALE
        ]
        critical_missing = (
            self._component(components, CRITICAL_COMPONENT).status == FAILED
        )

        # MISSING varken confidence otomatik 100 OLAMAZ.
        if missing_fields:
            confidence = min(confidence, 99)
        # Kritik eksik varsa ust sinir (vars. 60).
        if critical_missing:
            confidence = min(confidence, int(self.config.critical_cap))
        confidence = max(0, min(100, confidence))

        # Uyarilar (sabit metinler + readiness notlari; tekrarsiz, sirali)
        warnings: List[str] = []
        if critical_missing:
            warnings.append(WARNING_CRITICAL_DATA)
        if stale_components:
            warnings.append(WARNING_STALE_DATA)
        for note in verdict.notes:
            if note not in warnings:
                warnings.append(note)

        # Kati kurallar: verdict tutarsiz olsa bile uygulanir.
        # SPEC bolum 9: restriction_check FAILED ise scoring_ready=False
        # (technical_ready etkilenmez — o verdict'ten oldugu gibi gelir).
        restriction_failed = (
            self._component(components, "restriction_check").status == FAILED
        )
        scoring_ready = (
            bool(verdict.scoring_ready)
            and not critical_missing
            and not restriction_failed
        )
        favorite_eligible = (
            bool(verdict.favorite_eligible)
            and not critical_missing
            and not stale_components
            and not verdict.new_listing
        )

        return ConfidenceResult(
            stock_id=stock_id,
            data_confidence=confidence,
            technical_ready=bool(verdict.technical_ready),
            scoring_ready=scoring_ready,
            favorite_eligible=favorite_eligible,
            missing_fields=missing_fields,
            component_scores=component_scores,
            warnings=warnings,
            disclaimer=DISCLAIMER_TEXT,
        )
