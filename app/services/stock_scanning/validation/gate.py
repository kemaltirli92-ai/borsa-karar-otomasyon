"""BLOK 9 - ReleaseGate: analiz modullerine gecis gecidi (gate.py).

SPEC BLOK 9 bolum 9.

- release_for_analysis(series_verdict, sufficiency) -> ReleaseDecision:
  sadece VALIDATED (ve izin verilen CLEAN) barlar analiz modullerine
  gecer. REJECTED / REVIEW_REQUIRED barlar CIKARILIR ve sayilari
  raporlanir.
- INSUFFICIENT_FOR_TECHNICAL / PRICE_DATA_MISSING yeterliliginde
  allowed=False (analiz modulu cagrilmaz) ve GATE_BLOCKED loglanir.
- Serbest birakimda GATE_RELEASED loglanir; hic gecer bar yoksa
  yine GATE_BLOCKED (NO_RELEASABLE_BARS).

Gecit karari her zaman loglanir (events listesi + opsiyonel logger).
Gercek ag YOK; stdlib only; deterministik.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from .rules import LayerStatus
from .sufficiency import INSUFFICIENT_FOR_TECHNICAL, PRICE_DATA_MISSING

GATE_RELEASED = "GATE_RELEASED"
GATE_BLOCKED = "GATE_BLOCKED"
NO_RELEASABLE_BARS = "NO_RELEASABLE_BARS"

BLOCKING_SUFFICIENCY = (INSUFFICIENT_FOR_TECHNICAL, PRICE_DATA_MISSING)


@dataclass
class ReleaseDecision:
    """Gecit karari.

    bars: analize birakilan HAM bar nesneleri (degistirilmez).
    rejected_count / review_count: cikarilan bar sayilari (raporlanir).
    excluded_count: diger elenenler (or. RAW veya izinsiz CLEAN).
    """

    allowed: bool
    bars: List[Any] = field(default_factory=list)
    reason: str = ""
    released_count: int = 0
    rejected_count: int = 0
    review_count: int = 0
    excluded_count: int = 0
    blocked_reason: Optional[str] = None


class ReleaseGate:
    """Analiz modullerine sadece dogrulanmis veriyi birakan gecit."""

    def __init__(self, allow_clean: bool = False, logger=None):
        """
        allow_clean: True ise CLEAN (henuz VALIDATED olmayan) barlar da
        analize birakilabilir ("izinli CLEAN"). Varsayilan False.
        """
        self.allow_clean = bool(allow_clean)
        self._logger = logger
        self.events: List[dict] = []

    # ------------------------------------------------------------------ #
    # Loglama
    # ------------------------------------------------------------------ #
    def _log(self, code: str, **fields) -> None:
        event = {"event": code}
        event.update(fields)
        self.events.append(event)
        lg = self._logger
        if lg is None:
            return
        if callable(lg):
            lg(code, dict(fields))
        elif hasattr(lg, "info"):
            lg.info("%s | %s", code, fields)

    def events_by_code(self, code: str) -> List[dict]:
        return [e for e in self.events if e["event"] == code]

    # ------------------------------------------------------------------ #
    # Gecit
    # ------------------------------------------------------------------ #
    @staticmethod
    def _sufficiency_status(sufficiency) -> str:
        status = getattr(sufficiency, "status", sufficiency)
        return str(status)

    @staticmethod
    def _verdicts(series_verdict) -> List[Any]:
        verdicts = getattr(series_verdict, "bar_verdicts", series_verdict)
        return list(verdicts)

    def release_for_analysis(self, series_verdict, sufficiency) -> ReleaseDecision:
        """Seri + yeterlilik kararina gore analiz birakimi.

        Yeterlilik engelleyici ise (INSUFFICIENT_FOR_TECHNICAL /
        PRICE_DATA_MISSING) analiz modulu CAGRILMAZ: allowed=False,
        bars=[] ve GATE_BLOCKED loglanir.
        """
        suff_status = self._sufficiency_status(sufficiency)

        if suff_status in BLOCKING_SUFFICIENCY:
            decision = ReleaseDecision(
                allowed=False,
                bars=[],
                reason=suff_status,
                blocked_reason=suff_status,
            )
            self._log(
                GATE_BLOCKED,
                reason=suff_status,
                released=0,
            )
            return decision

        allowed_statuses = {LayerStatus.VALIDATED.value}
        if self.allow_clean:
            allowed_statuses.add(LayerStatus.CLEAN.value)

        passed: List[Any] = []
        rejected = 0
        review = 0
        excluded = 0
        for verdict in self._verdicts(series_verdict):
            status = getattr(verdict, "status", None)
            sv = status.value if isinstance(status, LayerStatus) else str(status)
            if sv in allowed_statuses:
                passed.append(getattr(verdict, "bar", verdict))
            elif sv == LayerStatus.REJECTED.value:
                rejected += 1
            elif sv == LayerStatus.REVIEW_REQUIRED.value:
                review += 1
            else:
                excluded += 1

        if not passed:
            decision = ReleaseDecision(
                allowed=False,
                bars=[],
                reason=NO_RELEASABLE_BARS,
                rejected_count=rejected,
                review_count=review,
                excluded_count=excluded,
                blocked_reason=NO_RELEASABLE_BARS,
            )
            self._log(
                GATE_BLOCKED,
                reason=NO_RELEASABLE_BARS,
                released=0,
                rejected=rejected,
                review=review,
                excluded=excluded,
            )
            return decision

        decision = ReleaseDecision(
            allowed=True,
            bars=passed,
            reason="OK",
            released_count=len(passed),
            rejected_count=rejected,
            review_count=review,
            excluded_count=excluded,
        )
        self._log(
            GATE_RELEASED,
            released=len(passed),
            rejected=rejected,
            review=review,
            excluded=excluded,
            allow_clean=self.allow_clean,
        )
        return decision
