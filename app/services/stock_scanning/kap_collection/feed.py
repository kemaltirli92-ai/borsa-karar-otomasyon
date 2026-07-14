"""BLOK 11 - Merkezi KAP akisi kaynagi (feed.py).

KURAL (SPEC bolum 1/4): Her sabah 100 sirketin 200 profil/bildirim linkini
TEK TEK ACMA YASAK — merkezi akis taranir (fetch_since tek cagri).

KapFeed(fetcher, clock=None):
- fetcher ENJEKTE edilir (gercek ag YOK). Sozlesme:
    fetcher.fetch_feed(cutoff_iso) -> list[dict]
    fetcher.fetch_notification(notification_id) -> dict | None
- fetcher None veya cagri hata verirse KapFeedUnavailableError firlatilir.
- KONTROLSUZ TEKRAR ACMA YASAGI: ayni calisma icinde ayni notification_id
  icin detay TEK KEZ cekilir (calisma-ici onbellek). Yeni calisma icin
  begin_run() cagrilir (collector.collect bunu yapar).

ProfileChecker(checker_fetcher, clock): sirket PROFIL linkleri merkezi
akista ACILMAZ; profil kontrolu haftalik (7 gun) pencerede yapilir. Son
kontrol 7 gunden yeniyse ATLA (PROFILES_SKIPPED_FRESH).

Deterministik: clock enjekte edilebilir.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

# Profil haftalik kontrol penceresi (gun)
WEEKLY_WINDOW_DAYS = 7

# Olay kodlari
PROFILES_CHECKED = "PROFILES_CHECKED"
PROFILES_SKIPPED_FRESH = "PROFILES_SKIPPED_FRESH"
PROFILES_SKIPPED_NO_FETCHER = "PROFILES_SKIPPED_NO_FETCHER"
PROFILES_CHECK_FAILED = "PROFILES_CHECK_FAILED"


def _utcnow_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


class KapFeedUnavailableError(Exception):
    """Merkezi KAP akisina/detayina ulasilamadi (kaynak kesintisi).

    Collector bu hatayi yakalar ve sonuc nesnesinde tasir; fiyat
    taramasina exception olarak SIZMAZ.
    """


class KapFeed:
    """Merkezi KAP bildirim akisi (fetcher enjekte, calisma-ici onbellekli)."""

    def __init__(self, fetcher=None, clock: Optional[Callable[[], str]] = None):
        self.fetcher = fetcher
        self._clock: Callable[[], str] = clock or _utcnow_iso
        # Calisma-ici detay onbellegi: notification_id -> dict | None
        self._detail_cache: Dict[str, Optional[dict]] = {}
        self.detail_fetch_counts: Dict[str, int] = {}
        self.feed_calls: List[str] = []

    # ------------------------------------------------------------------ #
    # Calisma yonetimi
    # ------------------------------------------------------------------ #
    def begin_run(self) -> None:
        """Yeni toplama calismasi: detay onbellegi ve sayaclar sifirlanir."""
        self._detail_cache.clear()
        self.detail_fetch_counts.clear()

    # ------------------------------------------------------------------ #
    # Merkezi akis
    # ------------------------------------------------------------------ #
    def fetch_since(self, cutoff_iso: str) -> List[dict]:
        """Son veri kesiminden (cutoff) sonraki MERKEZI bildirim listesi.

        fetcher'a cutoff iletilir; ayrica savunma amacli istemci tarafinda
        da published_at <= cutoff olan kayitlar elenir.
        """
        if self.fetcher is None:
            raise KapFeedUnavailableError("KAP akisi fetcher'i tanimli degil")
        try:
            items = self.fetcher.fetch_feed(cutoff_iso)
        except KapFeedUnavailableError:
            raise
        except Exception as exc:  # kaynak hatasi -> kesinti sayilir
            raise KapFeedUnavailableError(
                f"KAP merkezi akisi okunamadi: {exc}"
            ) from exc
        self.feed_calls.append(cutoff_iso)
        return [dict(it) for it in (items or []) if self._after_cutoff(it, cutoff_iso)]

    @staticmethod
    def _after_cutoff(item: dict, cutoff_iso: str) -> bool:
        """published_at bilinen kayitlar icin kesim filtresi (ISO metin karsilastirma)."""
        published = item.get("published_at")
        if not published:
            return True
        return str(published) > str(cutoff_iso)

    # ------------------------------------------------------------------ #
    # Bildirim detayi (calisma-ici tek cekim)
    # ------------------------------------------------------------------ #
    def fetch_detail(self, notification_id: str) -> Optional[dict]:
        """Eslesen bildirimin detayi (body, ekler). Ayni id ikinci kez CEKILMEZ.

        None sonuc da onbelleklenir (bos detay tekrar acilmaz).
        """
        if notification_id in self._detail_cache:
            return self._detail_cache[notification_id]
        if self.fetcher is None:
            raise KapFeedUnavailableError("KAP akisi fetcher'i tanimli degil")
        try:
            detail = self.fetcher.fetch_notification(notification_id)
        except KapFeedUnavailableError:
            raise
        except Exception as exc:
            raise KapFeedUnavailableError(
                f"KAP bildirim detayi okunamadi ({notification_id}): {exc}"
            ) from exc
        self._detail_cache[notification_id] = detail
        self.detail_fetch_counts[notification_id] = (
            self.detail_fetch_counts.get(notification_id, 0) + 1
        )
        return detail

    @property
    def total_detail_fetches(self) -> int:
        """Bu calismada fetcher'a giden gercek detay cagri sayisi."""
        return sum(self.detail_fetch_counts.values())


