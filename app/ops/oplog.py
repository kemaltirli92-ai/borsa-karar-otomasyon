"""BLOK 21 - Guvenlik, Log, Izleme ve Yedekleme: yapilandirilmis olay gunlugu.

Kurallar ozeti:
- stdlib only; gercek ag/subprocess YOK; JSON-lines ciktisi ASCII guvenli.
- Deterministik: clock enjekte edilir (default UTC now sarici); modulde
  dogrudan datetime.now() cagrisi yapilmaz.
- KAYIT ONCESI redaksiyon: message redact_text, extra redact_mapping'den
  gecer (secret_provider.known_values() + SENSITIVE_KEY_RE). Gizli deger
  ASLA yazilmaz; orijinal extra mapping degistirilmez (kopya).
- Puan kilidi: hicbir log alan adinda / enum uyesinde "puan", "score",
  "sinyal" GECMEZ; bu modul puan/sinyal uretmez.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional

from app.ops.secrets import redact_mapping, redact_text


def _utc_now() -> datetime:
    """Default clock sarici (enjekte clock kullanilmadiginda)."""
    return datetime.now(timezone.utc)


def _iso_z(value) -> str:
    """datetime/ISO string'i ISO-8601 'Z' bicimine cevirir."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        text = value.isoformat()
        return text if text.endswith("Z") else text + "Z"
    text = str(value)
    return text if text.endswith("Z") else text + "Z"


class LogEvent(str, Enum):
    """Operasyon olay tipleri — TAM 19 uye (test: len(LogEvent) == 19)."""

    SCAN_STARTED = "SCAN_STARTED"
    SCAN_FINISHED = "SCAN_FINISHED"
    STOCK_TASK_STATUS = "STOCK_TASK_STATUS"
    SOURCE_REQUEST = "SOURCE_REQUEST"
    SOURCE_HTTP_STATUS = "SOURCE_HTTP_STATUS"
    SOURCE_RESPONSE_TIME = "SOURCE_RESPONSE_TIME"
    SOURCE_RETRY = "SOURCE_RETRY"
    SOURCE_FALLBACK = "SOURCE_FALLBACK"
    PRICE_ROWS_FETCHED = "PRICE_ROWS_FETCHED"
    KAP_COUNT = "KAP_COUNT"
    NEWS_COUNT = "NEWS_COUNT"
    DUPLICATES_ELIMINATED = "DUPLICATES_ELIMINATED"
    WRONG_MATCH = "WRONG_MATCH"
    MISSING_DATA = "MISSING_DATA"
    ABNORMAL_DATA = "ABNORMAL_DATA"
    MANUAL_RESCAN = "MANUAL_RESCAN"
    UNIVERSE_CHANGE = "UNIVERSE_CHANGE"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"
    ADMIN_SETTING_CHANGE = "ADMIN_SETTING_CHANGE"


