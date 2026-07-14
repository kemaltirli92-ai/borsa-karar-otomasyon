"""BLOK 7 - Veri Tabani ve Migration: TAM 100 pytest testi.

Kategoriler (toplam = 100, SPEC BLOK 7 bolum 7):
1. Migration ileri uygulama: 11 tablo olusumu, indexler, schema_migrations (16)
2. Benzersizlik kisitlari: run_id, run_id+stock_id,
   stock_id+trade_date+source+data_version, kap_notice_no vb. (18)
3. CHECK kisitlari: platform, status, data_layer, action_type,
   match_method, is_active araliklari (14)
4. Migration geri alma: rollback tek/cok adim, checksum uyusmazligi reddi,
   .down.sql yoksa hata, yarim transaction kalmaz (16)
5. Ham/temiz/dogrulanmis: katman insert, promote akisi, atlama yasagi,
   raw silinmez, promotions kaydi (14)
6. Yedek + kayip kontrolu: backup manifest, satir sayisi dogrulama, kayip
   tespiti, bos DB backup, safe_migrate senaryolari (14)
7. Repository yardimcilari + genel uc durumlar (FK, PRAGMA, idempotency) (8)

Her test BOS gecici DB (tmp_path) uzerinde calisir; gercek dosya DB'ye
dokunulmaz. Hicbir test ag erisimi yapmaz. Saat enjekte edilir
(deterministik).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3

import pytest

from app.services.stock_scanning.db import (
    MIGRATIONS_DIR,
    ChecksumMismatchError,
    DataLossError,
    MigrationError,
    MigrationRunner,
    MissingDownMigrationError,
    PromotionError,
    RepoError,
    StockScanRepo,
    backup_db,
    safe_migrate,
    verify_no_data_loss,
)

ELEVEN_TABLES = {
    "stock_universe",
    "stock_universe_memberships",
    "stock_symbol_mappings",
    "stock_scan_runs",
    "stock_scan_results",
    "stock_prices_daily",
    "stock_corporate_actions",
    "stock_trading_restrictions",
    "stock_news_matches",
    "stock_scan_errors",
    "source_health",
}


def fixed_clock() -> str:
    """Deterministik saat (testlerde enjekte edilir)."""
    return "2024-01-01T00:00:00Z"


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def runner(db_path):
    return MigrationRunner(db_path, clock=fixed_clock)


@pytest.fixture
def migrated_db(db_path, runner):
    runner.apply_all()
    return db_path


def connect(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def table_names(db_path):
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def index_names(db_path):
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def ins(conn, sql, params=()):
    conn.execute(sql, params)
    conn.commit()


def expect_integrity(conn, sql, params=()):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, params)
    conn.rollback()


def seed_run(conn, run_id="run-1", status="WAITING"):
    ins(
        conn,
        "INSERT INTO stock_scan_runs (run_id, run_date, status) VALUES (?, ?, ?)",
        (run_id, "2024-01-01", status),
    )


def seed_universe(conn, universe_id="u1"):
    ins(
        conn,
        "INSERT INTO stock_universe (universe_id, name) VALUES (?, ?)",
        (universe_id, "Ana Evren"),
    )


def copy_migrations(tmp_path):
    """Paket migration'larini tmp altina kopyalar (degisiklik testleri icin)."""
    dst = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, str(dst))
    return str(dst)


