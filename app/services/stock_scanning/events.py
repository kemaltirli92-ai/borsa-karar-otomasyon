"""BLOK 20 — Dahili tarama olay modulu (Mobil Uygulama Entegrasyonu).

TAM 3 dahili olay: STOCK_SCAN_COMPLETED, STOCK_SCAN_PARTIAL, STOCK_SCAN_FAILED.

BILDIRIM KILIDI:
- Bu modul MUSTERIYE BILDIRIM GONDERMEZ. Musteriye her adimda bildirim
  gonderilmez; musteri bildirim kurali Bolum 9'da olusturulacaktir.
- Bu modulde musteri bildirimi fonksiyonu YOKTUR: hicbir fonksiyon/oznitelik
  adinda "push", "notification", "telegram" veya "send" gecmez (kilit kurali).
- EventBus yalnizca dahili olay kaydi tutar (kuyruk/log). Isterse bolum 9
  bildirim katmani bu kayitlari okuyup kendi kurallariyla bildirim uretebilir;
  bu modul o isi yapmaz.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional, Union


class ScanEvent(str, Enum):
    """Dahili tarama olaylari — TAM 3 adet (baska olay tanimlanamaz)."""

    STOCK_SCAN_COMPLETED = "STOCK_SCAN_COMPLETED"
    STOCK_SCAN_PARTIAL = "STOCK_SCAN_PARTIAL"
    STOCK_SCAN_FAILED = "STOCK_SCAN_FAILED"


# Olay kaydi semasi: {"event", "run_id", "at", "payload"}
EventRecord = Dict[str, object]


class EventBus:
    """Dahili olay veri yolu: emit() ile olay kaydi tutulur, get_events() ile okunur.

    MUSTERIYE BILDIRIM GONDERMEZ — yalnizca bellek ici kuyruk/log tutar.

    Args:
        clock: ISO zaman damgasi icin saat enjeksiyonu (test dostu).
               Verilmezse UTC sistem saati kullanilir.
    """

    def __init__(self, clock: Optional[Callable[[], datetime]] = None) -> None:
        self._clock: Callable[[], datetime] = clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._events: List[EventRecord] = []
        self._lock = threading.Lock()

    def emit(
        self,
        event: Union[ScanEvent, str],
        run_id: str,
        payload: Optional[Dict[str, object]] = None,
    ) -> EventRecord:
        """Olayi kayda yazar ve yazilan kaydi dondurur.

        - event: ScanEvent uyesi (veya degeri); gecersiz deger ValueError firlatir.
        - run_id: tarama kosusu kimligi (zarf scan_run_id ile ayni deger).
        - payload: istege bagli dahili ek veri (musteriye gonderilmez).

        Musteri bildirimi YAPMAZ — sadece kuyruga/log'a yazar.
        """
        if isinstance(event, str):
            event = ScanEvent(event)  # gecersiz deger -> ValueError
        if not isinstance(event, ScanEvent):
            raise TypeError(f"event ScanEvent olmali, gelen: {type(event)!r}")
        record: EventRecord = {
            "event": event.value,
            "run_id": run_id,
            "at": self._clock().isoformat(),
            "payload": dict(payload) if payload else {},
        }
        with self._lock:
            self._events.append(record)
        return record

    def get_events(self, run_id: Optional[str] = None) -> List[EventRecord]:
        """Kayitlari dondurur; run_id verilirse yalnizca o kosuya ait kayitlar."""
        with self._lock:
            events = list(self._events)
        if run_id is None:
            return events
        return [rec for rec in events if rec["run_id"] == run_id]