class OpsLogger:
    """Yapilandirilmis olay gunlugu yazici.

    sink: callable(dict) — default bellek listesi (logger.records).
    clock: callable() -> datetime — default UTC now.
    secret_provider: known_values() saglayan nesne (redaksiyon icin).
    """

    def __init__(
        self,
        sink: Optional[Callable[[dict], None]] = None,
        clock: Optional[Callable[[], datetime]] = None,
        secret_provider=None,
        min_secret_len: int = 4,
    ):
        self.records: List[dict] = []
        self._sink = sink
        self._clock = clock or _utc_now
        self._secret_provider = secret_provider
        self.min_secret_len = min_secret_len

    # ------------------------------------------------------------------ #
    # cekirdek
    # ------------------------------------------------------------------ #
    def _secret_values(self) -> List[str]:
        provider = self._secret_provider
        if provider is None:
            return []
        values = provider.known_values()
        return list(values) if values else []

    def log(
        self,
        event: LogEvent,
        message: str = "",
        *,
        run_id=None,
        symbol=None,
        source=None,
        level: str = "INFO",
        **extra,
    ) -> dict:
        """Olayi redakte edip kaydeder; kayit dict'ini dondurur.

        Sema (sabit alan sirasi korunur):
        {"ts", "level", "event", "run_id", "symbol", "source", "message",
         "extra"}.
        """
        secrets_list = self._secret_values()
        safe_message = redact_text(
            str(message), secrets_list, min_len=self.min_secret_len
        )
        safe_extra = redact_mapping(
            dict(extra), secrets_list, min_len=self.min_secret_len
        )
        record: Dict[str, object] = {
            "ts": _iso_z(self._clock()),
            "level": str(level),
            "event": LogEvent(event).value,
            "run_id": run_id,
            "symbol": symbol,
            "source": source,
            "message": safe_message,
            "extra": safe_extra,
        }
        self.records.append(record)
        if self._sink is not None:
            self._sink(record)
        return record

    def to_json_lines(self) -> str:
        """Her kayit bir satir JSON; ASCII guvenli (ensure_ascii=True)."""
        return "\n".join(
            json.dumps(record, ensure_ascii=True) for record in self.records
        )

    # ------------------------------------------------------------------ #
    # kolaylik metodlari (her biri dogru event'i uretir)
    # ------------------------------------------------------------------ #
    def scan_started(self, run_id) -> dict:
        return self.log(LogEvent.SCAN_STARTED, "tarama basladi", run_id=run_id)

    def scan_finished(self, run_id, status) -> dict:
        return self.log(
            LogEvent.SCAN_FINISHED,
            "tarama bitti",
            run_id=run_id,
            status=status,
        )

    def stock_task(self, run_id, symbol, status, detail="") -> dict:
        return self.log(
            LogEvent.STOCK_TASK_STATUS,
            detail,
            run_id=run_id,
            symbol=symbol,
            status=status,
        )

    def source_request(self, source, url_path) -> dict:
        return self.log(
            LogEvent.SOURCE_REQUEST,
            "kaynak istegi",
            source=source,
            url_path=url_path,
        )

    def http_status(self, source, status_code) -> dict:
        return self.log(
            LogEvent.SOURCE_HTTP_STATUS,
            "http durum kodu",
            source=source,
            status_code=status_code,
        )

    def response_time(self, source, elapsed_ms) -> dict:
        return self.log(
            LogEvent.SOURCE_RESPONSE_TIME,
            "cevap suresi",
            source=source,
            elapsed_ms=elapsed_ms,
        )

    def retry(self, source, attempt, delay_s) -> dict:
        return self.log(
            LogEvent.SOURCE_RETRY,
            "tekrar deneme",
            source=source,
            attempt=attempt,
            delay_s=delay_s,
        )

    def fallback(self, source, from_target, to_target) -> dict:
        return self.log(
            LogEvent.SOURCE_FALLBACK,
            "yedek kaynaga gecis",
            source=source,
            from_target=from_target,
            to_target=to_target,
        )

    def price_rows(self, source, symbol, rows) -> dict:
        return self.log(
            LogEvent.PRICE_ROWS_FETCHED,
            "fiyat satirlari cekildi",
            source=source,
            symbol=symbol,
            rows=rows,
        )

    def kap_count(self, run_id, count) -> dict:
        return self.log(
            LogEvent.KAP_COUNT, "kap kayit sayisi", run_id=run_id, count=count
        )

    def news_count(self, run_id, count) -> dict:
        return self.log(
            LogEvent.NEWS_COUNT, "haber sayisi", run_id=run_id, count=count
        )

    def duplicates_eliminated(self, run_id, count) -> dict:
        return self.log(
            LogEvent.DUPLICATES_ELIMINATED,
            "kopyalar elendi",
            run_id=run_id,
            count=count,
        )

    def wrong_match(self, symbol, expected, matched) -> dict:
        return self.log(
            LogEvent.WRONG_MATCH,
            "yanlis sirket eslesmesi",
            symbol=symbol,
            expected=expected,
            matched=matched,
        )

    def missing_data(self, symbol, field) -> dict:
        return self.log(
            LogEvent.MISSING_DATA,
            "eksik veri",
            symbol=symbol,
            field=field,
        )

    def abnormal_data(self, symbol, field, value) -> dict:
        return self.log(
            LogEvent.ABNORMAL_DATA,
            "anormal veri",
            symbol=symbol,
            field=field,
            value=value,
        )

    def manual_rescan(self, run_id, by, reason) -> dict:
        return self.log(
            LogEvent.MANUAL_RESCAN,
            "elle yeniden tarama",
            run_id=run_id,
            by=by,
            reason=reason,
        )

    def universe_change(self, added, removed) -> dict:
        return self.log(
            LogEvent.UNIVERSE_CHANGE,
            "evren degisikligi",
            added=added,
            removed=removed,
        )

    def symbol_change(self, old, new) -> dict:
        return self.log(
            LogEvent.SYMBOL_CHANGE,
            "sembol degisikligi",
            old=old,
            new=new,
        )

    def admin_setting(self, key, by) -> dict:
        return self.log(
            LogEvent.ADMIN_SETTING_CHANGE,
            "yonetici ayar degisikligi",
            key=key,
            by=by,
        )
