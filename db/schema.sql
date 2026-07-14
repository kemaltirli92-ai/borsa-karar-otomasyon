-- BLOK 7 / Migration 0001 (ileri): Bolum 3 Hisse Taramasi veri semasi.
-- 11 tablo + indexler. Timestamps ISO-8601 TEXT. Baglantida
-- PRAGMA foreign_keys=ON zorunludur (MigrationRunner.connect bunu acar).

-- 1) Evren (universe) tanimlari
CREATE TABLE stock_universe (
    universe_id    TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    source_url     TEXT,
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    effective_from TEXT,
    effective_to   TEXT,
    created_at     TEXT
);

-- 2) Evren uyelikleri (zaman aralikli)
CREATE TABLE stock_universe_memberships (
    id          INTEGER PRIMARY KEY,
    universe_id TEXT NOT NULL REFERENCES stock_universe(universe_id),
    stock_id    TEXT NOT NULL,
    member_from TEXT NOT NULL,
    member_to   TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    UNIQUE (universe_id, stock_id, member_from)
);

-- 3) Platform sembol eslemeleri
CREATE TABLE stock_symbol_mappings (
    id         INTEGER PRIMARY KEY,
    stock_id   TEXT NOT NULL,
    platform   TEXT NOT NULL CHECK (platform IN ('bist', 'yahoo', 'google', 'tradingview', 'kap')),
    symbol     TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to   TEXT,
    is_active  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    UNIQUE (platform, symbol, valid_from)
);

-- Aktif (valid_to IS NULL) kayitlar icin ayni (platform, symbol) cifti tek olabilir.
CREATE UNIQUE INDEX ux_symbol_mappings_active
    ON stock_symbol_mappings (platform, symbol)
    WHERE valid_to IS NULL;

CREATE INDEX ix_symbol_mappings_stock
    ON stock_symbol_mappings (stock_id);

-- 4) Tarama kosulari (run_id benzersiz)
CREATE TABLE stock_scan_runs (
    run_id         TEXT PRIMARY KEY,
    run_date       TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('WAITING', 'RUNNING', 'COMPLETED', 'FAILED', 'PARTIAL')),
    started_at     TEXT,
    completed_at   TEXT,
    total_stocks   INTEGER,
    error_count    INTEGER,
    config_version TEXT
);

-- 5) Tarama sonuclari (run_id + stock_id benzersiz)
CREATE TABLE stock_scan_results (
    id                 INTEGER PRIMARY KEY,
    run_id             TEXT NOT NULL REFERENCES stock_scan_runs(run_id),
    stock_id           TEXT NOT NULL,
    result_status      TEXT NOT NULL CHECK (result_status IN ('OK', 'MISSING_DATA', 'FAILED', 'PENDING')),
    data_quality_score REAL CHECK (data_quality_score IS NULL OR (data_quality_score >= 0.0 AND data_quality_score <= 1.0)),
    payload_json       TEXT,
    UNIQUE (run_id, stock_id)
);

CREATE INDEX ix_scan_results_run
    ON stock_scan_results (run_id);

-- 6) Gunluk fiyatlar (ham/temiz/dogrulanmis katmanli)
CREATE TABLE stock_prices_daily (
    id           INTEGER PRIMARY KEY,
    stock_id     TEXT NOT NULL,
    trade_date   TEXT NOT NULL,
    source       TEXT NOT NULL,
    data_version TEXT NOT NULL,
    open         REAL,
    high         REAL,
    low          REAL,
    close        REAL,
    volume       INTEGER,
    data_layer   TEXT NOT NULL DEFAULT 'raw' CHECK (data_layer IN ('raw', 'clean', 'validated')),
    UNIQUE (stock_id, trade_date, source, data_version)
);

CREATE INDEX ix_prices_stock_date
    ON stock_prices_daily (stock_id, trade_date);

-- 7) Kurumsal aksiyonlar (KAP bildirim numarasi benzersiz)
CREATE TABLE stock_corporate_actions (
    id                INTEGER PRIMARY KEY,
    stock_id          TEXT NOT NULL,
    action_type       TEXT NOT NULL CHECK (action_type IN ('dividend', 'bonus', 'split', 'capital_increase', 'rights', 'other')),
    announcement_date TEXT,
    effective_date    TEXT,
    ratio             TEXT,
    kap_notice_no     TEXT UNIQUE,
    source            TEXT,
    data_layer        TEXT NOT NULL DEFAULT 'raw' CHECK (data_layer IN ('raw', 'clean', 'validated'))
);

-- 8) Islem kisitlari
CREATE TABLE stock_trading_restrictions (
    id               INTEGER PRIMARY KEY,
    stock_id         TEXT NOT NULL,
    restriction_type TEXT NOT NULL,
    start_date       TEXT NOT NULL,
    end_date         TEXT,
    source           TEXT,
    kap_notice_no    TEXT UNIQUE,
    is_active        INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

-- 9) Haber eslesmeleri
CREATE TABLE stock_news_matches (
    id           INTEGER PRIMARY KEY,
    stock_id     TEXT NOT NULL,
    news_id      TEXT NOT NULL,
    headline     TEXT,
    source       TEXT NOT NULL,
    published_at TEXT,
    matched_at   TEXT,
    match_method TEXT CHECK (match_method IN ('code', 'name', 'manual')),
    UNIQUE (stock_id, news_id)
);

CREATE INDEX ix_news_matches_stock
    ON stock_news_matches (stock_id);

-- 10) Tarama hatalari
CREATE TABLE stock_scan_errors (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT REFERENCES stock_scan_runs(run_id),
    stock_id    TEXT,
    stage       TEXT NOT NULL,
    error_type  TEXT NOT NULL,
    message     TEXT,
    occurred_at TEXT,
    resolved    INTEGER NOT NULL DEFAULT 0 CHECK (resolved IN (0, 1))
);

CREATE INDEX ix_scan_errors_run_stage
    ON stock_scan_errors (run_id, stage);

-- 11) Kaynak sagligi
CREATE TABLE source_health (
    id          INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL,
    checked_at  TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('OK', 'DEGRADED', 'DOWN', 'UNCHECKED')),
    latency_ms  INTEGER,
    fail_count  INTEGER NOT NULL DEFAULT 0,
    note        TEXT,
    UNIQUE (source_name, checked_at)
);

-- 0002: veri katmanlari
-- BLOK 7 / Migration 0002 (ileri): ham/temiz/dogrulanmis katman ayrimi.
-- Katman alanlari (data_layer) 0001'de stock_prices_daily ve
-- stock_corporate_actions uzerinde tanimli. Bu migration, katman
-- gecislerini izlenebilir kilmak icin data_layer_promotions tablosunu ekler.

CREATE TABLE data_layer_promotions (
    id              INTEGER PRIMARY KEY,
    table_name      TEXT NOT NULL,
    record_id       INTEGER NOT NULL,
    from_layer      TEXT NOT NULL CHECK (from_layer IN ('raw', 'clean', 'validated')),
    to_layer        TEXT NOT NULL CHECK (to_layer IN ('raw', 'clean', 'validated')),
    promoted_at     TEXT NOT NULL,
    promoted_by     TEXT,
    checksum_before TEXT,
    checksum_after  TEXT
);

CREATE INDEX ix_promotions_record
    ON data_layer_promotions (table_name, record_id);
