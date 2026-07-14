-- BLOK 7 / Migration 0001 (geri alma): 0001_initial.sql ile olusan
-- 11 tabloyu (ve indexlerini) kaldirir. Once cocuk tablolar (FK kaynakli),
-- sonra ebeveyn tablolar dusurulur. Indexler tabloyla birlikte duser.

DROP TABLE IF EXISTS source_health;
DROP TABLE IF EXISTS stock_scan_errors;
DROP TABLE IF EXISTS stock_news_matches;
DROP TABLE IF EXISTS stock_trading_restrictions;
DROP TABLE IF EXISTS stock_corporate_actions;
DROP TABLE IF EXISTS stock_prices_daily;
DROP TABLE IF EXISTS stock_scan_results;
DROP TABLE IF EXISTS stock_scan_runs;
DROP TABLE IF EXISTS stock_symbol_mappings;
DROP TABLE IF EXISTS stock_universe_memberships;
DROP TABLE IF EXISTS stock_universe;
