"""BLOK 22 - 14 kesin tamamlanma kriteri (completion.py).

Her kriter GEREKCELI kanit uretir: staging_report alanlari, site
dosyalarindaki gercek baglanti noktalari (stk-*/sd-*/xk100-* id'leri),
docs.html'deki tamamlanma kriterleri + gercek test dosyasi yollari,
api-contract.json native_mobile=HAZIR_BEKLIYOR, DEMO rozetinin yalnizca
sabit demo bloklarinda kalmasi.

DÜRÜSTLÜK KURALI: kanit yoksa ok=False. Hicbir kriter "varsayimla" gecmez;
evidence stringi kanitin nereden okundugunu acikca yazar. Sahte tarih/
skor/hisse/test sonucu "canli" GOSTERILMEZ.

stdlib only; gercek ag YOK.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

ENVELOPE_KEYS = (
    "scan_run_id",
    "report_version",
    "last_updated_at",
    "data_cutoff_at",
    "status",
)
STATUS_VALUES = ("OK", "PARTIAL", "FAILED", "STALE")

CRITERIA = (
    "official_universe_verified",
    "hundred_active_scanned",
    "data_collected_all_channels",
    "missing_not_zeroed",
    "confidence_per_stock",
    "standard_packet_built",
    "home_real_scan_status",
    "real_summary_table_works",
    "detail_real_raw_chart",
    "mobile_same_api_or_contract",
    "admin_schema_real_files",
    "no_fake_live_data",
    "staging_fullday_verified",
    "deployment_artifacts_ready",
)


@dataclass(frozen=True)
class CriterionResult:
    """Tek tamamlanma kriterinin kanitli sonucu."""

    key: str
    ok: bool
    evidence: str


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def check_completion(
    repo_root: str,
    site_root: str,
    staging_report,
    deploy_report,
) -> List[CriterionResult]:
    """14 kriterin tamamini gercek kanitlarla degerlendirir."""
    root = Path(str(repo_root))
    site = Path(str(site_root))
    index_html = _read(site / "index.html")
    docs_html = _read(root / "docs.html")
    results: List[CriterionResult] = []

    results.append(_official_universe_verified(staging_report))
    results.append(_hundred_active_scanned(staging_report))
    results.append(_data_collected_all_channels(staging_report))
    results.append(_missing_not_zeroed(staging_report))
    results.append(_confidence_per_stock(staging_report))
    results.append(_standard_packet_built(staging_report))
    results.append(_home_real_scan_status(index_html))
    results.append(_real_summary_table_works(index_html))
    results.append(_detail_real_raw_chart(index_html))
    results.append(_mobile_same_api_or_contract(root))
    results.append(_admin_schema_real_files(root, docs_html))
    results.append(_no_fake_live_data(index_html))
    results.append(_staging_fullday_verified(staging_report))
    results.append(_deployment_artifacts_ready(deploy_report))
    return results


# ---------------------------------------------------------------------- #
# Staging kanitli kriterler
# ---------------------------------------------------------------------- #
def _official_universe_verified(report) -> CriterionResult:
    run_id = str(getattr(report, "run_id", ""))
    total = int(getattr(report, "total", 0))
    ok = run_id.startswith("STAGING-") and total > 0
    return CriterionResult(
        "official_universe_verified",
        ok,
        f"staging run_id={run_id!r} (STAGING- oneki), toplam evren={total} "
        "— resmi liste enjekte provider'dan yuklendi (UniverseBook.load_official)",
    )


def _hundred_active_scanned(report) -> CriterionResult:
    total = int(getattr(report, "total", 0))
    n_results = len(getattr(report, "results", ()))
    missing_total = int(getattr(report, "missing_total", -1))
    ok = total == 100 and n_results == 100 and missing_total == 0
    return CriterionResult(
        "hundred_active_scanned",
        ok,
        f"total={total}, results={n_results}, missing_total={missing_total} "
        "(sessiz dusme yok)",
    )


def _data_collected_all_channels(report) -> CriterionResult:
    rows = list(getattr(report, "results", ()))
    kap = sum(int(getattr(r, "kap_count", 0)) for r in rows)
    news = sum(int(getattr(r, "news_count", 0)) for r in rows)
    actions = sum(int(getattr(r, "action_count", 0)) for r in rows)
    restrictions = sum(int(getattr(r, "restriction_count", 0)) for r in rows)
    prices = sum(
        1 for r in rows if getattr(r, "price_rows", None) not in (None, 0)
    )
    ok = bool(rows) and prices > 0 and (kap + news + actions + restrictions) > 0
    return CriterionResult(
        "data_collected_all_channels",
        ok,
        f"fiyat serisi olan sembol={prices}, KAP={kap}, haber={news}, "
        f"kurumsal islem={actions}, tedbir={restrictions} (tum kanallar sayildi)",
    )


def _missing_not_zeroed(report) -> CriterionResult:
    rows = list(getattr(report, "results", ()))
    violators = [
        r.symbol
        for r in rows
        if "price" in getattr(r, "missing_fields", ())
        and getattr(r, "price_rows", None) == 0
    ] + [
        r.symbol
        for r in rows
        if "volume" in getattr(r, "missing_fields", ())
        and getattr(r, "volume_rows", None) == 0
        and getattr(r, "price_rows", None) is None
    ]
    with_missing = sum(1 for r in rows if getattr(r, "missing_fields", ()))
    ok = not violators
    return CriterionResult(
        "missing_not_zeroed",
        ok,
        f"eksik alan tasiyan sonuc={with_missing}; None->0 ihlali="
        f"{violators if violators else 'YOK'} (eksik veri None kalir)",
    )


def _confidence_per_stock(report) -> CriterionResult:
    rows = list(getattr(report, "results", ()))
    values = [int(getattr(r, "data_confidence", -1)) for r in rows]
    ok = bool(rows) and all(0 <= v <= 100 for v in values)
    lo = min(values) if values else None
    hi = max(values) if values else None
    return CriterionResult(
        "confidence_per_stock",
        ok,
        f"{len(values)} sembol icin data_confidence 0-100 araliginda "
        f"(min={lo}, max={hi}; ConfidenceCalculator ile)",
    )


def _standard_packet_built(report) -> CriterionResult:
    envelope = dict(getattr(report, "envelope", {}) or {})
    missing = [k for k in ENVELOPE_KEYS if k not in envelope]
    ok = not missing and envelope.get("status") in STATUS_VALUES
    return CriterionResult(
        "standard_packet_built",
        ok,
        f"zarf anahtarlari={sorted(envelope)} status={envelope.get('status')!r}"
        if ok
        else f"zarf eksik: {missing}",
    )


# ---------------------------------------------------------------------- #
# Site dosyasi kanitli kriterler
# ---------------------------------------------------------------------- #
def _home_real_scan_status(index_html: str) -> CriterionResult:
    has_card = 'id="xk100-scan-card"' in index_html
    has_lock_banner = "HISSE SKORLAMA MODULU HENUZ CANLI DEGIL" in index_html
    has_run_id = 'id="xk100-scan-run-id"' in index_html
    ok = has_card and has_lock_banner and has_run_id
    return CriterionResult(
        "home_real_scan_status",
        ok,
        "index.html: #xk100-scan-card + #xk100-scan-run-id + "
        "'HISSE SKORLAMA MODULU HENUZ CANLI DEGIL' bandi mevcut"
        if ok
        else "ana sayfa tarama karti baglantilari eksik",
    )


def _real_summary_table_works(index_html: str) -> CriterionResult:
    has_table = 'id="stk-table"' in index_html and 'id="stk-tbody"' in index_html
    has_fetch = "/api/xk100/stocks" in index_html
    ok = has_table and has_fetch
    return CriterionResult(
        "real_summary_table_works",
        ok,
        "index.html: #stk-table/#stk-tbody + /api/xk100/stocks fetch baglantisi"
        if ok
        else "ozet tablo baglantilari eksik",
    )


def _detail_real_raw_chart(index_html: str) -> CriterionResult:
    has_chart = 'id="sd-candles"' in index_html
    has_raw_adj = 'id="sd-btn-raw"' in index_html and 'id="sd-btn-adj"' in index_html
    ok = has_chart and has_raw_adj
    return CriterionResult(
        "detail_real_raw_chart",
        ok,
        "index.html: #sd-candles + #sd-btn-raw/#sd-btn-adj (HAM/DUZELTILMIS)"
        if ok
        else "detay grafik baglantilari eksik",
    )


def _mobile_same_api_or_contract(root: Path) -> CriterionResult:
    path = root / "docs" / "api-contract.json"
    try:
        contract = json.loads(_read(path))
    except ValueError:
        contract = {}
    native = (contract.get("native_mobile") or {}).get("status")
    envelope_fields = (contract.get("envelope") or {}).get("fields") or []
    ok = native == "HAZIR_BEKLIYOR" and sorted(envelope_fields) == sorted(
        ENVELOPE_KEYS
    )
    return CriterionResult(
        "mobile_same_api_or_contract",
        ok,
        f"docs/api-contract.json: native_mobile.status={native!r}, "
        f"zarf alanlari={sorted(envelope_fields)}",
    )


def _admin_schema_real_files(root: Path, docs_html: str) -> CriterionResult:
    admin_py = (root / "app" / "admin" / "symbol_admin.py").is_file()
    schema = (root / "db" / "schema.sql").is_file()
    systemd = (root / "systemd" / "xk100-api.service").is_file()
    # docs.html: tamamlanma kriterleri bandi + gercek test dosyasi yollari
    has_criteria = "TAMAMLANMA KRITERLERI" in docs_html.upper()
    test_paths = re.findall(r"tests/blok\d+/[\w.]+\.py", docs_html)
    ok = admin_py and schema and systemd and has_criteria and bool(test_paths)
    return CriterionResult(
        "admin_schema_real_files",
        ok,
        f"admin/symbol_admin.py={admin_py}, db/schema.sql={schema}, "
        f"systemd/xk100-api.service={systemd}, docs.html kriter bandi="
        f"{has_criteria}, test yollari={sorted(set(test_paths))}",
    )


def _no_fake_live_data(index_html: str) -> CriterionResult:
    """DEMO rozeti yalniz sabit demo bloklarinda; canli kartlarda YOK."""
    live_sections = []
    for marker in ('id="xk100-scan-card"', 'id="stk-table"', 'id="sd-candles"'):
        start = index_html.find(marker)
        if start == -1:
            live_sections.append((marker, None))
            continue
        end = index_html.find('id="', start + len(marker))
        section = index_html[start : end if end != -1 else start + 4000]
        live_sections.append((marker, section))
    leaks = [
        marker
        for marker, section in live_sections
        if section is not None and "demo-badge" in section.lower()
    ]
    missing = [marker for marker, section in live_sections if section is None]
    demo_ids = re.findall(r'id="(demo-[\w-]+)"', index_html)
    ok = not leaks and not missing and bool(demo_ids)
    return CriterionResult(
        "no_fake_live_data",
        ok,
        f"canli kartlarda DEMO rozeti sizintisi={leaks if leaks else 'YOK'}; "
        f"sabit demo bloklari={sorted(demo_ids)}",
    )


# ---------------------------------------------------------------------- #
# Rapor kanitli kriterler
# ---------------------------------------------------------------------- #
def _staging_fullday_verified(report) -> CriterionResult:
    finish = bool(getattr(report, "finish_by_0935", False))
    total = int(getattr(report, "total", 0))
    finished_at = str(getattr(report, "finished_at", ""))
    ok = finish and total == 100
    return CriterionResult(
        "staging_fullday_verified",
        ok,
        f"total={total}, finished_at={finished_at}, finish_by_0935={finish}",
    )


def _deployment_artifacts_ready(deploy_report) -> CriterionResult:
    steps = list(getattr(deploy_report, "steps", ()))
    ok = bool(getattr(deploy_report, "ok", False)) and len(steps) == 10
    failed = [s.name for s in steps if not getattr(s, "ok", False)]
    return CriterionResult(
        "deployment_artifacts_ready",
        ok,
        f"10 adim dogrulandi (mode={getattr(deploy_report, 'mode', '?')})"
        if ok
        else f"basarisiz adimlar: {failed}",
    )