# ====================================================================== #
# 1) Migration ileri uygulama (16 test)
# ====================================================================== #
class TestMigrationApply:
    def test_apply_all_creates_all_tables(self, db_path, runner):
        runner.apply_all()
        names = table_names(db_path)
        assert ELEVEN_TABLES.issubset(names)
        # 11 tablo + data_layer_promotions + schema_migrations = 13
        assert len(names) == 13

    def test_status_fresh_all_pending(self, runner):
        st = runner.status()
        assert st["applied"] == []
        assert st["pending"] == ["0001", "0002"]
        assert st["current"] is None
        assert st["checksum_mismatches"] == []

    def test_apply_next_first_only(self, runner):
        assert runner.apply_next() == "0001"
        st = runner.status()
        assert st["applied"] == ["0001"]
        assert st["pending"] == ["0002"]

    def test_apply_next_twice_completes(self, runner):
        runner.apply_next()
        assert runner.apply_next() == "0002"
        assert runner.status()["pending"] == []

    def test_apply_next_none_when_done(self, runner):
        runner.apply_all()
        assert runner.apply_next() is None

    def test_apply_all_returns_versions(self, runner):
        assert runner.apply_all() == ["0001", "0002"]

    def test_apply_all_idempotent(self, runner):
        runner.apply_all()
        assert runner.apply_all() == []
        assert runner.applied_versions() == ["0001", "0002"]

    def test_schema_migrations_rows(self, db_path, runner):
        runner.apply_all()
        conn = connect(db_path)
        try:
            rows = conn.execute(
                "SELECT version, name, checksum, applied_at "
                "FROM schema_migrations ORDER BY version"
            ).fetchall()
        finally:
            conn.close()
        assert [r[0] for r in rows] == ["0001", "0002"]
        assert [r[1] for r in rows] == ["initial", "data_layers"]
        for row in rows:
            assert len(row[2]) == 64  # SHA-256 hex
            assert row[3] == "2024-01-01T00:00:00Z"  # enjekte saat

    def test_checksum_matches_sha256_of_file(self, db_path, runner):
        runner.apply_all()
        with open(os.path.join(MIGRATIONS_DIR, "0001_initial.sql"), "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        conn = connect(db_path)
        try:
            stored = conn.execute(
                "SELECT checksum FROM schema_migrations WHERE version='0001'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert stored == digest

    def test_eleven_table_names_exact(self, db_path, runner):
        runner.apply_all()
        names = table_names(db_path)
        assert ELEVEN_TABLES == names - {"schema_migrations", "data_layer_promotions"}

    def test_data_layer_promotions_created(self, db_path, runner):
        runner.apply_all()
        assert "data_layer_promotions" in table_names(db_path)

    def test_index_prices_stock_date(self, db_path, runner):
        runner.apply_all()
        assert "ix_prices_stock_date" in index_names(db_path)

    def test_index_scan_results_run(self, db_path, runner):
        runner.apply_all()
        assert "ix_scan_results_run" in index_names(db_path)

    def test_index_scan_errors_run_stage(self, db_path, runner):
        runner.apply_all()
        assert "ix_scan_errors_run_stage" in index_names(db_path)

    def test_index_news_matches_stock(self, db_path, runner):
        runner.apply_all()
        assert "ix_news_matches_stock" in index_names(db_path)

    def test_index_symbol_mappings_stock(self, db_path, runner):
        runner.apply_all()
        assert "ix_symbol_mappings_stock" in index_names(db_path)


# ====================================================================== #
# 2) Benzersizlik kisitlari (18 test)
# ====================================================================== #
class TestUniqueness:
    def test_duplicate_run_id_rejected(self, migrated_db):
        conn = connect(migrated_db)
        try:
            seed_run(conn, "run-1")
            expect_integrity(
                conn,
                "INSERT INTO stock_scan_runs (run_id, run_date, status) "
                "VALUES ('run-1', '2024-01-02', 'RUNNING')",
            )
        finally:
            conn.close()

    def test_distinct_run_ids_ok(self, migrated_db):
        conn = connect(migrated_db)
        try:
            seed_run(conn, "run-1")
            seed_run(conn, "run-2")
            count = conn.execute("SELECT COUNT(*) FROM stock_scan_runs").fetchone()[0]
            assert count == 2
        finally:
            conn.close()

    def test_scan_results_run_stock_unique(self, migrated_db):
        conn = connect(migrated_db)
        try:
            seed_run(conn)
            ins(
                conn,
                "INSERT INTO stock_scan_results (run_id, stock_id, result_status) "
                "VALUES ('run-1', 'THYAO', 'OK')",
            )
            expect_integrity(
                conn,
                "INSERT INTO stock_scan_results (run_id, stock_id, result_status) "
                "VALUES ('run-1', 'THYAO', 'FAILED')",
            )
        finally:
            conn.close()

    def test_scan_results_same_stock_other_run_ok(self, migrated_db):
        conn = connect(migrated_db)
        try:
            seed_run(conn, "run-1")
            seed_run(conn, "run-2")
            for rid in ("run-1", "run-2"):
                ins(
                    conn,
                    "INSERT INTO stock_scan_results (run_id, stock_id, result_status) "
                    "VALUES (?, 'THYAO', 'OK')",
                    (rid,),
                )
            count = conn.execute("SELECT COUNT(*) FROM stock_scan_results").fetchone()[0]
            assert count == 2
        finally:
            conn.close()

    def test_prices_unique_quartet_rejected(self, migrated_db):
        conn = connect(migrated_db)
        try:
            sql = (
                "INSERT INTO stock_prices_daily "
                "(stock_id, trade_date, source, data_version, data_layer) "
                "VALUES ('THYAO', '2024-01-01', 'bist', 'v1', 'raw')"
            )
            ins(conn, sql)
            expect_integrity(conn, sql)
        finally:
            conn.close()

    def test_prices_other_data_version_ok(self, migrated_db):
        conn = connect(migrated_db)
        try:
            for ver in ("v1", "v2"):
                ins(
                    conn,
                    "INSERT INTO stock_prices_daily "
                    "(stock_id, trade_date, source, data_version, data_layer) "
                    "VALUES ('THYAO', '2024-01-01', 'bist', ?, 'raw')",
                    (ver,),
                )
            assert conn.execute("SELECT COUNT(*) FROM stock_prices_daily").fetchone()[0] == 2
        finally:
            conn.close()

    def test_prices_other_source_ok(self, migrated_db):
        conn = connect(migrated_db)
        try:
            for src in ("bist", "yahoo"):
                ins(
                    conn,
                    "INSERT INTO stock_prices_daily "
                    "(stock_id, trade_date, source, data_version, data_layer) "
                    "VALUES ('THYAO', '2024-01-01', ?, 'v1', 'raw')",
                    (src,),
                )
            assert conn.execute("SELECT COUNT(*) FROM stock_prices_daily").fetchone()[0] == 2
        finally:
            conn.close()

    def test_prices_other_trade_date_ok(self, migrated_db):
        conn = connect(migrated_db)
        try:
            for day in ("2024-01-01", "2024-01-02"):
                ins(
                    conn,
                    "INSERT INTO stock_prices_daily "
                    "(stock_id, trade_date, source, data_version, data_layer) "
                    "VALUES ('THYAO', ?, 'bist', 'v1', 'raw')",
                    (day,),
                )
            assert conn.execute("SELECT COUNT(*) FROM stock_prices_daily").fetchone()[0] == 2
        finally:
            conn.close()

    def test_corporate_actions_kap_unique(self, migrated_db):
        conn = connect(migrated_db)
        try:
            ins(
                conn,
                "INSERT INTO stock_corporate_actions (stock_id, action_type, kap_notice_no) "
                "VALUES ('THYAO', 'dividend', 'KAP-2024-0001')",
            )
            expect_integrity(
                conn,
                "INSERT INTO stock_corporate_actions (stock_id, action_type, kap_notice_no) "
                "VALUES ('ASELS', 'bonus', 'KAP-2024-0001')",
            )
        finally:
            conn.close()

    def test_corporate_actions_kap_null_repeats_ok(self, migrated_db):
        conn = connect(migrated_db)
        try:
            for stock in ("THYAO", "ASELS"):
                ins(
                    conn,
                    "INSERT INTO stock_corporate_actions (stock_id, action_type) "
                    "VALUES (?, 'dividend')",
                    (stock,),
                )
            # SQLite: NULL kap_notice_no degerleri cakismaz
            assert conn.execute("SELECT COUNT(*) FROM stock_corporate_actions").fetchone()[0] == 2
        finally:
            conn.close()

    def test_restrictions_kap_unique(self, migrated_db):
        conn = connect(migrated_db)
        try:
            ins(
                conn,
                "INSERT INTO stock_trading_restrictions "
                "(stock_id, restriction_type, start_date, kap_notice_no) "
                "VALUES ('THYAO', 'tedbir', '2024-01-01', 'KAP-T-1')",
            )
            expect_integrity(
                conn,
                "INSERT INTO stock_trading_restrictions "
                "(stock_id, restriction_type, start_date, kap_notice_no) "
                "VALUES ('ASELS', 'tedbir', '2024-01-02', 'KAP-T-1')",
            )
        finally:
            conn.close()

    def test_symbol_mappings_triple_unique(self, migrated_db):
        conn = connect(migrated_db)
        try:
            ins(
                conn,
                "INSERT INTO stock_symbol_mappings "
                "(stock_id, platform, symbol, valid_from, valid_to) "
                "VALUES ('THYAO', 'bist', 'THYAO.IS', '2020-01-01', '2021-01-01')",
            )
            expect_integrity(
                conn,
                "INSERT INTO stock_symbol_mappings "
                "(stock_id, platform, symbol, valid_from, valid_to) "
                "VALUES ('THYAO', 'bist', 'THYAO.IS', '2020-01-01', '2022-01-01')",
            )
        finally:
            conn.close()

    def test_symbol_mappings_other_platform_ok(self, migrated_db):
        conn = connect(migrated_db)
        try:
            for platform in ("bist", "yahoo"):
                ins(
                    conn,
                    "INSERT INTO stock_symbol_mappings "
                    "(stock_id, platform, symbol, valid_from) "
                    "VALUES ('THYAO', ?, 'THYAO.IS', '2020-01-01')",
                    (platform,),
                )
            assert conn.execute("SELECT COUNT(*) FROM stock_symbol_mappings").fetchone()[0] == 2
        finally:
            conn.close()

    def test_symbol_mappings_active_pair_unique(self, migrated_db):
        conn = connect(migrated_db)
        try:
            ins(
                conn,
                "INSERT INTO stock_symbol_mappings "
                "(stock_id, platform, symbol, valid_from) "
                "VALUES ('THYAO', 'bist', 'THYAO.IS', '2020-01-01')",
            )
            # Ikinci aktif (valid_to NULL) ayni (platform, symbol) -> partial index
            expect_integrity(
                conn,
                "INSERT INTO stock_symbol_mappings "
                "(stock_id, platform, symbol, valid_from) "
                "VALUES ('THYAO', 'bist', 'THYAO.IS', '2021-01-01')",
            )
        finally:
            conn.close()

    def test_symbol_mappings_active_plus_closed_ok(self, migrated_db):
        conn = connect(migrated_db)
        try:
            ins(
                conn,
                "INSERT INTO stock_symbol_mappings "
                "(stock_id, platform, symbol, valid_from, valid_to) "
                "VALUES ('THYAO', 'bist', 'THYAO.IS', '2020-01-01', '2023-01-01')",
            )
            ins(
                conn,
                "INSERT INTO stock_symbol_mappings "
                "(stock_id, platform, symbol, valid_from) "
                "VALUES ('THYAO', 'bist', 'THYAO.IS', '2023-01-01')",
            )
            assert conn.execute("SELECT COUNT(*) FROM stock_symbol_mappings").fetchone()[0] == 2
        finally:
            conn.close()

    def test_memberships_triple_unique(self, migrated_db):
        conn = connect(migrated_db)
        try:
            seed_universe(conn)
            ins(
                conn,
                "INSERT INTO stock_universe_memberships "
                "(universe_id, stock_id, member_from) "
                "VALUES ('u1', 'THYAO', '2024-01-01')",
            )
            expect_integrity(
                conn,
                "INSERT INTO stock_universe_memberships "
                "(universe_id, stock_id, member_from) "
                "VALUES ('u1', 'THYAO', '2024-01-01')",
            )
        finally:
            conn.close()

    def test_news_matches_pair_unique(self, migrated_db):
        conn = connect(migrated_db)
        try:
            ins(
                conn,
                "INSERT INTO stock_news_matches (stock_id, news_id, source, match_method) "
                "VALUES ('THYAO', 'news-1', 'aa', 'code')",
            )
            expect_integrity(
                conn,
                "INSERT INTO stock_news_matches (stock_id, news_id, source, match_method) "
                "VALUES ('THYAO', 'news-1', 'bb', 'name')",
            )
        finally:
            conn.close()

    def test_source_health_pair_unique(self, migrated_db):
        conn = connect(migrated_db)
        try:
            ins(
                conn,
                "INSERT INTO source_health (source_name, checked_at, status) "
                "VALUES ('bist', '2024-01-01T00:00:00Z', 'OK')",
            )
            expect_integrity(
                conn,
                "INSERT INTO source_health (source_name, checked_at, status) "
                "VALUES ('bist', '2024-01-01T00:00:00Z', 'DOWN')",
            )
        finally:
            conn.close()


# ====================================================================== #
# 3) CHECK kisitlari (14 test)
# ====================================================================== #
class TestCheckConstraints:
    def test_platform_invalid_rejected(self, migrated_db):
        conn = connect(migrated_db)
        try:
            expect_integrity(
                conn,
                "INSERT INTO stock_symbol_mappings "
                "(stock_id, platform, symbol, valid_from) "
                "VALUES ('THYAO', 'borsa', 'X', '2024-01-01')",
            )
        finally:
            conn.close()

    def test_platform_all_valid(self, migrated_db):
        conn = connect(migrated_db)
        try:
            for i, platform in enumerate(
                ("bist", "yahoo", "google", "tradingview", "kap")
            ):
                ins(
                    conn,
                    "INSERT INTO stock_symbol_mappings "
                    "(stock_id, platform, symbol, valid_from) VALUES (?, ?, ?, ?)",
                    ("THYAO", platform, "SYM%d" % i, "2024-01-01"),
                )
            assert conn.execute("SELECT COUNT(*) FROM stock_symbol_mappings").fetchone()[0] == 5
        finally:
            conn.close()

    def test_run_status_invalid_rejected(self, migrated_db):
        conn = connect(migrated_db)
        try:
            expect_integrity(
                conn,
                "INSERT INTO stock_scan_runs (run_id, run_date, status) "
                "VALUES ('r1', '2024-01-01', 'DONE')",
            )
        finally:
            conn.close()

    def test_run_status_all_valid(self, migrated_db):
        conn = connect(migrated_db)
        try:
            for i, status in enumerate(
                ("WAITING", "RUNNING", "COMPLETED", "FAILED", "PARTIAL")
            ):
                ins(
                    conn,
                    "INSERT INTO stock_scan_runs (run_id, run_date, status) "
                    "VALUES (?, '2024-01-01', ?)",
                    ("r%d" % i, status),
                )
            assert conn.execute("SELECT COUNT(*) FROM stock_scan_runs").fetchone()[0] == 5
        finally:
            conn.close()

    def test_result_status_invalid_rejected(self, migrated_db):
        conn = connect(migrated_db)
        try:
            seed_run(conn)
            expect_integrity(
                conn,
                "INSERT INTO stock_scan_results (run_id, stock_id, result_status) "
                "VALUES ('run-1', 'THYAO', 'UNKNOWN')",
            )
        finally:
            conn.close()

    def test_quality_score_out_of_range_rejected(self, migrated_db):
        conn = connect(migrated_db)
        try:
            seed_run(conn)
            expect_integrity(
                conn,
                "INSERT INTO stock_scan_results "
                "(run_id, stock_id, result_status, data_quality_score) "
                "VALUES ('run-1', 'THYAO', 'OK', 1.5)",
            )
            expect_integrity(
                conn,
                "INSERT INTO stock_scan_results "
                "(run_id, stock_id, result_status, data_quality_score) "
                "VALUES ('run-1', 'THYAO', 'OK', -0.1)",
            )
        finally:
            conn.close()

    def test_quality_score_null_and_bounds_ok(self, migrated_db):
        conn = connect(migrated_db)
        try:
            seed_run(conn)
            for stock, score in (("A", None), ("B", 0.0), ("C", 1.0)):
                ins(
                    conn,
                    "INSERT INTO stock_scan_results "
                    "(run_id, stock_id, result_status, data_quality_score) "
                    "VALUES ('run-1', ?, 'OK', ?)",
                    (stock, score),
                )
            assert conn.execute("SELECT COUNT(*) FROM stock_scan_results").fetchone()[0] == 3
        finally:
            conn.close()

    def test_price_layer_invalid_rejected(self, migrated_db):
        conn = connect(migrated_db)
        try:
            expect_integrity(
                conn,
                "INSERT INTO stock_prices_daily "
                "(stock_id, trade_date, source, data_version, data_layer) "
                "VALUES ('THYAO', '2024-01-01', 'bist', 'v1', 'semi')",
            )
        finally:
            conn.close()

    def test_price_layer_all_valid(self, migrated_db):
        conn = connect(migrated_db)
        try:
            for layer in ("raw", "clean", "validated"):
                ins(
                    conn,
                    "INSERT INTO stock_prices_daily "
                    "(stock_id, trade_date, source, data_version, data_layer) "
                    "VALUES ('THYAO', '2024-01-01', 'bist', ?, ?)",
                    ("v-" + layer, layer),
                )
            assert conn.execute("SELECT COUNT(*) FROM stock_prices_daily").fetchone()[0] == 3
        finally:
            conn.close()

    def test_action_type_invalid_rejected(self, migrated_db):
        conn = connect(migrated_db)
        try:
            expect_integrity(
                conn,
                "INSERT INTO stock_corporate_actions (stock_id, action_type) "
                "VALUES ('THYAO', 'merger')",
            )
        finally:
            conn.close()

    def test_action_type_all_valid(self, migrated_db):
        conn = connect(migrated_db)
        try:
            for action in (
                "dividend", "bonus", "split", "capital_increase", "rights", "other"
            ):
                ins(
                    conn,
                    "INSERT INTO stock_corporate_actions (stock_id, action_type) "
                    "VALUES (?, ?)",
                    ("THYAO-" + action, action),
                )
            assert conn.execute("SELECT COUNT(*) FROM stock_corporate_actions").fetchone()[0] == 6
        finally:
            conn.close()

    def test_match_method_invalid_rejected(self, migrated_db):
        conn = connect(migrated_db)
        try:
            expect_integrity(
                conn,
                "INSERT INTO stock_news_matches (stock_id, news_id, source, match_method) "
                "VALUES ('THYAO', 'n1', 'aa', 'fuzzy')",
            )
        finally:
            conn.close()

    def test_is_active_range_enforced(self, migrated_db):
        conn = connect(migrated_db)
        try:
            expect_integrity(
                conn,
                "INSERT INTO stock_universe (universe_id, name, is_active) "
                "VALUES ('u1', 'X', 2)",
            )
            for flag in (0, 1):
                ins(
                    conn,
                    "INSERT INTO stock_universe (universe_id, name, is_active) "
                    "VALUES (?, 'X', ?)",
                    ("ok-%d" % flag, flag),
                )
            assert conn.execute("SELECT COUNT(*) FROM stock_universe").fetchone()[0] == 2
        finally:
            conn.close()

    def test_source_health_status_enforced(self, migrated_db):
        conn = connect(migrated_db)
        try:
            expect_integrity(
                conn,
                "INSERT INTO source_health (source_name, checked_at, status) "
                "VALUES ('bist', 't0', 'SLOW')",
            )
            for i, status in enumerate(("OK", "DEGRADED", "DOWN", "UNCHECKED")):
                ins(
                    conn,
                    "INSERT INTO source_health (source_name, checked_at, status) "
                    "VALUES ('bist', ?, ?)",
                    ("t%d" % (i + 1), status),
                )
            assert conn.execute("SELECT COUNT(*) FROM source_health").fetchone()[0] == 4
        finally:
            conn.close()


# ====================================================================== #
# 4) Migration geri alma (16 test)
# ====================================================================== #
class TestRollback:
    def test_rollback_one_removes_0002(self, db_path, runner):
        runner.apply_all()
        assert runner.rollback() == ["0002"]
        names = table_names(db_path)
        assert "data_layer_promotions" not in names
        assert ELEVEN_TABLES.issubset(names)
        assert runner.applied_versions() == ["0001"]

    def test_rollback_two_leaves_empty_schema(self, db_path, runner):
        runner.apply_all()
        assert runner.rollback(steps=2) == ["0002", "0001"]
        assert table_names(db_path) == {"schema_migrations"}
        conn = connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0
        finally:
            conn.close()

    def test_rollback_default_one_step(self, db_path, runner):
        runner.apply_all()
        runner.rollback()
        assert runner.status()["current"] == "0001"

    def test_rollback_empty_db_noop(self, runner):
        assert runner.rollback() == []
        assert runner.rollback(steps=3) == []

    def test_rollback_checksum_mismatch_refused(self, tmp_path, db_path):
        mig_dir = copy_migrations(tmp_path)
        runner = MigrationRunner(db_path, migrations_dir=mig_dir, clock=fixed_clock)
        runner.apply_all()
        # Uygulanmis 0002 dosyasina disaridan mudahale
        with open(os.path.join(mig_dir, "0002_data_layers.sql"), "a", encoding="utf-8") as fh:
            fh.write("\n-- disaridan eklenen satir\n")
        with pytest.raises(ChecksumMismatchError):
            runner.rollback()
        # Geri alma REDDEDILDI: tablo hala duruyor
        assert "data_layer_promotions" in table_names(db_path)
        assert runner.applied_versions() == ["0001", "0002"]

    def test_missing_down_file_rejected(self, tmp_path, db_path):
        mig_dir = tmp_path / "mig"
        mig_dir.mkdir()
        (mig_dir / "0001_solo.sql").write_text(
            "CREATE TABLE solo (id INTEGER);", encoding="utf-8"
        )
        with pytest.raises(MissingDownMigrationError):
            MigrationRunner(db_path, migrations_dir=str(mig_dir))

    def test_status_reports_checksum_mismatch(self, tmp_path, db_path):
        mig_dir = copy_migrations(tmp_path)
        runner = MigrationRunner(db_path, migrations_dir=mig_dir, clock=fixed_clock)
        runner.apply_all()
        with open(os.path.join(mig_dir, "0002_data_layers.sql"), "a", encoding="utf-8") as fh:
            fh.write("\n-- degisiklik\n")
        st = runner.status()
        assert st["checksum_mismatches"] == ["0002"]

    def test_apply_refused_on_checksum_mismatch(self, tmp_path, db_path):
        mig_dir = copy_migrations(tmp_path)
        runner = MigrationRunner(db_path, migrations_dir=mig_dir, clock=fixed_clock)
        runner.apply_next()  # 0001
        with open(os.path.join(mig_dir, "0001_initial.sql"), "a", encoding="utf-8") as fh:
            fh.write("\n-- degisiklik\n")
        with pytest.raises(ChecksumMismatchError):
            runner.apply_next()
        # 0002 uygulanmadi
        assert runner.applied_versions() == ["0001"]

    def test_failed_migration_rolls_back_objects(self, tmp_path, db_path):
        mig_dir = copy_migrations(tmp_path)
        with open(os.path.join(mig_dir, "0003_broken.sql"), "w", encoding="utf-8") as fh:
            fh.write(
                "CREATE TABLE broken_a (id INTEGER);\n"
                "INSERT INTO tablo_yok VALUES (1);\n"
            )
        with open(os.path.join(mig_dir, "0003_broken.down.sql"), "w", encoding="utf-8") as fh:
            fh.write("DROP TABLE IF EXISTS broken_a;\n")
        runner = MigrationRunner(db_path, migrations_dir=mig_dir, clock=fixed_clock)
        with pytest.raises(MigrationError):
            runner.apply_all()
        # Yarim kayit kalmadi: broken_a yok, onceki migration'lar saglam
        assert "broken_a" not in table_names(db_path)
        assert ELEVEN_TABLES.issubset(table_names(db_path))

    def test_failed_migration_no_meta_record(self, tmp_path, db_path):
        mig_dir = copy_migrations(tmp_path)
        with open(os.path.join(mig_dir, "0003_broken.sql"), "w", encoding="utf-8") as fh:
            fh.write("INSERT INTO tablo_yok VALUES (1);\n")
        with open(os.path.join(mig_dir, "0003_broken.down.sql"), "w", encoding="utf-8") as fh:
            fh.write("-- noop\n")
        runner = MigrationRunner(db_path, migrations_dir=mig_dir, clock=fixed_clock)
        with pytest.raises(MigrationError):
            runner.apply_all()
        assert runner.applied_versions() == ["0001", "0002"]
        conn = connect(db_path)
        try:
            assert conn.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version='0003'"
            ).fetchone()[0] == 0
        finally:
            conn.close()

    def test_broken_sql_raises_migration_error(self, tmp_path, db_path):
        mig_dir = copy_migrations(tmp_path)
        with open(os.path.join(mig_dir, "0003_badsql.sql"), "w", encoding="utf-8") as fh:
            fh.write("BU GECERSIZ SQL;\n")
        with open(os.path.join(mig_dir, "0003_badsql.down.sql"), "w", encoding="utf-8") as fh:
            fh.write("-- noop\n")
        runner = MigrationRunner(db_path, migrations_dir=mig_dir, clock=fixed_clock)
        with pytest.raises(MigrationError):
            runner.apply_all()
        assert runner.applied_versions() == ["0001", "0002"]

    def test_rollback_more_steps_than_applied(self, db_path, runner):
        runner.apply_next()  # sadece 0001
        assert runner.rollback(steps=5) == ["0001"]
        assert runner.applied_versions() == []

    def test_rollback_then_reapply(self, db_path, runner):
        runner.apply_all()
        runner.rollback()
        assert runner.apply_all() == ["0002"]
        assert "data_layer_promotions" in table_names(db_path)

    def test_rollback_keeps_other_data(self, db_path, runner):
        runner.apply_all()
        conn = connect(db_path)
        try:
            seed_universe(conn)
        finally:
            conn.close()
        runner.rollback(steps=1)  # sadece 0002 geri alinir
        conn = connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM stock_universe").fetchone()[0] == 1
        finally:
            conn.close()

    def test_apply_next_after_rollback(self, runner):
        runner.apply_all()
        runner.rollback()
        assert runner.apply_next() == "0002"
        assert runner.status()["pending"] == []

    def test_rollback_return_order(self, runner):
        runner.apply_all()
        assert runner.rollback(steps=2) == ["0002", "0001"]


# ====================================================================== #
# 5) Ham/temiz/dogrulanmis katmanlar (14 test)
# ====================================================================== #
class TestDataLayers:
    @pytest.fixture
    def repo(self, migrated_db):
        return StockScanRepo(migrated_db, clock=fixed_clock)

    def _layer(self, db_path, rid):
        conn = connect(db_path)
        try:
            return conn.execute(
                "SELECT data_layer FROM stock_prices_daily WHERE id = ?", (rid,)
            ).fetchone()[0]
        finally:
            conn.close()

    def test_insert_price_default_raw(self, migrated_db, repo):
        rid = repo.insert_price("THYAO", "2024-01-01", "bist", "v1")
        assert self._layer(migrated_db, rid) == "raw"

    def test_insert_price_explicit_layer(self, migrated_db, repo):
        rid = repo.insert_price(
            "THYAO", "2024-01-01", "bist", "v2", layer="clean", open=1.0, close=2.0
        )
        assert self._layer(migrated_db, rid) == "clean"

    def test_insert_price_bad_layer(self, repo):
        with pytest.raises(RepoError):
            repo.insert_price("THYAO", "2024-01-01", "bist", "v1", layer="semi")

    def test_promote_clean_updates_layer(self, migrated_db, repo):
        rid = repo.insert_price("THYAO", "2024-01-01", "bist", "v1")
        repo.promote_to_clean([rid])
        assert self._layer(migrated_db, rid) == "clean"

    def test_promote_clean_logs_promotion(self, migrated_db, repo):
        rid = repo.insert_price("THYAO", "2024-01-01", "bist", "v1")
        promo_ids = repo.promote_to_clean([rid], promoted_by="tester")
        conn = connect(migrated_db)
        try:
            row = conn.execute(
                "SELECT table_name, record_id, from_layer, to_layer, promoted_by, "
                "promoted_at, checksum_before, checksum_after "
                "FROM data_layer_promotions WHERE id = ?",
                (promo_ids[0],),
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == "stock_prices_daily"
        assert row[1] == rid
        assert (row[2], row[3]) == ("raw", "clean")
        assert row[4] == "tester"
        assert row[5] == "2024-01-01T00:00:00Z"
        assert row[6] and row[7]

    def test_promote_validated_from_clean(self, migrated_db, repo):
        rid = repo.insert_price("THYAO", "2024-01-01", "bist", "v1", layer="clean")
        repo.promote_to_validated([rid])
        assert self._layer(migrated_db, rid) == "validated"

    def test_promote_validated_from_raw_rejected(self, migrated_db, repo):
        rid = repo.insert_price("THYAO", "2024-01-01", "bist", "v1")
        with pytest.raises(PromotionError):
            repo.promote_to_validated([rid])  # atlama yasak
        assert self._layer(migrated_db, rid) == "raw"

    def test_promote_clean_from_clean_rejected(self, migrated_db, repo):
        rid = repo.insert_price("THYAO", "2024-01-01", "bist", "v1", layer="clean")
        with pytest.raises(PromotionError):
            repo.promote_to_clean([rid])

    def test_promote_clean_from_validated_rejected(self, migrated_db, repo):
        rid = repo.insert_price("THYAO", "2024-01-01", "bist", "v1", layer="validated")
        with pytest.raises(PromotionError):
            repo.promote_to_clean([rid])

    def test_raw_row_survives_promotion(self, migrated_db, repo):
        rid = repo.insert_price(
            "THYAO", "2024-01-01", "bist", "v1", open=10.0, close=12.5, volume=1000
        )
        repo.promote_to_clean([rid])
        conn = connect(migrated_db)
        try:
            rows = conn.execute("SELECT * FROM stock_prices_daily").fetchall()
            assert len(rows) == 1  # kayit SILINMEDI
            row = rows[0]
            assert row[0] == rid  # ayni id
            # ham veri korundu
            assert row[5] == 10.0 and row[8] == 12.5 and row[9] == 1000
        finally:
            conn.close()

    def test_full_chain_raw_clean_validated(self, migrated_db, repo):
        rid = repo.insert_price("THYAO", "2024-01-01", "bist", "v1")
        repo.promote_to_clean([rid])
        repo.promote_to_validated([rid])
        assert self._layer(migrated_db, rid) == "validated"
        conn = connect(migrated_db)
        try:
            transitions = conn.execute(
                "SELECT from_layer, to_layer FROM data_layer_promotions "
                "WHERE record_id = ? ORDER BY id",
                (rid,),
            ).fetchall()
        finally:
            conn.close()
        assert transitions == [("raw", "clean"), ("clean", "validated")]

    def test_promote_multiple_ids(self, migrated_db, repo):
        ids = [
            repo.insert_price("THYAO", "2024-01-0%d" % i, "bist", "v1")
            for i in (1, 2, 3)
        ]
        promo_ids = repo.promote_to_clean(ids)
        assert len(promo_ids) == 3
        for rid in ids:
            assert self._layer(migrated_db, rid) == "clean"

    def test_promote_atomic_rollback(self, migrated_db, repo):
        good = repo.insert_price("THYAO", "2024-01-01", "bist", "v1")
        bad = repo.insert_price("THYAO", "2024-01-02", "bist", "v1", layer="clean")
        with pytest.raises(PromotionError):
            repo.promote_to_clean([good, bad])
        # Atomik: good da yukseltilmedi, promotion kaydi yok
        assert self._layer(migrated_db, good) == "raw"
        conn = connect(migrated_db)
        try:
            assert conn.execute("SELECT COUNT(*) FROM data_layer_promotions").fetchone()[0] == 0
        finally:
            conn.close()

    def test_promote_missing_id_rejected(self, migrated_db, repo):
        repo.insert_price("THYAO", "2024-01-01", "bist", "v1")
        with pytest.raises(PromotionError):
            repo.promote_to_clean([99999])


# ====================================================================== #
# 6) Yedek + kayip kontrolu (14 test)
# ====================================================================== #
class TestBackup:
    def test_backup_copy_and_manifest_exist(self, tmp_path, migrated_db):
        result = backup_db(migrated_db, str(tmp_path / "bak"), clock=fixed_clock)
        assert result["backup_path"] is not None
        assert os.path.isfile(result["backup_path"])
        assert os.path.isfile(result["manifest_path"])
        with open(result["manifest_path"], "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        assert manifest["tables"]  # en az bir tablo
        assert manifest["backup_file"] == os.path.basename(result["backup_path"])

    def test_manifest_row_counts(self, tmp_path, migrated_db):
        conn = connect(migrated_db)
        try:
            seed_universe(conn, "u1")
            seed_universe(conn, "u2")
        finally:
            conn.close()
        result = backup_db(migrated_db, str(tmp_path / "bak"), clock=fixed_clock)
        assert result["manifest"]["tables"]["stock_universe"]["row_count"] == 2
        assert result["manifest"]["tables"]["stock_prices_daily"]["row_count"] == 0

    def test_manifest_checksum_present(self, tmp_path, migrated_db):
        result = backup_db(migrated_db, str(tmp_path / "bak"), clock=fixed_clock)
        checksum = result["manifest"]["tables"]["stock_universe"]["checksum"]
        assert isinstance(checksum, str) and len(checksum) == 64

    def test_backup_empty_db_ok(self, tmp_path):
        empty_db = str(tmp_path / "bos.db")
        sqlite3.connect(empty_db).close()  # tablosuz, 0 bayt dosya
        result = backup_db(empty_db, str(tmp_path / "bak"), clock=fixed_clock)
        assert result["manifest"]["tables"] == {}
        assert os.path.isfile(result["manifest_path"])

    def test_backup_missing_db_ok(self, tmp_path):
        missing = str(tmp_path / "yok.db")
        result = backup_db(missing, str(tmp_path / "bak"), clock=fixed_clock)
        assert result["backup_path"] is None
        assert result["manifest"]["tables"] == {}
        assert result["manifest"]["db_existed"] is False
        assert os.path.isfile(result["manifest_path"])

    def test_verify_identical_ok(self, tmp_path, migrated_db):
        result = backup_db(migrated_db, str(tmp_path / "bak"), clock=fixed_clock)
        report = verify_no_data_loss(result["backup_path"], migrated_db)
        assert report["ok"] is True
        assert report["missing"] == {}

    def test_verify_missing_rows_raises(self, tmp_path, migrated_db):
        conn = connect(migrated_db)
        try:
            seed_universe(conn, "u1")
            seed_universe(conn, "u2")
        finally:
            conn.close()
        target = str(tmp_path / "kopya.db")
        shutil.copy2(migrated_db, target)
        conn = connect(target)
        try:
            conn.execute("DELETE FROM stock_universe WHERE universe_id='u2'")
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(DataLossError):
            verify_no_data_loss(migrated_db, target)

    def test_verify_reports_table_and_count(self, tmp_path, migrated_db):
        conn = connect(migrated_db)
        try:
            seed_universe(conn, "u1")
            seed_universe(conn, "u2")
        finally:
            conn.close()
        target = str(tmp_path / "kopya.db")
        shutil.copy2(migrated_db, target)
        conn = connect(target)
        try:
            conn.execute("DELETE FROM stock_universe")
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(DataLossError) as exc_info:
            verify_no_data_loss(migrated_db, target)
        assert exc_info.value.report["missing"] == {"stock_universe": 2}
        assert "stock_universe" in str(exc_info.value)

    def test_verify_missing_table_raises(self, tmp_path, migrated_db):
        # Hedefte satirli bir tablo dusurulurse satir kaybi olarak yakalanir.
        conn = connect(migrated_db)
        try:
            ins(
                conn,
                "INSERT INTO source_health (source_name, checked_at, status) "
                "VALUES ('bist', 't0', 'OK')",
            )
        finally:
            conn.close()
        target = str(tmp_path / "kopya.db")
        shutil.copy2(migrated_db, target)
        conn = connect(target)
        try:
            conn.execute("DROP TABLE source_health")
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(DataLossError) as exc_info:
            verify_no_data_loss(migrated_db, target)
        assert exc_info.value.report["missing"] == {"source_health": 1}

    def test_verify_more_rows_ok(self, tmp_path, migrated_db):
        target = str(tmp_path / "kopya.db")
        shutil.copy2(migrated_db, target)
        conn = connect(target)
        try:
            seed_universe(conn, "ekstra")
        finally:
            conn.close()
        report = verify_no_data_loss(migrated_db, target)
        assert report["ok"] is True

    def test_safe_migrate_success(self, tmp_path, db_path, runner):
        runner.apply_next()  # 0001
        conn = connect(db_path)
        try:
            seed_universe(conn)
        finally:
            conn.close()
        result = safe_migrate(runner, db_path, str(tmp_path / "bak"), clock=fixed_clock)
        assert result["applied"] == ["0002"]
        assert result["verified"] is True
        assert "data_layer_promotions" in table_names(db_path)
        conn = connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM stock_universe").fetchone()[0] == 1
        finally:
            conn.close()

    def test_safe_migrate_makes_backup(self, tmp_path, db_path, runner):
        runner.apply_all()
        backup_dir = str(tmp_path / "bak")
        safe_migrate(runner, db_path, backup_dir, clock=fixed_clock)
        files = os.listdir(backup_dir)
        assert any(f.endswith(".db") for f in files)
        assert any(f.endswith(".manifest.json") for f in files)

    def test_safe_migrate_restores_on_loss(self, tmp_path, db_path):
        mig_dir = copy_migrations(tmp_path)
        with open(os.path.join(mig_dir, "0003_danger.sql"), "w", encoding="utf-8") as fh:
            fh.write("DELETE FROM stock_universe;\n")
        with open(os.path.join(mig_dir, "0003_danger.down.sql"), "w", encoding="utf-8") as fh:
            fh.write("-- noop: silinen satirlar yedekten gelir\n")
        runner = MigrationRunner(db_path, migrations_dir=mig_dir, clock=fixed_clock)
        runner.apply_next()  # 0001
        runner.apply_next()  # 0002
        conn = connect(db_path)
        try:
            seed_universe(conn, "u1")
            seed_universe(conn, "u2")
        finally:
            conn.close()
        with pytest.raises(DataLossError):
            safe_migrate(runner, db_path, str(tmp_path / "bak"), clock=fixed_clock)
        # Otomatik geri alindi: veriler yedekten restore edildi
        conn = connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM stock_universe").fetchone()[0] == 2
            versions = [r[0] for r in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()]
        finally:
            conn.close()
        assert versions == ["0001", "0002"]

    def test_safe_migrate_empty_db(self, tmp_path):
        db = str(tmp_path / "bos.db")
        runner = MigrationRunner(db, clock=fixed_clock)
        result = safe_migrate(runner, db, str(tmp_path / "bak"), clock=fixed_clock)
        assert result["applied"] == ["0001", "0002"]
        # Bos DB senaryosu: yedek hata vermez; manifest'te veri tablosu yok
        # (runner'in olusturdugu meta tablo disinda) ve satir sayisi 0'dir.
        tables = result["backup"]["manifest"]["tables"]
        assert set(tables) <= {"schema_migrations"}
        assert all(t["row_count"] == 0 for t in tables.values())
        assert ELEVEN_TABLES.issubset(table_names(db))


# ====================================================================== #
# 7) Repository yardimcilari + genel uc durumlar (8 test)
# ====================================================================== #
class TestRepoAndGeneral:
    def test_fk_enforced_scan_results(self, migrated_db):
        conn = connect(migrated_db)
        try:
            expect_integrity(
                conn,
                "INSERT INTO stock_scan_results (run_id, stock_id, result_status) "
                "VALUES ('olmayan-run', 'THYAO', 'OK')",
            )
        finally:
            conn.close()

    def test_runner_connect_pragma_on(self, runner):
        conn = runner.connect()
        try:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        finally:
            conn.close()

    def test_idempotent_single_meta_row(self, db_path, runner):
        runner.apply_all()
        runner.apply_all()
        conn = connect(db_path)
        try:
            assert conn.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version='0001'"
            ).fetchone()[0] == 1
        finally:
            conn.close()

    def test_db_file_created_on_disk(self, db_path):
        assert not os.path.exists(db_path)
        runner = MigrationRunner(db_path, clock=fixed_clock)
        runner.apply_all()
        assert os.path.isfile(db_path)
        assert os.path.getsize(db_path) > 0

    def test_repo_insert_without_schema_fails(self, tmp_path):
        bare_db = str(tmp_path / "cipsiz.db")
        repo = StockScanRepo(bare_db, clock=fixed_clock)
        with pytest.raises(sqlite3.OperationalError):
            repo.insert_price("THYAO", "2024-01-01", "bist", "v1")

    def test_promotion_checksums_differ(self, migrated_db):
        repo = StockScanRepo(migrated_db, clock=fixed_clock)
        rid = repo.insert_price("THYAO", "2024-01-01", "bist", "v1", close=5.0)
        promo_ids = repo.promote_to_clean([rid])
        conn = connect(migrated_db)
        try:
            row = conn.execute(
                "SELECT checksum_before, checksum_after FROM data_layer_promotions "
                "WHERE id = ?",
                (promo_ids[0],),
            ).fetchone()
        finally:
            conn.close()
        assert row[0] != row[1]
        assert len(row[0]) == 64 and len(row[1]) == 64

    def test_two_dbs_independent(self, tmp_path):
        db1 = str(tmp_path / "a.db")
        db2 = str(tmp_path / "b.db")
        MigrationRunner(db1, clock=fixed_clock).apply_all()
        runner2 = MigrationRunner(db2, clock=fixed_clock)
        assert ELEVEN_TABLES.issubset(table_names(db1))
        # db2'ye henuz migration uygulanmadi
        assert table_names(db2) == {"schema_migrations"}
        assert runner2.status()["pending"] == ["0001", "0002"]

    def test_status_after_rollback_consistent(self, runner):
        runner.apply_all()
        runner.rollback()
        st = runner.status()
        assert st["applied"] == ["0001"]
        assert st["pending"] == ["0002"]
        assert st["current"] == "0001"
        assert st["checksum_mismatches"] == []