class ProfileChecker:
    """Sirket profil sayfasi haftalik (7 gun) kontrolcu.

    Profil linkleri merkezi akista ACILMAZ; sadece haftalik pencerede
    checker_fetcher ile cekilir. Son kontrol 7 gunden yeniyse ATLANIR
    (PROFILES_SKIPPED_FRESH) — kontrolsuz tekrar acma yasagi profiller
    icin de gecerlidir.
    """

    def __init__(
        self,
        checker_fetcher=None,
        clock: Optional[Callable[[], datetime]] = None,
        window_days: int = WEEKLY_WINDOW_DAYS,
    ):
        self.checker_fetcher = checker_fetcher
        self._clock: Callable[[], datetime] = clock or datetime.now
        self.window_days = int(window_days)
        self._last_checked: Dict[str, datetime] = {}
        self.events: List[dict] = []

    # ------------------------------------------------------------------ #
    def _now(self) -> datetime:
        now = self._clock()
        if isinstance(now, datetime):
            return now
        # date/str geldiyse datetime'a cevirip deterministik kalmak
        return datetime.fromisoformat(str(now))

    def last_checked_at(self, stock_id: str) -> Optional[datetime]:
        return self._last_checked.get(stock_id)

    def mark_checked(self, stock_id: str, at: Optional[datetime] = None) -> None:
        """Son kontrol zamanini disaridan isaretler (test/geri yukleme icin)."""
        self._last_checked[stock_id] = at or self._now()

    def is_fresh(self, stock_id: str, now: Optional[datetime] = None) -> bool:
        """Son kontrol pencere (7 gun) icindeyse True (taze -> atla)."""
        last = self._last_checked.get(stock_id)
        if last is None:
            return False
        ref = now or self._now()
        return (ref - last) < timedelta(days=self.window_days)

    def check(self, stock_ids: List[str]) -> dict:
        """Haftalik profil kontrolu.

        Donus: {"checked": [...], "skipped_fresh": [...],
                "skipped_no_fetcher": [...], "failed": [...]}
        """
        summary: Dict[str, List[str]] = {
            "checked": [],
            "skipped_fresh": [],
            "skipped_no_fetcher": [],
            "failed": [],
        }
        now = self._now()
        for stock_id in stock_ids:
            if self.is_fresh(stock_id, now):
                summary["skipped_fresh"].append(stock_id)
                self.events.append(
                    {"event": PROFILES_SKIPPED_FRESH, "stock_id": stock_id}
                )
                continue
            if self.checker_fetcher is None:
                summary["skipped_no_fetcher"].append(stock_id)
                self.events.append(
                    {"event": PROFILES_SKIPPED_NO_FETCHER, "stock_id": stock_id}
                )
                continue
            try:
                self.checker_fetcher.fetch_profile(stock_id)
            except Exception:
                summary["failed"].append(stock_id)
                self.events.append(
                    {"event": PROFILES_CHECK_FAILED, "stock_id": stock_id}
                )
                continue
            self._last_checked[stock_id] = now
            summary["checked"].append(stock_id)
            self.events.append({"event": PROFILES_CHECKED, "stock_id": stock_id})
        return summary
