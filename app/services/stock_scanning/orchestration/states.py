"""BLOK 14 - Hisse tarama durum makinesi.

- ScanState: TAM 11 durum.
- TRANSITIONS: izinli gecis tablosu; tablo disi gecis InvalidTransitionError.
- INACTIVE: pasif/arsiv hisse, hicbir toplama asamasina giremez.
- FAILED -> WAITING yalnizca bilincli yeniden taramada (reason=conscious_rescan).

Not: 5 kaynak asamasi sirayla yurudugu icin COLLECTING_* zinciri
(COLLECTING_PRICE -> COLLECTING_KAP -> ... -> COLLECTING_RESTRICTIONS)
izinli gecisler arasindadir; her COLLECTING_* ayrica VALIDATING/PARTIAL_DATA/FAILED
durumlarina gecebilir.

stdlib only; saat enjekte; gercek ag YOK.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, FrozenSet, List, Optional


class ScanState(str, Enum):
    """Hisse tarama durumlari (TAM 11)."""

    WAITING = "WAITING"
    COLLECTING_PRICE = "COLLECTING_PRICE"
    COLLECTING_KAP = "COLLECTING_KAP"
    COLLECTING_NEWS = "COLLECTING_NEWS"
    COLLECTING_ACTIONS = "COLLECTING_ACTIONS"
    COLLECTING_RESTRICTIONS = "COLLECTING_RESTRICTIONS"
    VALIDATING = "VALIDATING"
    READY = "READY"
    PARTIAL_DATA = "PARTIAL_DATA"
    FAILED = "FAILED"
    INACTIVE = "INACTIVE"


# Bilincli yeniden tarama nedeni (FAILED -> WAITING icin zorunlu).
CONSCIOUS_RESCAN_REASON = "conscious_rescan"

_COLLECTING_STATES: FrozenSet[ScanState] = frozenset(
    {
        ScanState.COLLECTING_PRICE,
        ScanState.COLLECTING_KAP,
        ScanState.COLLECTING_NEWS,
        ScanState.COLLECTING_ACTIONS,
        ScanState.COLLECTING_RESTRICTIONS,
    }
)

_TERMINAL_STATES: FrozenSet[ScanState] = frozenset(
    {ScanState.READY, ScanState.PARTIAL_DATA, ScanState.FAILED}
)

# Izinli gecis tablosu (SPEC BLOK 14 bolum 4 + 5-asamali toplama zinciri).
TRANSITIONS: Dict[ScanState, FrozenSet[ScanState]] = {
    ScanState.WAITING: frozenset(
        {
            ScanState.COLLECTING_PRICE,
            ScanState.COLLECTING_KAP,
            ScanState.COLLECTING_NEWS,
            ScanState.COLLECTING_ACTIONS,
            ScanState.COLLECTING_RESTRICTIONS,
            ScanState.INACTIVE,  # beklemedeki hisse pasife alinabilir
        }
    ),
    ScanState.COLLECTING_PRICE: frozenset(
        {
            ScanState.COLLECTING_KAP,
            ScanState.VALIDATING,
            ScanState.PARTIAL_DATA,
            ScanState.FAILED,
        }
    ),
    ScanState.COLLECTING_KAP: frozenset(
        {
            ScanState.COLLECTING_NEWS,
            ScanState.VALIDATING,
            ScanState.PARTIAL_DATA,
            ScanState.FAILED,
        }
    ),
    ScanState.COLLECTING_NEWS: frozenset(
        {
            ScanState.COLLECTING_ACTIONS,
            ScanState.VALIDATING,
            ScanState.PARTIAL_DATA,
            ScanState.FAILED,
        }
    ),
    ScanState.COLLECTING_ACTIONS: frozenset(
        {
            ScanState.COLLECTING_RESTRICTIONS,
            ScanState.VALIDATING,
            ScanState.PARTIAL_DATA,
            ScanState.FAILED,
        }
    ),
    ScanState.COLLECTING_RESTRICTIONS: frozenset(
        {
            ScanState.VALIDATING,
            ScanState.PARTIAL_DATA,
            ScanState.FAILED,
        }
    ),
    ScanState.VALIDATING: frozenset(
        {
            ScanState.READY,
            ScanState.PARTIAL_DATA,
            ScanState.FAILED,
        }
    ),
    ScanState.PARTIAL_DATA: frozenset(
        {
            ScanState.VALIDATING,  # recovery sonrasi yeniden dogrulama
            ScanState.READY,
        }
    ),
    ScanState.FAILED: frozenset(
        {
            ScanState.WAITING,  # yalnizca bilincli yeniden taramada
        }
    ),
    ScanState.READY: frozenset(),  # terminal
    ScanState.INACTIVE: frozenset(),  # hicbir toplama asamasina giremez
}


class InvalidTransitionError(Exception):
    """TRANSITIONS tablosunda olmayan gecis denemesi."""

    def __init__(self, from_state: ScanState, to_state: ScanState, reason: str = "") -> None:
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason
        msg = f"Gecersiz gecis: {from_state.value} -> {to_state.value}"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)


def can_transition(
    from_state: ScanState, to_state: ScanState, *, reason: Optional[str] = None
) -> bool:
    """Gecis tabloya gore izinli mi? FAILED->WAITING icin bilincli neden zorunlu."""
    if to_state not in TRANSITIONS.get(from_state, frozenset()):
        return False
    if from_state is ScanState.FAILED and to_state is ScanState.WAITING:
        return reason == CONSCIOUS_RESCAN_REASON
    return True


def assert_transition(
    from_state: ScanState, to_state: ScanState, *, reason: Optional[str] = None
) -> None:
    """Izinsiz geciste InvalidTransitionError firlat."""
    if not can_transition(from_state, to_state, reason=reason):
        if from_state is ScanState.FAILED and to_state is ScanState.WAITING:
            detail = "FAILED->WAITING yalnizca bilincli yeniden taramada"
        else:
            detail = "izinli gecis degil"
        raise InvalidTransitionError(from_state, to_state, detail)


@dataclass
class StockScanStatus:
    """Tek hissenin tarama durumu (SPEC BLOK 14 bolum 4 alanlari)."""

    stock_id: str
    state: ScanState = ScanState.WAITING
    phase: Optional[str] = None
    updated_at: Optional[datetime] = None
    error: Optional[str] = None
    attempts: int = 0
    source_used: Optional[str] = None
    history: List[ScanState] = field(default_factory=list)
    partial_reasons: List[str] = field(default_factory=list)

    def transition(
        self,
        to_state: ScanState,
        *,
        reason: Optional[str] = None,
        at: Optional[datetime] = None,
        error: Optional[str] = None,
    ) -> None:
        """Durumu guncelle; izinsiz gecis InvalidTransitionError."""
        assert_transition(self.state, to_state, reason=reason)
        self.history.append(self.state)
        self.state = to_state
        if error is not None:
            self.error = error
        if at is not None:
            self.updated_at = at

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_STATES

    @property
    def is_collecting(self) -> bool:
        return self.state in _COLLECTING_STATES
