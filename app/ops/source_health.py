"""BLOK 21 - Guvenlik, Log, Izleme ve Yedekleme: kaynak saglik ekrani + 3-hata uyarisi.

Kurallar ozeti:
- stdlib only; gercek ag/subprocess YOK.
- Deterministik: clock enjekte edilir (default UTC now sarici); zaman
  damgalari ISO-8601 'Z' biciminde yazilir.
- Esik kurali: consecutive_errors == warn_threshold oldugunda TEK uyari;
  4./5. hata yeni uyari URETMEZ; record_success sifirladiktan sonra esige
  tekrar ulasilinca yeni uyari olur.
- Yonetici uyarilari dahili kayit listesidir (warnings); musteriye
  bildirim/push/telegram GONDERILMEZ (bildirim kilidi).
- Hata mesajlari kayit oncesi redact_text'ten gecer (opsiyonel
  secret_provider); gizli deger ASLA yazilmaz.
- Puan kilidi: bu modul puan/sinyal uretmez.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from app.ops.secrets import redact_text


def _utc_now() -> datetime:
    """Default clock sarici (enjekte clock kullanilmadiginda)."""
    return datetime.now(timezone.utc)


def _iso_z(value) -> str:
    """datetime'i ISO-8601 'Z' bicimine cevirir."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        text = value.isoformat()
        return text if text.endswith("Z") else text + "Z"
    text = str(value)
    return text if text.endswith("Z") else text + "Z"


@dataclass(frozen=True)
class SourceHealth:
    """Tek kaynagin anlik saglik goruntusu (degistirilemez)."""

    name: str
    active: bool
    consecutive_errors: int
    last_success_at: Optional[str]
    last_error_at: Optional[str]
    last_error_message: Optional[str]
    last_response_ms: Optional[float]


class SourceHealthRegistry:
    """Kaynak saglik kaydi + esikte TEK yonetici uyarisi.

    warning_sink: callable(dict) — default dahili liste (.warnings).
    """

    def __init__(
        self,
        clock: Optional[Callable[[], datetime]] = None,
        warn_threshold: int = 3,
        warning_sink: Optional[Callable[[dict], None]] = None,
        secret_provider=None,
    ):
        self._clock = clock or _utc_now
        self.warn_threshold = int(warn_threshold)
        self._warning_sink = warning_sink
        self._secret_provider = secret_provider
        self.warnings: List[dict] = []
        self._states: Dict[str, dict] = {}

    # ------------------------------------------------------------------ #
    # ic yardimcilar
    # ------------------------------------------------------------------ #
    def _now_iso(self) -> str:
        return _iso_z(self._clock())

    def _state(self, name: str) -> dict:
        if name not in self._states:
            self.register(name)
        return self._states[name]

    def _snapshot(self, state: dict) -> SourceHealth:
        return SourceHealth(
            name=state["name"],
            active=state["active"],
            consecutive_errors=state["consecutive_errors"],
            last_success_at=state["last_success_at"],
            last_error_at=state["last_error_at"],
            last_error_message=state["last_error_message"],
            last_response_ms=state["last_response_ms"],
        )

    def _redact(self, message: str) -> str:
        if self._secret_provider is None:
            return str(message)
        return redact_text(str(message), self._secret_provider.known_values())

    def _emit_warning(self, state: dict) -> None:
        warning = {
            "type": "SOURCE_UNHEALTHY",
            "source": state["name"],
            "consecutive_errors": state["consecutive_errors"],
            "at": self._now_iso(),
        }
        self.warnings.append(warning)
        if self._warning_sink is not None:
            self._warning_sink(warning)

    # ------------------------------------------------------------------ #
    # genel API
    # ------------------------------------------------------------------ #
    def register(self, name: str) -> None:
        """Kaynagi kaydet (varsa dokunma; kayit sirasi korunur)."""
        if name in self._states:
            return
        self._states[name] = {
            "name": name,
            "active": True,
            "consecutive_errors": 0,
            "last_success_at": None,
            "last_error_at": None,
            "last_error_message": None,
            "last_response_ms": None,
        }

    def record_success(
        self, name: str, response_ms: Optional[float] = None
    ) -> SourceHealth:
        """Basari kaydet: hata sayacini sifirlar; kaynak yoksa oto-register."""
        state = self._state(name)
        state["consecutive_errors"] = 0
        state["last_success_at"] = self._now_iso()
        if response_ms is not None:
            state["last_response_ms"] = response_ms
        return self._snapshot(state)

    def record_error(
        self, name: str, message: str, response_ms: Optional[float] = None
    ) -> SourceHealth:
        """Hata kaydet: sayaci artirir; esige ULASILDIGINDA (==) TEK uyari.

        4./5. hata tekrar uyari uretmez; record_success ile sifirlandiktan
        sonra esige yeniden ulasilinca yeni uyari olusur.
        """
        state = self._state(name)
        state["consecutive_errors"] += 1
        state["last_error_at"] = self._now_iso()
        state["last_error_message"] = self._redact(message)
        if response_ms is not None:
            state["last_response_ms"] = response_ms
        if state["consecutive_errors"] == self.warn_threshold:
            self._emit_warning(state)
        return self._snapshot(state)

    def set_active(self, name: str, active: bool) -> None:
        """Kaynagi aktif/pasif isaretle (yoksa oto-register)."""
        state = self._state(name)
        state["active"] = bool(active)

    def get(self, name: str) -> SourceHealth:
        """Kaynagin anlik goruntusu (yoksa oto-register)."""
        return self._snapshot(self._state(name))

    def screen(self) -> List[dict]:
        """Ekran satirlari: kayit sirasi; her satir SourceHealth alan dict'i."""
        return [asdict(self._snapshot(state)) for state in self._states.values()]
