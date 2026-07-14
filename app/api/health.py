"""BLOK 22 - Health endpoint (health.py) — BLOK 16 handler deseniyle.

Izleme ucu: GET /health -> {"status":"ok","version":...,"time":ISO,
"uptime_s":int,"disk":{"used_pct":..,"level":..},"checks":{"api":"ok"}}.

Kurallar:
- Auth YOKTUR (izleme ucu); govdede sir/token/gizli deger TASINMAZ.
- Disk bilgisi BLOK 21 disk.check_disk_usage ile uretilir
  (stat_provider ENJEKTE edilebilir; testlerde sahte istatistik).
- Saat ENJEKTE edilir (clock); modul icinde dogrudan datetime.now()
  cagrisi YOKTUR (default parametre olarak enjekte clock referansi).
- stdlib only; gercek ag/soket YOK (BLOK 16 Request/Response deseni).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional, Tuple

from app.api.router import Request, Response
from app.ops.disk import check_disk_usage

DEFAULT_VERSION = "1.0.0"


def _iso(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class HealthHandlers:
    """GET /health handler'i (auth'suz izleme ucu).

    clock              : () -> datetime (ENJEKTE; deterministik testlerde
                         sabit saat). Default parametre olarak enjekte
                         clock referansi; govdede datetime.now() cagrisi YOK.
    disk_stat_provider : (path) -> (total, used, free) — BLOK 21
                         check_disk_usage'e iletilir (ENJEKTE).
    version            : servis surum etiketi (govdede sir YOK).
    started_at         : servis baslangic damgasi (datetime veya ISO str);
                         None ise uptime_s=0.
    """

    def __init__(
        self,
        clock: Optional[Callable[[], datetime]] = None,
        disk_stat_provider: Optional[Callable[[str], Tuple[int, int, int]]] = None,
        version: str = DEFAULT_VERSION,
        started_at: Optional[Any] = None,
    ) -> None:
        self._clock: Callable[[], datetime] = clock or datetime.now
        self._disk_stat_provider = disk_stat_provider
        self._version = str(version)
        self._started_at = started_at

    def _uptime_seconds(self, now: datetime) -> int:
        if self._started_at is None:
            return 0
        started = self._started_at
        if not isinstance(started, datetime):
            try:
                started = datetime.fromisoformat(str(started))
            except ValueError:
                return 0
        delta = (now - started).total_seconds()
        return max(0, int(delta))

    def health(self, request: Request) -> Response:
        """Health govdesini uretir (govdede sir/token YOK)."""
        now = self._clock()
        disk = check_disk_usage("/", stat_provider=self._disk_stat_provider)
        body = {
            "status": "ok",
            "version": self._version,
            "time": _iso(now),
            "uptime_s": self._uptime_seconds(now),
            "disk": {"used_pct": disk.used_pct, "level": disk.level},
            "checks": {"api": "ok"},
        }
        return Response(200, body)

    def register(self, router: Any) -> None:
        """GET /health ucunu router'a kaydeder (auth YOK — izleme ucu)."""
        router.register("GET", "/health", self.health)
