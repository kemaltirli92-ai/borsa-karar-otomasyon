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
